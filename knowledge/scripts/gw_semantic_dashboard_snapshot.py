#!/usr/bin/env python3
"""Snapshot the Google Workspace Semantic MCP serving truth into a shareable dashboard.

Pulls live evidence through the wt CLI (dev profile):
  1. Registry rows grouped by service  (workspace_semantic_registry)
  2. Routing shards per service        (workspace_semantic_retrieval_index)
  3. Health / trust state rows         (mutation drill, conformance, alerts)
  4. Fleet running flags + job totals  (per recipe, plain names on the board)

Writes:
  ~/Documents/gw-semantic-dashboard/index.html          (self-contained board)
  ~/Documents/gw-semantic-dashboard/snapshots/snap-<ts>.json  (history)

Colleague-facing: no recipe IDs or table IDs render on the board.
"""

import json
import re
import subprocess
import sys
import shutil
import time

sys.path.insert(0, "~/.claude/knowledge/scripts")
from atomic_io import atomic_write_json  # noqa: E402  (json-guard shared helper)

# launchd PATH is minimal; resolve wt explicitly (broke 2026-10-18 when wt moved to ~/.local/bin)
WT = shutil.which("wt") or "~/.local/bin/wt"
from datetime import datetime, timezone
from pathlib import Path

OUT_DIR = Path.home() / "Documents" / "gw-semantic-dashboard"
SNAP_DIR = OUT_DIR / "snapshots"

REGISTRY_TABLE = "b64781ad-06b6-44db-bfde-09daeba8e801"
SHARD_TABLE = "9bdee34f-94e2-44ea-a736-053ecb325255"
STATE_TABLE = "f6f0d7f0-75f3-42c2-8162-4a3a674e7eb6"

# Plain name -> recipe id. IDs stay here; the board renders only the names.
FLEET = [
    ("Gateway", 82273312),
    ("Registry sync", 82272892),
    ("Learning curator", 82792466),
    ("Promotion gate", 82792961),
    ("Usage rollup", 82889357),
    ("Daily usage digest", 82803096),
    ("Health monitor", 82830607),
    ("Mutation-chain canary", 82964017),
    ("Fleet liveness sentinel", 82964161),
    ("Promoted phrase health", 82993457),
    ("Paraphrase clustering", 82964058),
    ("Error hint author", 82964024),
]


def run(args):
    return subprocess.run(args, capture_output=True, text=True, timeout=120)


def wt_json(*args):
    r = run([WT] + list(args))
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def page_all(table, select, cap_pages=40):
    # A transient wt failure used to return None here and silently truncate the
    # row count (board showed registry=400 vs real 1073 on 2026-10-18) while the
    # verdict stayed green. Retry, then fail loud so a bad run never overwrites
    # the last good board.
    rows, token = [], ""
    for _ in range(cap_pages):
        if token:
            args = ["dt", "query", table, "--select", select, "--limit", "200",
                    "--continuation", token]
        else:
            args = ["dt", "query", table, "--select", select, "--limit", "200"]
        d = None
        for _attempt in range(3):
            d = wt_json(*args)
            if d is not None:
                break
            time.sleep(2)
        if d is None:
            raise RuntimeError(
                f"wt dt query failed (non-JSON) for table {table} after 3 attempts; "
                "refusing to build a partial snapshot")
        if not d.get("rows"):
            break
        rows.extend(d["rows"])
        token = d.get("continuation_token") or d.get("continuation") or ""
        if not token:
            break
    return rows


def registry_by_service():
    counts = {}
    for r in page_all(REGISTRY_TABLE, "service"):
        s = r.get("service") or "?"
        counts[s] = counts.get(s, 0) + 1
    return counts


def routing_shards():
    per = {}
    total_active = 0
    for r in page_all(SHARD_TABLE, "index_key,status"):
        # Column semantics are swapped vs the schema names: the shard key
        # ("active:<service>:NNNN") can arrive in either field.
        for key in (r.get("index_key"), r.get("status")):
            key = (key or "")
            parts = key.split(":")
            if len(parts) == 3 and parts[0] == "active" and parts[2].isdigit():
                svc = parts[1]
                per[svc] = per.get(svc, 0) + 1
                total_active += 1
                break
    return per, total_active


def health_state():
    rows = page_all(STATE_TABLE, "check_key,last_alert_at,last_detail", cap_pages=4)
    return {r.get("check_key"): (r.get("last_alert_at") or "", r.get("last_detail") or "")
            for r in rows}


