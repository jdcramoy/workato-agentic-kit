#!/usr/bin/env python3
"""Ops-visibility local action server (stdlib-only, Python 3.9+).

Serves the ops dashboard and the three contract actions on 127.0.0.1:8771 ONLY.
Contract: ~/.claude/knowledge/ops-visibility/CONTRACT.md

Modes:
  ops-server.py --serve   run the HTTP server + in-process 15-min collection loop (default)
  ops-server.py --once    run a single collection tick and exit (no server)

POST endpoints (loopback-only, per contract):
  /api/triage   {"sig": ...} -> append finding to knowledge/triage/queue.jsonl (idempotent on open slug)
  /api/autopsy  {"sig": ...} -> append record + requested_ts to ops-visibility/autopsy-requests.jsonl
  /api/refresh  {}           -> spawn ops-collector.py collect out-of-band (503 if collector absent)
"""

import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8771
BASE = Path.home() / ".claude" / "knowledge" / "ops-visibility"
TRIAGE_QUEUE = Path.home() / ".claude" / "knowledge" / "triage" / "queue.jsonl"
COLLECTOR = Path.home() / ".claude" / "knowledge" / "scripts" / "ops-collector.py"
DASHGEN = BASE / "ops-dashboard.py"
DASH_HTML = BASE / "ops-dashboard.html"
AUTOPSY_REQ = BASE / "autopsy-requests.jsonl"
STATE = BASE / "state.json"
COLLECTOR_LOG = BASE / "collector.log"
HEARTBEAT = Path.home() / ".claude" / "knowledge" / "garden-reports" / "heartbeat.jsonl"
COLLECT_INTERVAL_S = 900          # 15 min per contract
MAX_BODY = 65536
RECORDS_GLOB = "records-*.jsonl"

STOP = threading.Event()

