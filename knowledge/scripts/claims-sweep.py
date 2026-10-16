#!/usr/bin/env python3
"""claims-sweep.py — nightly claims/queue/liveness sweep (P4 REAPER, fusion 2026-10-13).

Sweeps, read-only:
  1. STALE IN-FLIGHT CLAIMS  — mission-control events.jsonl claim rows whose
     workstream's latest claim is still state=in-flight and older than 72h.
     A stale claim on a prod-gated action = possible unfinished prod state.
  2. LIVE VERIFY — read-only `wt recipes get <id>` on extractable recipe IDs.
     Verdicts: EXISTS / MISSING / UNVERIFIED. MISSING-or-STOPPED on a gated
     claim is flagged POSSIBLE UNFINISHED PROD STATE (highest severity).
  3. NEEDS-JOSH AGING — closeout rows state=needs-josh bucketed <72h / 3-7d / >7d.
  4. SILENT AGENTS — dreams/bus/*.jsonl: rows ever, last-post age. Flags 0-row
     agents (silent since creation) and >7d-silent agents. One-row one-shot
     archives are listed with a note, not accused.

Outputs (idempotent, overwrite never append):
  ~/.claude/knowledge/reports/claims-sweep-<YYYY-MM-DD>.md   (human report)
  ~/.claude/knowledge/reports/claims-sweep-latest.json       (machine cache)

Modes: --report (human stdout + files)  |  --json (JSON stdout + files).
Pure stdlib, system python 3.9. Read-only on all ledgers. wt usage is
read-only (recipes get); any wt failure degrades that row to UNVERIFIED.
"""
import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
import datetime

HOME = os.path.expanduser("~")
EVENTS = os.path.join(HOME, ".claude", "knowledge", "mission-control", "events.jsonl")
BUS = os.path.join(HOME, ".claude", "knowledge", "dreams", "bus")
REPORTS = os.path.join(HOME, ".claude", "knowledge", "reports")

STALE_HOURS = 72
SILENT_DAYS = 7
LIVE_VERIFY_CAP = 4          # max wt subprocess calls per sweep (keeps runtime bounded)
WT_TIMEOUT_S = 4             # per-call timeout; failure => UNVERIFIED, never fatal

GATED_KEYWORDS = ("prod", "production", "promot", "deploy", "uat")  # prod-gated action heuristics

# bus files that are metadata registries, not agent outboxes — listed for
# completeness but their liveness is not a fleet-liveness signal
NON_AGENT_FILES = {"channels-registry"}


def now_ts():
    return time.time()


def parse_ts(s):
    """Tolerant ISO-8601 parser: Z, naive, offset+micro, epoch float all accepted.
    Returns epoch or None."""
    if isinstance(s, (int, float)):
        return float(s)
    if not s or not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        d = datetime.datetime.fromisoformat(t)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                d = datetime.datetime.strptime(t[:19], fmt)
                d = d.replace(tzinfo=datetime.timezone.utc)
                break
            except ValueError:
                continue
        else:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=datetime.timezone.utc)
    return d.timestamp()


def read_events():
    rows = []
    try:
        with open(EVENTS) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                r["_epoch"] = parse_ts(r.get("ts"))
                rows.append(r)
    except OSError as e:
        print("ERROR: cannot read %s: %s" % (EVENTS, e), file=sys.stderr)
        sys.exit(1)
    rows.sort(key=lambda r: r["_epoch"] or 0)
    return rows


def extract_recipe_ids(text):
    """Primary: 8-digit number named as a recipe nearby. Secondary: bare 8-digit tokens
    (may be connections/tables — flagged ambiguous, not asserted as recipes)."""
    out, seen = [], set()
    for m in re.finditer(r"recipe\D{0,20}?(\d{8})\b", text or "", re.I):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            out.append({"id": m.group(1), "context": "named-recipe"})
    bare = re.findall(r"\b(\d{8})\b", text or "")
    for rid in bare:
        if rid not in seen:
            seen.add(rid)
            out.append({"id": rid, "context": "bare-8digit"})
    return out


