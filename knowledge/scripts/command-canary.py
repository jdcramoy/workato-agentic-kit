#!/usr/bin/env python3
"""command-canary.py — daily end-to-end canary for the Slack command loop.

The orchestration loop is: room post -> watcher poll (60s) -> queue row ->
execute -> BOT ACK in the room. Every part of that was proven by hand on
2026-10-08; nothing re-proved it daily — until this. The canary injects a
synthetic selfcheck row through the SAME data-tables API, waits for the
watcher to process it, then asserts the bot ack carrying the exact result
timestamp landed in the room. Pure REST — no claude -p, deterministic.

Writes garden-reports/command-canary-status.json (read by the replay gym's
canary-freshness invariant and the morning brief) + a heartbeat row.
Pass SLA: row processed + ack visible within 5 minutes.

    python3 ~/.claude/knowledge/scripts/command-canary.py
"""
import datetime as dt
import json
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path
from atomic_io import atomic_append

K = Path.home() / ".claude/knowledge"
WATCHER = K / "scripts" / "agent-command-watcher-module.py"
STATE = K / "garden-reports/command-canary-status.json"
HEARTBEAT = K / "garden-reports/heartbeat.jsonl"
ROOM = "C0C7JHJKHRU"
SLA_SECONDS = 300


def watcher_api(method, path, data):
    import importlib.util
    spec = importlib.util.spec_from_file_location("w", str(Path.home() / ".local/bin/agent-command-watcher.py"))
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    return w.api(method, path, data)


def bot_token():
    r = subprocess.run(["security", "find-generic-password", "-s",
                        "slack-harness-command-bot", "-w"],
                       capture_output=True, text=True)
    return r.stdout.strip()


def slack_get(method, params):
    url = f"https://slack.com/api/{method}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {bot_token()}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def heartbeat(passed, detail):
    row = {"ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "job": "command-canary", "pass": passed, "detail": detail[:200]}
    atomic_append(HEARTBEAT, row)


def main():
    import argparse
    # --help/-h gate (2026-10-16): this script had NO argparse, so any
    # invocation — including a naive --help during an audit — fired a REAL
    # canary: a watcher queue row + Slack polling + heartbeat/status writes.
    # argparse prints usage and exits before the body runs.
    ap = argparse.ArgumentParser(
        description="daily end-to-end canary for the Slack command loop "
                    "(no arguments; run bare to execute the canary)")
    ap.parse_args()
    started = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    t0 = time.time()

    # 1. inject the synthetic selfcheck through the canonical queue API
    status, resp = watcher_api("POST", "/records", {"document": {
        "directive": "selfcheck", "author_slack_id": "U0A3R9AVAMA",
        "status": "pending", "source_ref": f"canary:{started}"}})
    # create returns HTTP 201 + {'data': {'created_at', 'document'}} — NO row id
    # (learned live 2026-10-09; false-FAILed the first canary run). Get the id
    # by querying the row back on its unique source_ref.
    if not (isinstance(resp, dict) and resp.get("data")):
        detail = f"row create failed: {str(resp)[:150]}"
        STATE.write_text(json.dumps({"checked": started, "checked_epoch": t0,
                                     "pass": False, "detail": detail}))
        heartbeat(False, detail)
        print("canary FAIL:", detail)
        return
    qstatus, qresp = watcher_api("POST", "/query",
                                 {"where": {"source_ref": {"$eq": f"canary:{started}"}}})
    rows = qresp.get("data", []) if isinstance(qresp, dict) else []
    if not rows:
        detail = "row created but not queryable back on source_ref"
        STATE.write_text(json.dumps({"checked": started, "checked_epoch": t0,
                                     "pass": False, "detail": detail}))
        heartbeat(False, detail)
        print("canary FAIL:", detail)
        return
    v = rows[0]
    rid = (v[0] if isinstance(v[0], list) else [v[0]])[0]

    # 2. wait for the watcher to process it (SLA)
    result_note = None
    while time.time() - t0 < SLA_SECONDS:
        time.sleep(15)
        qstatus, qresp = watcher_api("POST", "/query",
                                     {"where": {"source_ref": {"$eq": f"canary:{started}"}}})
        for v in qresp.get("data", []):
            vals = v[1] if isinstance(v[1], list) else v[1:]
            row_status = str(vals[3]) if len(vals) > 3 else "?"
            if row_status == "done":
                result_note = str(vals[4]) if len(vals) > 4 else ""
                break
            if row_status == "rejected":
                break
        if result_note:
            break

    if not result_note:
        detail = f"row {rid} not done within {SLA_SECONDS}s SLA — watcher not polling?"
        STATE.write_text(json.dumps({"checked": started, "checked_epoch": t0,
                                     "pass": False, "detail": detail}))
        heartbeat(False, detail)
        print("canary FAIL:", detail)
        return

    # 3. assert the bot ack carrying the exact result timestamp landed
    ack_ts = result_note.replace("selfcheck ok at ", "").strip()
    ack_seen = False
    for _ in range(6):  # ack may lag the row by a few seconds
        hist = slack_get("conversations.history", {"channel": ROOM, "limit": 10})
        ack_seen = any(ack_ts[:19] in (m.get("text", ""))
                       and m.get("user") == "U0C76D82LAK"
                       for m in hist.get("messages", []))
        if ack_seen:
            break
        time.sleep(10)

    latency = time.time() - t0
    detail = (f"row {rid} done, bot ack verified in-room ({latency:.0f}s)"
              if ack_seen else
              f"row done but BOT ACK MISSING for ts {ack_ts} — ack leg broken")
    STATE.write_text(json.dumps({"checked": started, "checked_epoch": time.time(),
                                 "pass": ack_seen, "detail": detail,
                                 "latency_s": round(latency)}))
    heartbeat(ack_seen, detail)
    print(("canary PASS:" if ack_seen else "canary FAIL:"), detail)


if __name__ == "__main__":
    main()