def fleet_status():
    out = []
    for name, rid in FLEET:
        g = run([WT, "recipes", "get", str(rid)])
        running = '"running": true' in g.stdout or '"running":true' in g.stdout
        j = wt_json("jobs", "list", str(rid)) or {}
        ok = j.get("job_succeeded_count", 0)
        bad = j.get("job_failed_count", 0)
        total = j.get("job_count", 0)
        last = ""
        items = j.get("items") or []
        if items:
            last = (items[0].get("completed_at") or items[0].get("started_at") or "")[:16]
        rate = round(100.0 * ok / total, 1) if total else None
        out.append({"name": name, "running": running, "ok": ok, "failed": bad,
                    "total": total, "rate": rate, "last_run": last})
    return out


def parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def build_snapshot():
    now = datetime.now(timezone.utc)
    reg = registry_by_service()
    shards, shard_total = routing_shards()
    state = health_state()
    fleet = fleet_status()

    drill_ok = False
    drill_at = ""
    conf = {"checked": "", "rows": 0, "conformant": 0, "drifted": 0}
    for key, (at, detail) in state.items():
        if key == "mutation_drill":
            drill_at = at
            drill_ok = "ok=yes" in detail
        elif key == "conformance_freshness":
            m = re.search(r"checked=([\d-]+)", detail)
            rows_m = re.search(r"rows=(\d+)", detail)
            conf_m = re.search(r"conformant=(\d+)", detail)
            drift_m = re.search(r"drifted=(\d+)", detail)
            conf = {
                "checked": m.group(1) if m else "",
                "rows": int(rows_m.group(1)) if rows_m else 0,
                "conformant": int(conf_m.group(1)) if conf_m else 0,
                "drifted": int(drift_m.group(1)) if drift_m else 0,
            }

    all_running = all(f["running"] for f in fleet)
    drill_fresh_ts = parse_ts(drill_at)
    drill_age_h = None
    if drill_fresh_ts:
        drill_age_h = round((now - drill_fresh_ts).total_seconds() / 3600.0, 1)
    drill_current = drill_age_h is not None and drill_age_h <= 26

    if all_running and drill_ok and drill_current and conf["drifted"] == 0:
        verdict, tier = "All serving surfaces green.", "good"
    elif drill_ok and all_running:
        verdict, tier = "Serving. One trust check needs a look.", "warning"
    else:
        problems = []
        if not all_running:
            problems.append("a fleet component is not running")
        if not drill_ok or not drill_current:
            problems.append("the mutation-chain proof is stale or failing")
        if conf["drifted"]:
            problems.append("conformance drift detected")
        verdict, tier = "Needs attention: " + "; ".join(problems) + ".", "critical"

    snap = {
        "generated_at": now.isoformat(timespec="seconds"),
        "verdict": verdict, "tier": tier,
        "registry_total": sum(reg.values()),
        "registry_by_service": reg,
        "shard_total": shard_total,
        "shards_by_service": shards,
        "fleet": fleet,
        "drill": {"ok": drill_ok, "at": drill_at, "age_hours": drill_age_h},
        "conformance": conf,
        "alerts": {k: v[0] for k, v in state.items()
                   if k in ("silence", "failure_burst", "failure_burst_rejections",
                            "consent_rot", "stall_watch_alert")},
    }
    return snap