def is_gated(row):
    blob = " ".join(str(row.get(k, "")) for k in ("what", "why", "end", "needs")).lower()
    return any(k in blob for k in GATED_KEYWORDS)


def live_verify(rid):
    """Read-only existence check via wt. Returns dict verdict/running/name."""
    try:
        r = subprocess.run(
            ["/usr/bin/env", "wt", "recipes", "get", rid, "--raw"],
            capture_output=True, text=True, timeout=WT_TIMEOUT_S,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {"recipe_id": rid, "verdict": "UNVERIFIED", "running": None, "name": "",
                "detail": "wt call failed or timed out"}
    if r.returncode == 0 and r.stdout.strip().startswith("{"):
        try:
            d = json.loads(r.stdout)
            return {"recipe_id": rid, "verdict": "EXISTS", "running": bool(d.get("running")),
                    "name": d.get("name", ""), "detail": "wt recipes get ok"}
        except ValueError:
            return {"recipe_id": rid, "verdict": "UNVERIFIED", "running": None, "name": "",
                    "detail": "wt returned unparseable JSON"}
    blob = (r.stderr or "") + (r.stdout or "")
    if "404" in blob or "not found" in blob.lower() or "Not Found" in blob:
        return {"recipe_id": rid, "verdict": "MISSING", "running": None, "name": "",
                "detail": "wt reports not found"}
    return {"recipe_id": rid, "verdict": "UNVERIFIED", "running": None, "name": "",
            "detail": "wt exit %s: %s" % (r.returncode, blob.strip()[:120])}


def sweep_stale_claims(rows):
    """A claim is STALE when it is the latest activity for its workstream, is a
    claim row with state=in-flight, and is older than STALE_HOURS."""
    latest_per_ws = {}
    for r in rows:
        ws = r.get("workstream")
        if not ws:
            continue
        prev = latest_per_ws.get(ws)
        if prev is None or (r["_epoch"] or 0) >= (prev["_epoch"] or 0):
            latest_per_ws[ws] = r
    stale = []
    for r in rows:
        if r.get("event") != "claim" or r.get("state") != "in-flight":
            continue
        if (r["_epoch"] or 0) > now_ts() - STALE_HOURS * 3600:
            continue
        if latest_per_ws.get(r.get("workstream")) is not r:
            continue  # superseded by a later claim/closeout row
        stale.append({
            "workstream": r.get("workstream", ""),
            "jira": r.get("jira", ""),
            "ts": r.get("ts", ""),
            "age_hours": round((now_ts() - (r["_epoch"] or 0)) / 3600, 1),
            "gated": is_gated(r),
            "what": (r.get("what") or "")[:220],
            "recipe_ids": extract_recipe_ids(r.get("what") or ""),
            "by": r.get("by", ""),
        })
    stale.sort(key=lambda s: -s["age_hours"])
    return stale


def sweep_needs_josh(rows):
    """Latest closeout per workstream with state=needs-josh, bucketed by age."""
    latest = {}
    for r in rows:
        if r.get("event") != "closeout" or r.get("state") != "needs-josh":
            continue
        ws = r.get("workstream", "")
        prev = latest.get(ws)
        if prev is None or (r["_epoch"] or 0) >= (prev["_epoch"] or 0):
            latest[ws] = r
    buckets = {"under_72h": [], "d3_7": [], "over_7d": []}
    for ws, r in latest.items():
        age_d = (now_ts() - (r["_epoch"] or 0)) / 86400
        item = {
            "workstream": ws,
            "jira": r.get("jira", ""),
            "ts": r.get("ts", ""),
            "age_days": round(age_d, 1),
            "what": (r.get("what") or "")[:160],
            "needs": (r.get("needs") or "")[:160],
        }
        if age_d < 3:
            buckets["under_72h"].append(item)
        elif age_d <= 7:
            buckets["d3_7"].append(item)
        else:
            buckets["over_7d"].append(item)
    for b in buckets.values():
        b.sort(key=lambda i: -i["age_days"])
    return buckets


def sweep_silent_agents():
    agents = []
    for path in sorted(glob.glob(os.path.join(BUS, "*.jsonl"))):
        name = os.path.basename(path)[:-6]
        rows_n, last = 0, None
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    rows_n += 1
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    # registry-style files carry last_seen instead of ts
                    e = parse_ts(row.get("ts"))
                    if e is None:
                        e = parse_ts(row.get("last_seen"))
                    if e and (last is None or e > last):
                        last = e
        except OSError:
            agents.append({"agent": name, "rows": None, "last_ts": "", "age_days": None,
                           "silent": True, "note": "unreadable file"})
            continue
        age_d = (now_ts() - last) / 86400 if last else None
        note = ""
        if name in NON_AGENT_FILES:
            note = "registry file, not an agent outbox — excluded from silent count"
        elif rows_n == 0:
            note = "0 rows EVER — no alarm has ever fired on this agent"
        elif rows_n <= 2 and age_d is not None and age_d > SILENT_DAYS:
            note = "one-shot archive? (single-row outbox) — listed, not accused"
        silent = (name not in NON_AGENT_FILES
                  and (rows_n == 0 or age_d is None or age_d > SILENT_DAYS))
        agents.append({
            "agent": name,
            "rows": rows_n,
            "last_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(last)) if last else "",
            "age_days": round(age_d, 1) if age_d is not None else None,
            "silent": silent,
            "note": note,
        })
    return agents


def run_sweep():
    rows = read_events()
    stale = sweep_stale_claims(rows)
    # live verify named-recipe IDs first (bare 8-digit tokens may be connections)
    verify = []
    ids = [ri for s in stale for ri in s["recipe_ids"] if ri["context"] == "named-recipe"]
    seen = set()
    for ri in ids:
        if ri["id"] in seen:
            continue
        seen.add(ri["id"])
        if len(verify) >= LIVE_VERIFY_CAP:
            verify.append({"recipe_id": ri["id"], "verdict": "UNVERIFIED",
                           "running": None, "name": "", "detail": "live-verify cap reached"})
            continue
        verify.append(live_verify(ri["id"]))
    verdict_by_id = {v["recipe_id"]: v for v in verify}
    for s in stale:
        s["verify"] = [verdict_by_id[ri["id"]] for ri in s["recipe_ids"] if ri["id"] in verdict_by_id]
        s["flag_prod_state"] = any(
            s["gated"] and (v["verdict"] == "MISSING"
                            or (v["verdict"] == "EXISTS" and v["running"] is False))
            for v in s["verify"])
    flagged = sum(1 for s in stale if s["flag_prod_state"])
    nj = sweep_needs_josh(rows)
    agents = sweep_silent_agents()
    silent_n = sum(1 for a in agents if a["silent"])
    return {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "headline": {
            "stale_claims": len(stale),
            "possible_unfinished_prod_state": flagged,
            "needs_josh_over_7d": len(nj["over_7d"]),
            "silent_agents": silent_n,
        },
        "stale_claims": stale,
        "live_verify": verify,
        "needs_josh": nj,
        "silent_agents": agents,
        "notes": {
            "live_verify_cap": LIVE_VERIFY_CAP,
            "wt_timeout_s": WT_TIMEOUT_S,
            "gated_heuristic": "claim text mentions " + "/".join(GATED_KEYWORDS),
        },
    }


def write_outputs(data):
    os.makedirs(REPORTS, exist_ok=True)
    day = data["generated"][:10]
    json_path = os.path.join(REPORTS, "claims-sweep-latest.json")
    tmp = json_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, json_path)
    md = render_md(data)
    md_path = os.path.join(REPORTS, "claims-sweep-%s.md" % day)
    tmp2 = md_path + ".tmp"
    with open(tmp2, "w") as f:
        f.write(md)
    os.replace(tmp2, md_path)
    return json_path, md_path


