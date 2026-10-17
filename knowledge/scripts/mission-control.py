#!/usr/bin/env python3
"""mission-control.py — the in-flight work registry and its projections.

Josh's 2026-10-11 problem: multiple sessions run parallel work, agents report
in jargon, and nothing joins in-flight state across sessions/projects. This is
the join. Event-sourced per the store-discipline law: sessions APPEND events
to mission-control/events.jsonl (validated); registry.json and board.html are
DERIVED projections only this script writes.

Subcommands:
  fold       rebuild registry.json from the events log (last event per
             workstream wins; done rows older than 14d drop off the board)
  board      render mission-control/board.html (auto-refresh, groups by state)
  needs      print workstreams in state needs-josh (for briefs and /today)
  add        append one event (used by the closeout ritual and seeding):
             --event claim|closeout|state|note --workstream SLUG --project P
             --jira KEY --jira-title T --what ... --why ... --end ...
             --needs ... --state in-flight|needs-josh|blocked|done --by WHO
             [--force to record despite a near-alias conflict]
  reconcile  one-time slug-duplicate pass (dry-run by default, --apply to
             execute): groups registry rows that share a Jira key or are
             slug anagrams, keeps the fresher row, supersedes the loser
             with a pointer, posts every merge to the gossip bus

Slug canonicalization (dreamer proposal 2026-10-12): workstreams fold under
a CANONICAL slug key (trim + casefold + underscores/whitespace to dashes) so
"estate_monitor" / "Estate Monitor" / "estate-monitor" aggregate into one
row instead of phantom duplicates. `add` warns on a near-alias (canonical
match under a different spelling, or a Jira key already on another row) and
requires --force; exact same-slug updates are unaffected.
Zero-LLM. Plain-English fields are REQUIRED — the whole point.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

HOME = os.path.expanduser("~")
MC = os.path.join(HOME, ".claude", "knowledge", "mission-control")
EVENTS = os.path.join(MC, "events.jsonl")
REGISTRY = os.path.join(MC, "registry.json")
BOARD = os.path.join(MC, "board.html")
sys.path.insert(0, os.path.join(HOME, ".claude", "knowledge", "scripts"))
from atomic_io import atomic_append, atomic_append_validated, atomic_write  # noqa: E402
from bus_post import post as bus_post  # noqa: E402


def canonical_slug(s):
    """Canonical workstream key: trim + casefold + underscores/whitespace
    runs to single dashes. The only aggregation rule — no fuzzy matching
    here, so distinct workstreams can never silently collide."""
    s = re.sub(r"\s+", "-", (s or "").strip().casefold())
    s = s.replace("_", "-")
    return re.sub(r"-{2,}", "-", s)


def jira_tokens(s):
    """Set of uppercase Jira keys from a comma-separated jira field."""
    return {t.strip().upper() for t in (s or "").split(",") if t.strip()}


def find_conflicts(rows, workstream, jira):
    """Rows that conflict with a would-be `add`: a canonical alias under a
    different spelling, or a Jira key already on a DIFFERENT workstream.
    Same-slug updates (claim -> closeout) are never a conflict."""
    canon = canonical_slug(workstream)
    toks = jira_tokens(jira)
    seen, out = set(), []
    for r in rows:
        rw = r.get("workstream") or ""
        if not rw or rw in seen:
            continue
        if canonical_slug(rw) == canon:
            if rw != workstream:
                seen.add(rw)
                out.append(("canonical-alias", r))
            continue  # exact same slug: a normal state update
        if toks and (toks & jira_tokens(r.get("jira"))):
            seen.add(rw)
            out.append(("shared-jira", r))
    return out

SCHEMA = {
    "required": ["ts", "event", "workstream", "state", "by"],
    "enums": {"event": {"claim", "closeout", "state", "note"},
              "state": {"in-flight", "needs-josh", "blocked", "done"}},
    "timestamps": ["ts"],
}
STATES = ["needs-josh", "blocked", "in-flight", "done"]
STALE_DONE_DAYS = 14
STALE_NONDONE_HOURS = 24


def read_events():
    if not os.path.exists(EVENTS):
        return
    for line in open(EVENTS, errors="replace"):
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def fold():
    reg = {}
    for e in read_events():
        w = e.get("workstream")
        if not w:
            continue
        # canonical-slug fold (proposal 2026-10-12): spelling variants
        # aggregate into one row; the displayed workstream is the LATEST
        # event's raw slug, so existing callers keep their spelling
        reg[canonical_slug(w)] = e  # last event per workstream wins
    # drop done rows older than the window
    now = dt.datetime.now(dt.timezone.utc)
    fresh = {}
    for w, e in reg.items():
        age_hours = None
        try:
            ts = dt.datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))
            age_hours = (now - ts).total_seconds() / 3600.0
        except (ValueError, KeyError):
            pass
        if e.get("state") == "done":
            try:
                if (now - ts).days > STALE_DONE_DAYS:
                    continue
            except (ValueError, KeyError, NameError):
                pass
        else:
            # staleness pass for NON-done workstreams (cortex finding 2026-10-13:
            # fold previously computed no staleness here, hiding stale in-flight/
            # blocked/needs-josh rows from registry.json and board.html)
            e = dict(e)
            if age_hours is not None:
                e["age_hours"] = round(age_hours, 1)
                e["stale"] = age_hours > STALE_NONDONE_HOURS
        fresh[w] = e
    rows = sorted(fresh.values(),
                  key=lambda e: (STATES.index(e.get("state", "in-flight")),
                                 e.get("ts", "")))
    atomic_write(REGISTRY, json.dumps({"folded_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                       "workstreams": rows}, indent=1) + "\n")
    return rows


def esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def board(rows):
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    parts = ["""<!doctype html><html><head><meta charset="utf-8">
<title>Mission Control</title><meta http-equiv="refresh" content="300">
<style>
body{font-family:-apple-system,Helvetica,sans-serif;margin:24px;background:#0f172a;color:#e2e8f0}
h1{font-size:22px} .ts{color:#64748b;font-size:12px;margin-bottom:16px}
.card{background:#1e293b;border-radius:8px;padding:12px 16px;margin:10px 0;border-left:4px solid #475569}
.needs-josh{border-left-color:#ef4444}.blocked{border-left-color:#f59e0b}
.in-flight{border-left-color:#22c55e}.done{border-left-color:#334155;opacity:.6}
.jira{color:#38bdf8;font-weight:600} .meta{color:#94a3b8;font-size:12px}
.what{margin:4px 0}.why{color:#94a3b8;font-size:13px}
.needs{color:#fca5a5;font-size:13px;margin-top:6px}
h2{font-size:14px;color:#94a3b8;text-transform:uppercase;letter-spacing:.08em;margin-top:28px}
</style></head><body>
<h1>Mission Control — in-flight work</h1><div class="ts">folded %s &middot; auto-refresh 5m</div>""" % now]
    for state in STATES:
        group = [e for e in rows if e.get("state") == state]
        if not group:
            continue
        parts.append(f"<h2>{state} ({len(group)})</h2>")
        for e in group:
            jira = f'<span class="jira">{esc(e.get("jira"))}</span> — {esc(e.get("jira_title"))}<br>' if e.get("jira") else ""
            needs = f'<div class="needs">&#9888; needs Josh: {esc(e.get("needs"))}</div>' if e.get("needs") else ""
            stale = (f'<div class="needs">&#9203; STALE: no update for '
                     f'{e.get("age_hours")}h</div>') if e.get("stale") else ""
            parts.append(f"""<div class="card {state}">
{jira}<div class="what">{esc(e.get("what"))}</div>
<div class="why">why: {esc(e.get("why"))} &rarr; end: {esc(e.get("end"))}</div>
{needs}{stale}<div class="meta">{esc(e.get("workstream"))} &middot; {esc(e.get("project", ""))} &middot; by {esc(e.get("by"))} &middot; {esc(e.get("ts"))}</div>
</div>""")
    parts.append("</body></html>")
    atomic_write(BOARD, "\n".join(parts))


def needs(rows):
    for e in rows:
        if e.get("state") == "needs-josh":
            j = f" [{e.get('jira')} {e.get('jira_title')}]" if e.get("jira") else ""
            print(f"- {e.get('workstream')}{j}: {e.get('what')} — NEEDS: {e.get('needs')}")


def _parse_ts(ts):
    try:
        return dt.datetime.fromisoformat((ts or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def reconcile(apply):
    """One-time duplicate pass (proposal 2026-10-12, item 3). Dry-run by
    default; --apply executes. Merge groups = non-done rows sharing a Jira
    key, or rows whose slugs are anagrams of each other (stale-jira-review
    vs jira-stale-review). A group merges only when its rows have
    CONTRADICTORY states, or all share a state and were stamped within 60s
    (the duplicate-stamp signature). Winner = freshest row; losers get a
    supersede event (done + pointer) and every merge posts to the bus."""
    rows = fold()
    groups = {}
    by_jira, by_tokens = {}, {}
    for r in rows:
        if r.get("state") == "done" or not r.get("workstream"):
            continue
        for t in jira_tokens(r.get("jira")):
            by_jira.setdefault(t, []).append(r)
        toks = tuple(sorted(t for t in canonical_slug(r["workstream"]).split("-") if t))
        if toks:
            by_tokens.setdefault(toks, []).append(r)
    for reason, table in (("shared-jira", by_jira), ("slug-anagram", by_tokens)):
        for key, rs in table.items():
            slugs = {r["workstream"] for r in rs}
            if len(slugs) > 1:
                groups[(reason, key)] = (reason, rs)

    merges = []
    for (reason, key), (reason, rs) in sorted(groups.items()):
        states = {r.get("state") for r in rs}
        times = sorted(t for t in (_parse_ts(r.get("ts")) for r in rs) if t)
        close = bool(times) and (times[-1] - times[0]) <= dt.timedelta(seconds=60)
        if len(states) < 2 and not close:
            print(f"  left alone [{reason} {key}]: states={sorted(states)} not contradictory, not stamp-duplicates")
            continue
        winner = max(rs, key=lambda r: r.get("ts", ""))
        losers = [r for r in rs if r["workstream"] != winner["workstream"]]
        merges.append((reason, key, winner, losers))

    if not merges:
        print("reconcile: no duplicate rows to merge")
        return
    for reason, key, winner, losers in merges:
        print(f"MERGE [{reason} {key}]")
        for r in [winner] + losers:
            print(f"   {'KEEP ' if r is winner else 'LOSE '} {r['workstream']} | {r.get('state')} | {r.get('jira')} | {r.get('ts')}")
    if not apply:
        print(f"reconcile: {len(merges)} merge group(s) PLANNED (dry-run; re-run with --apply to execute)")
        return

    # backup both the registry and the event log before any write
    stamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    for path in (REGISTRY, EVENTS):
        if os.path.exists(path):
            backup = f"{path}.bak-reconcile-{stamp}"
            with open(path, "rb") as src, open(backup, "wb") as dst:
                dst.write(src.read())
            print(f"backup: {backup}")

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    merged = 0
    for reason, key, winner, losers in merges:
        for r in losers:
            note = (f"duplicate registry row merged into '{winner['workstream']}' by slug-canonicalization "
                    f"reconcile ({reason}: {key}); fresher state '{winner.get('state')}' at {winner.get('ts')} wins")
            row = {"ts": now, "event": "state", "workstream": r["workstream"],
                   "project": r.get("project", ""), "jira": r.get("jira", ""),
                   "jira_title": r.get("jira_title", ""),
                   "what": note, "why": note, "end": "one row per workstream on the board",
                   "needs": "", "state": "done", "by": "mission-control reconcile"}
            atomic_append_validated(EVENTS, row, SCHEMA)
            bus_post("mission-control", "finding", "mc-slug-merge",
                     {"claim": note, "confidence": "high"},
                     thread="mission-control-slug-canonicalization")
            merged += 1
            print(f"superseded {r['workstream']} -> pointer to {winner['workstream']}")
    rows = fold()
    board(rows)
    print(f"reconcile: {merged} duplicate row(s) superseded; registry refolded to {len(rows)} rows")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fold", "board", "needs", "add", "reconcile"])
    ap.add_argument("--event", dest="ev")
    ap.add_argument("--workstream")
    ap.add_argument("--project", default="")
    ap.add_argument("--jira", default="")
    ap.add_argument("--jira-title", default="")
    ap.add_argument("--what", default="")
    ap.add_argument("--why", default="")
    ap.add_argument("--end", default="")
    ap.add_argument("--needs", default="")
    ap.add_argument("--state", default="in-flight")
    ap.add_argument("--by", default="josh (session)")
    ap.add_argument("--session-id", default="",
                    help="session id of the recording session — turns closeout "
                         "attribution from time-proximity guessing into a fact "
                         "(2026-10-16 deadman FP fix)")
    ap.add_argument("--force", action="store_true",
                    help="add: record despite a near-alias conflict")
    ap.add_argument("--apply", action="store_true",
                    help="reconcile: execute the planned merges")
    a = ap.parse_args()
    if a.cmd == "add":
        if a.what and len(a.what) < 20:
            sys.exit("refused: 'what' must be a plain-English sentence, not a fragment")
        rows = fold()
        if a.workstream:
            conflicts = find_conflicts(rows, a.workstream, a.jira)
            if conflicts and not a.force:
                print(f"REFUSED: '{a.workstream}' conflicts with existing row(s) "
                      f"(slug-canonicalization guard, Josh 2026-10-16):")
                for kind, r in conflicts[:10]:
                    print(f"  [{kind}] {r.get('workstream')} | {r.get('state')} | "
                          f"jira={r.get('jira')} | {r.get('ts')}")
                print("re-run with --force if this is legitimate distinct work (e.g. a phase split)")
                sys.exit(2)
        row = {"ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "event": a.ev or "closeout", "workstream": a.workstream,
               "project": a.project, "jira": a.jira, "jira_title": a.jira_title,
               "what": a.what, "why": a.why, "end": a.end, "needs": a.needs,
               "state": a.state, "by": a.by}
        if a.session_id:
            row["session_id"] = a.session_id
        atomic_append_validated(EVENTS, row, SCHEMA)
        rows = fold()
        board(rows)
        print(f"recorded {row['event']} for {row['workstream']} -> {row['state']}; board refolded")
        if row['event'] == 'claim' and row.get('state') == 'in-flight':
            print("REMINDER (Josh 2026-10-12): if this claim involves a Workato build, open the living export manifest NOW — `wt manifests create` + mirror to <repo>/manifests/<BSYS-id>.manifest.json — BEFORE the first builder edit. Assets enter AS touched, same turn. (BSYS-29560/29564 drift: manifests opened after the pushes.)")
        return
    if a.cmd == "reconcile":
        reconcile(a.apply)
        return
    rows = fold()
    if a.cmd == "board":
        board(rows)
        print(f"board: {len(rows)} workstreams -> {BOARD}")
    elif a.cmd == "needs":
        needs(rows)
    else:
        print(f"folded {len(rows)} workstreams -> {REGISTRY}")


if __name__ == "__main__":
    main()