PLACEHOLDER_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="60">
<title>Ops visibility</title>
<style>body{font-family:-apple-system,Helvetica,sans-serif;background:#16181d;color:#e6e6e6;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
div{text-align:center}h1{font-size:20px;font-weight:600}p{color:#9aa0a6}</style></head>
<body><div><h1>Ops visibility is starting up</h1>
<p>Collection has not produced a dashboard yet.<br>
The collector is being deployed; this page refreshes every 60 seconds.</p>
</div></body></html>"""


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def append_line_locked(path, obj):
    """Append one JSON line to path under an exclusive flock."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.write(fd, (line + "\n").encode("utf-8"))
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def load_records():
    """All records across records-*.jsonl, latest occurrence wins per sig."""
    records = {}
    for f in sorted(BASE.glob(RECORDS_GLOB)):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict) and rec.get("sig"):
                        records[rec["sig"]] = rec
        except OSError:
            continue
    return records


def find_record(sig):
    return load_records().get(sig)


def last_sweep():
    try:
        state = json.loads(STATE.read_text(encoding="utf-8"))
        scans = [v.get("last_scan") for v in state.values() if isinstance(v, dict)]
        scans = [s for s in scans if s]
        return max(scans) if scans else None
    except (OSError, ValueError):
        return None


def summary():
    records = load_records()
    open_n = sent = diag = swallow = 0
    for rec in records.values():
        status = rec.get("status")
        if status == "open":
            open_n += 1
        elif status in ("sent-to-triage", "sent_to_triage"):
            sent += 1
        elif status == "diagnosed":
            diag += 1
        if rec.get("swallowed"):
            swallow += 1
    return {
        "open": open_n,
        "sent_to_triage": sent,
        "diagnosed": diag,
        "swallowed": swallow,
        "last_sweep": last_sweep(),
    }


def generate_dashboard():
    """Ensure the dashboard HTML exists; try generating if the generator exists."""
    if DASH_HTML.exists():
        return True
    if DASHGEN.exists():
        try:
            subprocess.run(
                [sys.executable, str(DASHGEN), "generate"],
                cwd=str(BASE), timeout=120,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except (OSError, subprocess.SubprocessError):
            pass
    return DASH_HTML.exists()


def collect_tick():
    """One collection tick: run ops-collector.py collect if it exists."""
    if not COLLECTOR.exists():
        return False
    try:
        with open(COLLECTOR_LOG, "a", encoding="utf-8") as lf:
            lf.write("\n[%s] collect tick\n" % now_iso())
            lf.flush()
            subprocess.run(
                [sys.executable, str(COLLECTOR), "collect"],
                cwd=str(BASE), timeout=780, stdout=lf, stderr=lf,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        try:
            with open(COLLECTOR_LOG, "a", encoding="utf-8") as lf:
                lf.write("[%s] collect tick error: %s\n" % (now_iso(), exc))
        except OSError:
            pass
        return False
    return True


def write_heartbeat():
    """Liveness row so harness-health can see the long-running server is up.
    Best-effort: a ledger failure must never take the server down."""
    try:
        append_line_locked(HEARTBEAT, {"ts": now_iso(), "job": "ops-visibility"})
    except OSError:
        pass


def collection_loop():
    """15-min sleep loop, first tick shortly after boot."""
    write_heartbeat()
    STOP.wait(15)
    while not STOP.is_set():
        collect_tick()
        write_heartbeat()
        STOP.wait(COLLECT_INTERVAL_S)


def run_triage(sig):
    rec = find_record(sig)
    if rec is None:
        return 404, {"ok": False, "error": "unknown sig"}

    slug = "ops-%s" % sig
    # Idempotent: skip if an OPEN finding with the same slug already exists.
    try:
        if TRIAGE_QUEUE.exists():
            with open(TRIAGE_QUEUE, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        existing = json.loads(line)
                    except ValueError:
                        continue
                    if existing.get("slug") == slug and existing.get("status") == "open":
                        return 200, {"ok": True, "appended": False,
                                     "reason": "open finding already in queue"}
    except OSError:
        pass

    error_text = rec.get("error") or ""
    title = "Workato %s failure: %s — %s" % (
        rec.get("env", "?"), rec.get("recipe_name", rec.get("recipe_id", "?")),
        error_text[:80])
    evidence = "job %s x%s; last %s; %s" % (
        rec.get("job_id", "?"), rec.get("count", "?"), rec.get("last_seen", "?"),
        "swallowed-error" if rec.get("swallowed") else "failed")
    finding = {
        "slug": slug,
        "kind": "build",
        "source": "ops-visibility",
        "title": title,
        "evidence": evidence,
        "work": "investigate per workato-autopsy; remediate dev-scoped",
        "points": 3,
        "status": "open",
        "ts": now_iso(),
    }
    append_line_locked(TRIAGE_QUEUE, finding)
    mark_record(sig, "sent-to-triage")
    return 200, {"ok": True, "appended": True}


def mark_record(sig, status):
    """Update a record's status in place across all records-*.jsonl files
    (contract: status is UPDATED in place), then regenerate the dashboard."""
    import json as _json
    changed = False
    for f in sorted(BASE.glob(RECORDS_GLOB)):
        lines = f.read_text(encoding="utf-8").splitlines()
        out = []
        for line in lines:
            if not line.strip():
                continue
            try:
                rec = _json.loads(line)
            except ValueError:
                out.append(line)
                continue
            if rec.get("sig") == sig and rec.get("status") != status:
                rec["status"] = status
                changed = True
            out.append(_json.dumps(rec))
        if changed:
            f.write_text("\n".join(out) + "\n", encoding="utf-8")
    if changed and DASHGEN.exists():
        subprocess.Popen(
            [sys.executable, str(DASHGEN), "generate"],
            cwd=str(BASE), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )


def run_autopsy(sig):
    rec = find_record(sig)
    if rec is None:
        return 404, {"ok": False, "error": "unknown sig"}
    req = dict(rec)
    req["requested_ts"] = now_iso()
    append_line_locked(AUTOPSY_REQ, req)
    return 200, {"ok": True, "appended": True}


def run_refresh():
    if not COLLECTOR.exists():
        return 503, {"ok": False, "error": "collector not deployed yet"}
    try:
        lf = open(COLLECTOR_LOG, "a", encoding="utf-8")
        subprocess.Popen(
            [sys.executable, str(COLLECTOR), "collect"],
            cwd=str(BASE), stdout=lf, stderr=lf,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        return 500, {"ok": False, "error": "spawn failed: %s" % exc}
    return 202, {"ok": True, "started": True}


class Handler(BaseHTTPRequestHandler):
    server_version = "ops-visibility/1.0"
    protocol_version = "HTTP/1.1"

    # One-line minimal logging; never echo request bodies (they carry error text).
    def log_message(self, fmt, *args):
        sys.stdout.write("[%s] %s %s\n" % (now_iso(),
                                           self.command, self.path.split("?")[0]))
        sys.stdout.flush()

    def _reject_remote(self):
        peer = self.client_address[0]
        if peer in ("127.0.0.1", "::1"):
            return False
        self._send_json(403, {"ok": False, "error": "loopback only"})
        return True

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, code, html):
        body = html.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self._reject_remote():
            return
        path = self.path.split("?")[0]
        if path == "/api/summary":
            self._send_json(200, summary())
            return
        if path == "/":
            if generate_dashboard():
                try:
                    self._send_html(200, DASH_HTML.read_text(encoding="utf-8"))
                except OSError:
                    self._send_html(500, PLACEHOLDER_HTML)
            else:
                self._send_html(200, PLACEHOLDER_HTML)
            return
        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self._reject_remote():
            return
        path = self.path.split("?")[0]
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(min(length, MAX_BODY)) if length > 0 else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"ok": False, "error": "invalid JSON"})
            return
        sig = payload.get("sig")
        if path == "/api/refresh":
            code, obj = run_refresh()
        elif path in ("/api/triage", "/api/autopsy"):
            if not sig or not isinstance(sig, str):
                self._send_json(400, {"ok": False, "error": "sig required"})
                return
            if path == "/api/triage":
                code, obj = run_triage(sig)
            else:
                code, obj = run_autopsy(sig)
        else:
            code, obj = 404, {"ok": False, "error": "not found"}
        self._send_json(code, obj)


def main():
    mode = "--serve"
    argv = [a for a in sys.argv[1:]]
    if argv:
        mode = argv[0]
        if mode not in ("--serve", "--once"):
            sys.stderr.write(__doc__)
            sys.exit(2)

    BASE.mkdir(parents=True, exist_ok=True)

    if mode == "--once":
        ok = collect_tick()
        print("collect tick: %s (collector %s)" % (
            "ran" if ok else "skipped",
            "found" if COLLECTOR.exists() else "not deployed yet"))
        return

    # --serve
    # Run the loop in a thread; SIGTERM/SIGINT stop it and shut the server down.
    worker = threading.Thread(target=collection_loop, daemon=True)
    worker.start()

    def _term(signum, frame):
        STOP.set()
        threading.Thread(target=httpd.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _term)
    signal.signal(signal.SIGINT, _term)

    class OpsServer(ThreadingHTTPServer):
        allow_reuse_address = True

    httpd = OpsServer((HOST, PORT), Handler)
    print("[%s] ops-visibility server on %s:%d" % (now_iso(), HOST, PORT))
    sys.stdout.flush()
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
        print("[%s] ops-visibility server stopped" % now_iso())


if __name__ == "__main__":
    main()