def render_md(data):
    h = data["headline"]
    L = []
    L.append("# Claims / Queue / Liveness sweep — %s" % data["generated"][:10])
    L.append("")
    L.append("Generated %s by claims-sweep.py (P4 REAPER). Read-only sweep; live checks "
             "are read-only `wt recipes get`." % data["generated"])
    L.append("")
    L.append("## Headline")
    L.append("")
    L.append("- Stale in-flight claims (>72h): **%d**" % h["stale_claims"])
    L.append("- Flagged POSSIBLE UNFINISHED PROD STATE: **%d**" % h["possible_unfinished_prod_state"])
    L.append("- needs-josh rows >7d: **%d**" % h["needs_josh_over_7d"])
    L.append("- Silent agents: **%d**" % h["silent_agents"])
    L.append("")
    L.append("## 1. Stale in-flight claims (>72h)")
    L.append("")
    if not data["stale_claims"]:
        L.append("None. (Oldest current in-flight claim is under 72h.)")
    else:
        L.append("| age | workstream | jira | what (truncated) | recipe IDs | gated | flag |")
        L.append("|---|---|---|---|---|---|---|")
        for s in data["stale_claims"]:
            ids = ", ".join(ri["id"] for ri in s["recipe_ids"]) or "-"
            flag = "POSSIBLE UNFINISHED PROD STATE" if s["flag_prod_state"] else ""
            L.append("| %sh | %s | %s | %s | %s | %s | %s |" % (
                s["age_hours"], s["workstream"], s["jira"] or "-",
                s["what"][:120].replace("|", "/"), ids,
                "yes" if s["gated"] else "no", flag))
    L.append("")
    if data["stale_claims"]:
        L.append("### Live verify (read-only wt recipes get)")
        L.append("")
        L.append("| recipe ID | verdict | running | name | detail |")
        L.append("|---|---|---|---|---|")
        for v in data["live_verify"]:
            L.append("| %s | %s | %s | %s | %s |" % (
                v["recipe_id"], v["verdict"],
                "-" if v["running"] is None else str(v["running"]),
                v["name"][:40], v["detail"][:80]))
        L.append("")
    L.append("## 2. Needs-josh aging")
    L.append("")
    nj = data["needs_josh"]
    L.append("- <72h: %d | 3-7d: %d | >7d: %d" % (len(nj["under_72h"]), len(nj["d3_7"]), len(nj["over_7d"])))
    L.append("")
    if nj["d3_7"] or nj["over_7d"]:
        L.append("| age | workstream | jira | needs |")
        L.append("|---|---|---|---|")
        for i in nj["over_7d"] + nj["d3_7"]:
            L.append("| %sd | %s | %s | %s |" % (i["age_days"], i["workstream"],
                                                 i["jira"] or "-", i["needs"][:100].replace("|", "/")))
        L.append("")
    else:
        L.append("No needs-josh rows older than 72h. Escalation threshold: 72h.")
        L.append("")
    L.append("## 3. Silent agents (dreams/bus)")
    L.append("")
    L.append("| agent | rows ever | last post | age | silent | note |")
    L.append("|---|---|---|---|---|---|")
    for a in data["silent_agents"]:
        L.append("| %s | %s | %s | %s | %s | %s |" % (
            a["agent"], a["rows"] if a["rows"] is not None else "?",
            a["last_ts"] or "-", "-" if a["age_days"] is None else "%sd" % a["age_days"],
            "YES" if a["silent"] else "", a["note"]))
    L.append("")
    L.append("Silence threshold: >%d days, or 0 rows ever. One-row outboxes are listed "
             "as possible one-shot archives — verify before reviving or removing." % SILENT_DAYS)
    L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="claims/queue/liveness sweep (P4 REAPER)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--report", action="store_true", help="human report to stdout")
    g.add_argument("--json", action="store_true", help="machine JSON to stdout")
    args = ap.parse_args()

    data = run_sweep()
    write_outputs(data)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(render_md(data))
        print("Wrote: %s" % ", ".join([
            os.path.join(REPORTS, "claims-sweep-%s.md" % data["generated"][:10]),
            os.path.join(REPORTS, "claims-sweep-latest.json")]))


if __name__ == "__main__":
    main()