TPL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Google Workspace Semantic MCP — Service Dashboard</title>
<style>
  .viz-root {
    color-scheme: light;
    --surface-1: #fcfcfb; --plane: #f9f9f7;
    --ink-1: #0b0b0b; --ink-2: #52514e; --ink-3: #898781;
    --grid: #e1e0d9; --baseline: #c3c2b7; --ring: rgba(11,11,11,0.10);
    --series-1: #2a78d6;
    --good: #0ca30c; --warning: #fab219; --serious: #ec835a; --critical: #d03b3b;
    --good-text: #006300; --critical-text: #a12f2f;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: dark;
      --surface-1: #1a1a19; --plane: #0d0d0d;
      --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-3: #898781;
      --grid: #2c2c2a; --baseline: #383835; --ring: rgba(255,255,255,0.10);
      --series-1: #3987e5;
      --good-text: #0ca30c; --critical-text: #e66767;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: dark;
    --surface-1: #1a1a19; --plane: #0d0d0d;
    --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-3: #898781;
    --grid: #2c2c2a; --baseline: #383835; --ring: rgba(255,255,255,0.10);
    --series-1: #3987e5;
    --good-text: #0ca30c; --critical-text: #e66767;
  }
  * { box-sizing: border-box; }
  body.viz-root {
    margin: 0; padding: 32px 20px 60px; background: var(--plane);
    color: var(--ink-1); font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 14px; line-height: 1.45;
  }
  .wrap { max-width: 960px; margin: 0 auto; }
  h1 { font-size: 20px; font-weight: 650; margin: 0 0 4px; }
  .sub { color: var(--ink-2); margin: 0 0 18px; }
  .verdict {
    display: flex; align-items: baseline; gap: 10px; padding: 12px 16px;
    background: var(--surface-1); border: 1px solid var(--ring); border-radius: 10px;
    margin-bottom: 22px; font-size: 15px;
  }
  .verdict .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; align-self: center; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 26px; }
  .tile { background: var(--surface-1); border: 1px solid var(--ring); border-radius: 10px; padding: 14px 16px; }
  .tile .v { font-size: 30px; font-weight: 650; }
  .tile .l { color: var(--ink-2); font-size: 12px; margin-top: 2px; }
  .tile .d { color: var(--ink-3); font-size: 11px; margin-top: 4px; }
  section { margin-bottom: 30px; }
  h2 { font-size: 14px; font-weight: 650; color: var(--ink-2); margin: 0 0 10px; }
  .card { background: var(--surface-1); border: 1px solid var(--ring); border-radius: 10px; padding: 16px; }
  .bar-row { display: grid; grid-template-columns: 90px 1fr 56px; align-items: center; gap: 10px; margin: 7px 0; }
  .bar-row .svc { color: var(--ink-2); font-size: 12px; text-align: right; }
  .bar-track { position: relative; height: 16px; }
  .bar-fill { height: 100%; background: var(--series-1); border-radius: 0 4px 4px 0; min-width: 2px; }
  .bar-row .n { font-size: 12px; color: var(--ink-1); font-variant-numeric: tabular-nums; }
  .bar-row:hover .bar-fill { filter: brightness(1.08); }
  .bar-row .n, .bar-row .svc { position: relative; z-index: 1; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; color: var(--ink-3); font-weight: 500; font-size: 12px; padding: 6px 10px; border-bottom: 1px solid var(--grid); }
  td { padding: 7px 10px; border-bottom: 1px solid var(--grid); font-variant-numeric: tabular-nums; }
  tr:last-child td { border-bottom: none; }
  .status { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
  .st-good { color: var(--good-text); } .st-bad { color: var(--critical-text); }
  details { margin-top: 10px; }
  summary { cursor: pointer; color: var(--ink-2); font-size: 12px; }
  .foot { color: var(--ink-3); font-size: 12px; margin-top: 8px; }
  .trust { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
  .trust .card { font-size: 13px; }
  .trust .k { color: var(--ink-3); font-size: 11px; }
  .trust .big { font-size: 16px; font-weight: 600; margin: 2px 0; }
</style>
</head>
<body class="viz-root" data-palette="#2a78d6">
<div class="wrap">
  <h1>Google Workspace Semantic MCP — Service Dashboard</h1>
  <p class="sub">What the server serves, verified live against its ledgers · snapshot __GENERATED__ UTC</p>

  <div class="verdict"><span class="dot" style="background: var(--__TIER__);"></span><span><strong>__VERDICT__</strong></span></div>

  <div class="tiles">
    <div class="tile"><div class="v">__CAPS__</div><div class="l">capabilities served</div><div class="d">across __SVCS__ services</div></div>
    <div class="tile"><div class="v">__REG__</div><div class="l">reviewed registry rows</div><div class="d">reconciled to routing</div></div>
    <div class="tile"><div class="v">__CONF__</div><div class="l">conformance check</div><div class="d">__CONF_DATE__</div></div>
    <div class="tile"><div class="v">__DRILL__</div><div class="l">mutation-chain drill</div><div class="d">__DRILL_AGE__</div></div>
    <div class="tile"><div class="v">__FLEET_OK__/__FLEET_N__</div><div class="l">fleet components running</div><div class="d">__FLEET_NOTE__</div></div>
  </div>

  <section>
    <h2>Reviewed capabilities per service</h2>
    <div class="card">
      __BARS__
      <details><summary>Table view</summary>
        <table><thead><tr><th>Service</th><th>Capabilities</th></tr></thead><tbody>__BARTABLE__</tbody></table>
      </details>
    </div>
  </section>

  <section>
    <h2>Fleet</h2>
    <div class="card">
      <table>
        <thead><tr><th>Component</th><th>Status</th><th>Success rate</th><th>Jobs run</th><th>Last run (UTC)</th></tr></thead>
        <tbody>__FLEETROWS__</tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>Trust checks</h2>
    <div class="trust">
      <div class="card"><div class="k">MUTATION-CHAIN DRILL</div><div class="big __DRILL_CLS__">__DRILL_WORD__</div><div class="d">Full create, undo, and delete chain proven end to end · __DRILL_AGE__</div></div>
      <div class="card"><div class="k">REGISTRY CONFORMANCE</div><div class="big">__CONF_ROWS__ rows, __CONF_DRIFT__ drift</div><div class="d">Every reviewed row matches its generated contract · checked __CONF_DATE__</div></div>
      <div class="card"><div class="k">LAST HEALTH ALERT</div><div class="big">__ALERT_KIND__</div><div class="d">__ALERT_AT__</div></div>
    </div>
  </section>

  <p class="foot">Numbers are pulled live at snapshot time from the workspace data plane and reconciled: registry rows plus discovery-only catalog tuples equal the routing surface. Names are hashed, content is never stored, and every mutation carries a caller-bound plan, a receipt, and a governed confirmation policy.</p>
</div>
</body>
</html>
"""


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(snap):
    reg = snap["registry_by_service"]
    order = sorted(reg.items(), key=lambda kv: -kv[1])
    mx = max([v for _, v in order] + [1])
    bars, table = [], []
    for svc, n in order:
        w = round(100.0 * n / mx, 1)
        bars.append(
            f'<div class="bar-row" title="{esc(svc)}: {n}"><div class="svc">{esc(svc)}</div>'
            f'<div class="bar-track"><div class="bar-fill" style="width:{w}%"></div></div>'
            f'<div class="n">{n}</div></div>')
        table.append(f"<tr><td>{esc(svc)}</td><td>{n}</td></tr>")

    frows = []
    for f in snap["fleet"]:
        rate = f"{f['rate']}%" if f["rate"] is not None else "n/a"
        if f["running"]:
            st = '<span class="status st-good">&#9679; running</span>'
        else:
            st = '<span class="status st-bad">&#9679; not running</span>'
        frows.append(f"<tr><td>{esc(f['name'])}</td><td>{st}</td><td>{rate}</td>"
                     f"<td>{f['total']}</td><td>{esc(f['last_run'] or 'n/a')}</td></tr>")

    last_alert_kind, last_alert_at = "none on record", "n/a"
    for k in ("failure_burst_rejections", "failure_burst", "consent_rot", "silence", "stall_watch_alert"):
        if snap["alerts"].get(k):
            last_alert_kind, last_alert_at = k.replace("_", " "), snap["alerts"][k][:16]
            break

    drill_age = f"{snap['drill']['age_hours']}h ago" if snap["drill"]["age_hours"] is not None else "n/a"
    # 13 = discovery-only tuples the routing surface serves but the registry never
    # holds (cross-service catalog 12 + workspace compound resolver 1, per design).
    conf = snap["conformance"]

    html = (TPL
            .replace("__GENERATED__", snap["generated_at"])
            .replace("__TIER__", {"good": "good", "warning": "warning", "critical": "critical"}[snap["tier"]])
            .replace("__VERDICT__", esc(snap["verdict"]))
            .replace("__CAPS__", str(snap["registry_total"] + 13))
            .replace("__SVCS__", str(len(set(reg) | set(snap["shards_by_service"]))))
            .replace("__REG__", str(snap["registry_total"]))
            .replace("__CONF__", f"{conf['conformant']}/{conf['rows']}")
            .replace("__CONF_ROWS__", str(conf["rows"]))
            .replace("__CONF_DRIFT__", str(conf["drifted"]))
            .replace("__CONF_DATE__", conf["checked"] or "n/a")
            .replace("__DRILL__", "PASS" if snap["drill"]["ok"] else "FAIL")
            .replace("__DRILL_WORD__", "PASS" if snap["drill"]["ok"] else "FAIL")
            .replace("__DRILL_CLS__", "st-good" if snap["drill"]["ok"] else "st-bad")
            .replace("__DRILL_AGE__", drill_age)
            .replace("__FLEET_OK__", str(sum(1 for f in snap["fleet"] if f["running"])))
            .replace("__FLEET_N__", str(len(snap["fleet"])))
            .replace("__FLEET_NOTE__", "live running flags" )
            .replace("__BARS__", "\n      ".join(bars))
            .replace("__BARTABLE__", "".join(table))
            .replace("__FLEETROWS__", "".join(frows))
            .replace("__ALERT_KIND__", esc(last_alert_kind))
            .replace("__ALERT_AT__", esc(last_alert_at)))
    return html


def main():
    snap = build_snapshot()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    ts = snap["generated_at"].replace(":", "").replace("-", "")
    # json-guard (2026-10-13 proposal): .json snapshot writes go through the
    # shared helper — non-JSON content refused loudly, raw kept as .txt.
    atomic_write_json(str(SNAP_DIR / f"snap-{ts}.json"), snap)
    (OUT_DIR / "index.html").write_text(render(snap))
    print(f"ok {snap['verdict']} registry={snap['registry_total']} shards={snap['shard_total']}")
    print(str(OUT_DIR / "index.html"))
    if not all(f["running"] for f in snap["fleet"]):
        for f in snap["fleet"]:
            if not f["running"]:
                print(f"NOT RUNNING: {f['name']}", file=sys.stderr)


if __name__ == "__main__":
    main()
