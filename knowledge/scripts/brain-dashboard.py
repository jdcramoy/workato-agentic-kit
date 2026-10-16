#!/usr/bin/env python3
# brain-dashboard.py — full-visibility operational dashboard for the agentic harness.
# Sections: machine health (launchd timers + heartbeats), fleet detail (log tails),
# agents, gossip bus, claims, capabilities, regression, watchdog/docs-delta, dream,
# evals/usage/cost, slack presence, build ledger, repos. Everything drillable.
# Generates ~/.claude/knowledge/dashboard.html. Zero tokens, ~100% local files.

import os, json, glob, time, html, subprocess, datetime as dt
import xml.etree.ElementTree as ET
try:
    import sys
except Exception:
    pass

HOME = os.path.expanduser("~")
K = os.path.join(HOME, ".claude", "knowledge")
OUT = os.path.join(K, "dashboard.html")
FLEET_STATE = os.path.join(HOME, ".local", "state", "fleet")
LAUNCH_AGENTS = os.path.join(HOME, "Library", "LaunchAgents")
AGENTS_DIR = os.path.join(HOME, ".claude", "agents")
REPOS = [
    ("knowledge", K),
    ("agentic-kit", os.path.join(HOME, "Documents", "agentic-workato-kit")),
    ("josh-orca", os.path.join(HOME, "Documents", "josh-orca")),
]


def read_jsonl(path):
    rows = []
    try:
        with open(path, errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return rows


def ts_epoch(ts):
    try:
        return time.mktime(time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return 0.0


def esc(s):
    return html.escape(str(s))


def rel_or_dash(ts):
    """Human 'age' string for a timestamp."""
    ep = ts_epoch(ts)
    if not ep:
        return "—"
    age = time.time() - ep
    if age < 0:
        age = 0
    if age < 3600:
        return f"{int(age//60)}m ago"
    if age < 86400:
        return f"{int(age//3600)}h ago"
    return f"{int(age//86400)}d ago"


def tail(path, n=40):
    try:
        with open(path, errors="replace") as fh:
            lines = fh.readlines()
        return "".join(lines[-n:]).strip() or "(empty)"
    except OSError:
        return "(no log yet)"


def read_head(path, n=1500):
    try:
        with open(path, errors="replace") as fh:
            return fh.read(n).strip() or "(empty)"
    except OSError:
        return "(missing)"


# ---- collectors -------------------------------------------------------------

HEARTBEAT = os.path.join(K, "garden-reports", "heartbeat.jsonl")

# launchd label suffix -> heartbeat job name it checks in as
JOB_ALIAS = {
    "docs-watch": "docs-watch", "workato-docs-watch": "docs-watch",
    "gardener": "brain-gardener", "watchdog": "workato-watchdog",
    "brief": "morning-brief", "backup": "harness-backup",
    "dreamer": "harness-dreamer", "jira-triage": "jira-triage",
    "corpus": "corpus", "architect": "estate-architect",
    "health": "workato-health", "gym": "gym",
    "dream-mini": "harness-dreamer-mini", "brain-dashboard": "brain-dashboard",
    "agent-command-watcher": None,  # event-driven: no heartbeat, state file is the evidence
}


def _expected_window(sched):
    """Seconds after which a timer with this schedule is considered late."""
    import re
    m = re.match(r"every (\d+)h", sched)
    if m:
        return int(m.group(1)) * 3600 * 3
    m = re.match(r"every (\d+)m", sched)
    if m:
        return max(int(m.group(1)) * 60 * 3, 900)
    if sched.startswith("hourly"):
        return 2 * 3600
    if re.match(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun) ", sched):
        return 8 * 86400
    if re.match(r"^\d{2}:\d{2}$", sched):
        return 26 * 3600
    return 26 * 3600


def timers():
    """Every com.josh launchd timer: schedule, evidence (FRESHEST of heartbeat /
    log mtime / state file wins — a fixed heartbeat>log priority misreported the
    2026-10-15 heartbeat wipe as 19 late/missed timers whose job logs said "done
    validated"), and a state that means what it says:
    ok = ran within window · late = overdue <3x · overdue = missed · new = never fired."""
    import re as _re2
    heart = {}
    for e in read_jsonl(HEARTBEAT):
        j = e.get("job", "")
        if j not in heart or ts_epoch(e.get("ts", "")) > ts_epoch(heart[j]):
            heart[j] = e["ts"]
    out = []
    for p in sorted(glob.glob(os.path.join(LAUNCH_AGENTS, "com.josh*.plist"))):
        name = os.path.basename(p)[:-6].replace("com.josh.", "").replace("fleet.", "")
        label = os.path.basename(p)[:-6]
        sched = "?"
        plist_log = None
        try:
            xml = open(p, errors="replace").read()
            m = _re2.search(r"<key>StartCalendarInterval</key>\s*<dict>(.*?)</dict>", xml, _re2.DOTALL)
            if m:
                body = m.group(1)
                def kv(k, s=body):
                    mm = _re2.search(rf"<key>{k}</key>\s*<integer>(\d+)</integer>", s)
                    return int(mm.group(1)) if mm else None
                h, mi, wd = kv("Hour"), kv("Minute"), kv("Weekday")
                if h is not None:
                    # wd=0 is Sunday — `wd or ""` turned it falsy and weekly
                    # Sunday jobs got a 26h window (false "overdue" forever)
                    day = {"1": "Mon", "2": "Tue", "3": "Wed", "4": "Thu",
                           "5": "Fri", "6": "Sat", "0": "Sun"}.get(str(wd), "") if wd is not None else ""
                    sched = f"{day + ' ' if day else ''}{h:02d}:{mi or 0:02d}"
                elif mi is not None:
                    sched = f"hourly :{mi:02d}"
                else:
                    sched = "calendar"
            else:
                si = _re2.search(r"<key>StartInterval</key>\s*<integer>(\d+)</integer>", xml)
                if si:
                    secs = int(si.group(1))
                    sched = (f"every {secs//3600}h" if secs >= 3600 else
                             f"every {secs//60}m" if secs >= 60 else f"every {secs}s")
            mp = _re2.search(r"<key>Standard(?:Out|Error)Path</key>\s*<string>([^<]+)</string>", xml)
            if mp:
                plist_log = mp.group(1)
        except Exception:
            pass
        hb_name = JOB_ALIAS.get(name, name)
        hb_ts = heart.get(hb_name) if hb_name else None
        if name == "dreamer":
            for cand in ("harness-dreamer", "dreamer"):
                if cand in heart and (not hb_ts or ts_epoch(heart[cand]) > ts_epoch(hb_ts)):
                    hb_ts = heart[cand]
        # evidence fallbacks: log mtime (incl. plist-declared log) and known state files
        log = os.path.join(FLEET_STATE, f"{name}.log")
        if not os.path.exists(log):
            log = os.path.join(FLEET_STATE, f"{name}.launchd.log")
        if name == "dream-mini":
            log = os.path.join(K, "dreams", "data", "mini.log")
        cand_logs = [log] + ([plist_log] if plist_log and plist_log != log else [])
        log_exists = any(os.path.exists(l) for l in cand_logs)
        if not log_exists:
            for l in cand_logs:
                if l and os.path.exists(l):
                    log = l
        if not hb_ts:
            if name == "dream-mini":
                log = os.path.join(K, "dreams", "data", "mini.log")
            if name == "agent-command-watcher":
                sf = os.path.join(K, "garden-reports", "command-watcher-state.json")
                if os.path.exists(sf):
                    hb_ts = dt.datetime.fromtimestamp(os.path.getmtime(sf)).strftime("%Y-%m-%dT%H:%M:%SZ")
                    log = sf
            elif log_exists:
                newest = max((l for l in cand_logs if os.path.exists(l)), key=os.path.getmtime)
                log = newest
                hb_ts = dt.datetime.fromtimestamp(os.path.getmtime(newest)).strftime("%Y-%m-%dT%H:%M:%SZ")
        # state semantics: freshest evidence wins (heartbeat, log mtime, state
        # file all compete). heartbeat.jsonl lost rows to a wholesale rewrite
        # on 2026-10-15 — a stale heartbeat must never outrank a fresh log
        # that says "done validated". Source tag in the detail makes the next
        # wipe diagnosable from the chip.
        cands = []
        if hb_ts:
            cands.append((ts_epoch(hb_ts), "hb", hb_ts))
        for l in cand_logs:
            if l and os.path.exists(l):
                cands.append((os.path.getmtime(l), "log", l))
        if name == "agent-command-watcher":
            sf = os.path.join(K, "garden-reports", "command-watcher-state.json")
            if os.path.exists(sf):
                cands.append((os.path.getmtime(sf), "state", sf))
        if cands:
            ev_epoch, ev_src, ev_ref = max(cands, key=lambda c: c[0])
            ev_ts = ev_ref if ev_src == "hb" else dt.datetime.fromtimestamp(ev_epoch).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            ev_epoch, ev_src, ev_ts = None, None, None
        if ev_ts is None:
            state, detail = "new", "pending first run"
        elif name == "agent-command-watcher":
            # event-driven, quiet by design: writes state only when it sees commands
            state, detail = "ok", f"event-driven · wrote {rel_or_dash(ev_ts)}"
        else:
            age = time.time() - ev_epoch
            win = _expected_window(sched)
            tag = {"hb": "", "log": " (log)", "state": " (state)"}[ev_src]
            if age < win:
                state = "ok"
                detail = rel_or_dash(ev_ts) + tag
            elif age < win * 3:
                state, detail = "late", f"{rel_or_dash(ev_ts)} — overdue{tag}"
            else:
                state, detail = "overdue", f"{rel_or_dash(ev_ts)} — missed{tag}"
        last_log = ""
        try:
            lines = open(log, errors="replace").readlines() if os.path.exists(log) else []
            # last MEANINGFUL line: pretty-printed JSON logs end in bare
            # braces/brackets — skipping them keeps the Fleet table free
            # of "}" / "]" rows
            last_log = next((l.strip() for l in reversed(lines)
                             if l.strip() and l.strip() not in ("}", "{", "]", "[")), "")
        except OSError:
            pass
        out.append({"name": name, "label": label, "sched": sched, "state": state,
                    "detail": detail, "hb": hb_ts or "", "log": log, "last_log": last_log[:160]})
    return out


def agents_roster(events):
    """Agent SOPs from ~/.claude/agents + live bus stats per outbox."""
    per = {}
    for e in events:
        per.setdefault(e.get("_outbox", "?"), []).append(e)
    all_outboxes = sorted(glob.glob(os.path.join(K, "dreams", "bus", "*.jsonl")))
    roster = []
    for p in all_outboxes:
        name = os.path.basename(p)[:-6]
        rows = read_jsonl(p)
        last = rows[-1] if rows else {}
        desc = ""
        ap = os.path.join(AGENTS_DIR, f"{name}.md")
        if os.path.exists(ap):
            try:
                head = open(ap, errors="replace").read(1200)
                after = head.split("---", 2)[-1].strip()
                desc = after.splitlines()[0] if after else ""
            except OSError:
                pass
        roster.append({"name": name, "desc": desc[:140], "n24h": len(per.get(name, [])),
                       "last_ts": last.get("ts", ""), "last_line": (last.get("line") or "")[:200],
                       "path": p})
    # agents with SOPs but no outbox yet
    have = {r["name"] for r in roster}
    for ap in sorted(glob.glob(os.path.join(AGENTS_DIR, "*.md"))):
        n = os.path.basename(ap)[:-3]
        if n not in have:
            roster.append({"name": n, "desc": "(no bus outbox yet)", "n24h": 0,
                           "last_ts": "", "last_line": "", "path": ap})
    return roster


def claims_rows():
    return read_jsonl(os.path.join(K, "claims", "claims.jsonl"))


def capabilities_rows():
    return read_jsonl(os.path.join(K, "capabilities.jsonl"))


def bus_summary():
    events = []
    for f in glob.glob(os.path.join(K, "dreams", "bus", "*.jsonl")):
        for e in read_jsonl(f):
            e["_outbox"] = os.path.basename(f)[:-6]
            e["_raw"] = json.dumps(e, ensure_ascii=False)[:500]
            events.append(e)
    cut = time.time() - 86400
    events = [e for e in events if ts_epoch(e.get("ts", "")) >= cut]
    events.sort(key=lambda e: e.get("ts", ""), reverse=True)
    threads = {}
    for e in events:
        tid = e.get("thread_id") or e.get("subject", "?")
        t = threads.setdefault(tid, {"witnesses": set(), "corr": 0, "line": "", "kind": ""})
        t["witnesses"].add(e.get("agent", "?"))
        if e.get("kind") == "verify":
            t["corr"] += 1
        if not t["line"] and e.get("kind") == "finding":
            t["line"], t["kind"] = e.get("line", ""), e.get("kind", "")
    return events, threads


def autonomous_work():
    rows = read_jsonl(os.path.join(K, "build-ledger.jsonl"))
    cut = time.time() - 86400
    rows = [r for r in rows if ts_epoch(r.get("ts", "")) >= cut]
    rows.sort(key=lambda r: r.get("ts", ""), reverse=True)
    return rows[:40]


def latest_report(pattern, folder="garden-reports"):
    files = sorted(glob.glob(os.path.join(K, folder, pattern)))
    if not files:
        return None, ""
    f = files[-1]
    try:
        return os.path.basename(f), open(f, errors="replace").read()[:3000]
    except OSError:
        return os.path.basename(f), ""


def canon_rows():
    return read_jsonl(os.path.join(K, "regression-canon", "canon.jsonl"))


def dream_meta():
    dreams = sorted(glob.glob(os.path.join(K, "dreams", "2*.md")))
    minis = sorted(glob.glob(os.path.join(K, "dreams", "mini-*.md")))
    verdict = mode = ""
    if dreams:
        head = open(dreams[-1], errors="replace").read(600)
        m1, m2 = _re(r"one_line_verdict:\s*(.+)", head), _re(r"^mode:\s*(.+)", head, True)
        verdict = m1.group(1) if m1 else ""
        mode = m2.group(1) if m2 else ""
    seeds = read_jsonl(os.path.join(K, "dreams", "visions", "seeds.jsonl"))
    outcomes = read_jsonl(os.path.join(K, "garden-reports", "proposal-outcomes.jsonl"))
    return (os.path.basename(dreams[-1]) if dreams else "none", mode, verdict, len(seeds),
            seeds[-1].get("seed", "")[:240] if seeds else "", len(minis), outcomes)


def proposal_pipeline():
    """Dream proposal queue via proposal-pipeline.py (read-only)."""
    try:
        r = subprocess.run(["python3", os.path.join(HOME, ".claude", "knowledge",
                                                  "scripts", "proposal-pipeline.py"), "--json"],
                           capture_output=True, text=True, timeout=10)
        return json.loads(r.stdout)
    except Exception:
        return {"counts": {}, "items": []}


def owned_health():
    """Owned-asset registry + latest health sweep (read-only)."""
    try:
        registry = json.load(open(os.path.join(K, "workato-health", "owned-registry.json")))
    except Exception:
        registry = {"recipes": []}
    try:
        latest = json.load(open(os.path.join(K, "workato-health", "health-latest.json")))
    except Exception:
        latest = {}
    return registry, latest


def eval_rows():
    rows = read_jsonl(os.path.join(K, "evals", "results.jsonl"))
    latest = {}
    for r in rows:
        latest[r.get("id", "?")] = r
    return list(latest.values())


def usage_stats():
    rows = read_jsonl(os.path.join(K, "garden-reports", "usage-ledger.jsonl"))
    cut = time.time() - 86400
    day = [r for r in rows if ts_epoch(r.get("ts", "")) >= cut]
    kinds = {}
    for r in day:
        kinds[r.get("kind", "?")] = kinds.get(r.get("kind", "?"), 0) + 1
    return len(day), kinds


def slack_open():
    rows = read_jsonl(os.path.join(K, "slack-posts.jsonl"))
    open_rows = [r for r in rows if str(r.get("status", "open")).lower() == "open"]
    return len(rows), open_rows


def cortex_questions():
    return read_jsonl(os.path.join(K, "cortex", "questions.jsonl"))[-5:]


def repo_state():
    out = []
    for name, path in REPOS:
        try:
            r = subprocess.run(["git", "-C", path, "log", "-1", "--format=%h %ad %s",
                                "--date=format:%m-%d %H:%M"], capture_output=True, text=True, timeout=5)
            out.append((name, path, r.stdout.strip() or "(no commits)", r.returncode == 0))
        except Exception:
            out.append((name, path, "(git failed)", False))
    return out


def platform_deltas():
    return read_jsonl(os.path.join(K, "garden-reports", "platform-delta.jsonl"))[-6:]


def _re(pat, text, multiline=False):
    import re
    return re.search(pat, text, re.MULTILINE if multiline else 0)


# ---- render -----------------------------------------------------------------

CSS = """
:root {
  --teal:#108291; --turf:#67EADD; --bg:#0A1018; --card:#101826; --card2:#15202F;
  --line:#1F2E42; --text:#E3EDF7; --muted:#7E93AC; --ok:#3DDC97; --warn:#FFC24B; --bad:#FF6B6B;
}
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--text);
  font:14px/1.55 -apple-system,'SF Pro Text','Segoe UI',system-ui,sans-serif; }
nav.topnav { position:sticky; top:0; z-index:9; background:rgba(10,16,24,.92); backdrop-filter:blur(8px);
  border-bottom:1px solid var(--line); padding:8px 40px; display:flex; gap:4px; flex-wrap:wrap; }
nav.topnav a { color:var(--muted); text-decoration:none; font-size:11.5px; font-weight:700;
  padding:3px 10px; border-radius:99px; letter-spacing:.4px; }
nav.topnav a:hover { background:var(--card2); color:var(--turf); }
header { padding:26px 40px 22px; background:linear-gradient(100deg,#0E4A54 0%,var(--teal) 55%,#0C6E79 100%);
  border-bottom:1px solid var(--line); position:relative; overflow:hidden; }
header::after { content:""; position:absolute; inset:0;
  background:radial-gradient(600px 200px at 85% -40%, rgba(103,234,221,.28), transparent 60%); pointer-events:none; }
.brand { display:flex; align-items:baseline; gap:14px; }
.wordmark { font-weight:800; font-size:22px; color:#fff; letter-spacing:.5px; }
.wordmark b { color:var(--turf); font-weight:800; }
.tagline { color:#BFE6EA; font-size:12.5px; letter-spacing:.3px; }
.hmeta { margin-top:10px; display:flex; gap:10px; align-items:center; color:#CDEDF0; font-size:12px; }
.mode-pill { background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.25);
  color:#fff; padding:2px 12px; border-radius:99px; font-weight:700; font-size:11px; letter-spacing:.8px; text-transform:uppercase; }
main { max-width:1360px; margin:0 auto; padding:26px 40px 70px; }
.stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:14px; margin-top:-2px; }
.stat { background:linear-gradient(180deg,var(--card2),var(--card)); border:1px solid var(--line);
  border-radius:14px; padding:16px 18px 14px; }
.stat-v { font-size:30px; font-weight:800; color:#fff; letter-spacing:-.5px; }
.stat-l { font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:1px; color:var(--turf); margin-top:2px; }
.stat-s { font-size:11px; color:var(--muted); margin-top:2px; }
h2 { font-size:12px; font-weight:800; text-transform:uppercase; letter-spacing:1.6px; color:var(--turf);
  margin:34px 0 12px; display:flex; align-items:center; gap:10px; scroll-margin-top:56px; }
h2::after { content:""; flex:1; height:1px; background:var(--line); }
.card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px 18px; }
.grid2 { display:grid; grid-template-columns:1.15fr 1fr; gap:16px; }
.grid3 { display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px; }
@media (max-width: 900px) { .grid2 { grid-template-columns:1fr; } }
.qcard { display:flex; gap:12px; align-items:flex-start; background:var(--card2);
  border:1px solid var(--line); border-radius:10px; padding:10px 14px; margin-bottom:8px; }
.qnum { flex:none; width:24px; height:24px; border-radius:50%; background:var(--teal); color:#fff;
  font-weight:800; font-size:12px; display:flex; align-items:center; justify-content:center; }
.qbody { font-size:13px; }
.chips { display:flex; flex-wrap:wrap; gap:10px; }
.chip { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 14px;
  min-width:150px; cursor:pointer; transition:border-color .15s; }
.chip:hover { border-color:var(--turf); }
.chip-name { font-weight:700; font-size:13px; display:flex; align-items:center; gap:7px; }
.dot { width:8px; height:8px; border-radius:50%; display:inline-block; flex:none; }
.dot.ok { background:var(--ok); box-shadow:0 0 8px rgba(61,220,151,.7); }
.dot.late { background:var(--warn); box-shadow:0 0 8px rgba(255,194,75,.6); }
.dot.overdue { background:var(--bad); box-shadow:0 0 8px rgba(255,107,107,.5); }
.dot.new { background:var(--muted); opacity:.55; }
.chip-detail { color:var(--muted); font-size:11px; margin-top:2px; }
table { width:100%; border-collapse:collapse; font-size:12.5px; }
th { color:var(--muted); font-size:10.5px; font-weight:700; text-transform:uppercase; letter-spacing:1px;
  text-align:left; padding:4px 8px; }
td { padding:7px 8px; border-bottom:1px solid var(--line); vertical-align:top; }
tr:last-child td { border-bottom:none; }
tr.xrow { cursor:pointer; }
tr.xrow:hover td { background:rgba(103,234,221,.06); }
tr.xdetail td { background:var(--card2); padding:10px 14px; }
tr.xdetail { display:none; }
tr.xdetail.open { display:table-row; }
.chev { color:var(--muted); font-size:10px; display:inline-block; transition:transform .15s; }
tr.xrow.open .chev { transform:rotate(90deg); }
.muted { color:var(--muted); }
.mono { font-family:ui-monospace,'SF Mono',Menlo,monospace; font-size:12px; }
.badge { display:inline-block; padding:1px 9px; border-radius:99px; font-size:10.5px; font-weight:700; }
.badge.finding { background:#123c33; color:var(--ok); }
.badge.verify { background:#123044; color:#7CC7F5; }
.badge.handoff { background:#3a2f12; color:var(--warn); }
.badge.open { background:#3a2f12; color:var(--warn); }
.badge.stale { background:#3a2f12; color:var(--warn); }
.badge.fixed, .badge.tested, .badge.active { background:#123c33; color:var(--ok); }
.badge.proposed { background:#3a2f12; color:var(--warn); }
.badge.accepted { background:#123044; color:#7CC7F5; }
.badge.built { background:#123c33; color:var(--ok); }
.badge.rejected { background:#2a1520; color:var(--bad); }
a.filelink { color:#7CC7F5; text-decoration:none; font-size:11px; }
a.filelink:hover { text-decoration:underline; }
details.logbox { margin-top:6px; }
details.logbox summary { cursor:pointer; color:var(--muted); font-size:11.5px; font-weight:700; }
details.logbox pre { margin-top:6px; }
.verdict { font-size:14.5px; line-height:1.6; color:#EAF3FA; border-left:3px solid var(--turf);
  padding:6px 0 6px 16px; margin:4px 0 10px; }
.seed { font-style:italic; color:#9FB4C8; border-left:3px solid var(--line); padding:4px 0 4px 16px; }
#filter { background:var(--card2); border:1px solid var(--line); color:var(--text); border-radius:99px;
  padding:6px 16px; font-size:12.5px; width:280px; outline:none; }
#filter:focus { border-color:var(--turf); }
pre { white-space:pre-wrap; font:11.5px/1.55 ui-monospace,Menlo,monospace; color:#B9C9DB; margin:0;
  max-height:340px; overflow:auto; }
footer { color:var(--muted); font-size:11px; padding:26px 40px; text-align:center; }
"""

JS = """
function toggleRow(tr) {
  var d = tr.nextElementSibling;
  if (!d || !d.classList.contains('xdetail')) return;
  var open = d.classList.toggle('open');
  tr.classList.toggle('open', open);
}
document.addEventListener('click', function(ev) {
  var tr = ev.target.closest('tr.xrow');
  if (tr && !ev.target.closest('a')) toggleRow(tr);
});
function jump(id) {
  var el = document.getElementById(id);
  if (el) { el.scrollIntoView({behavior:'smooth', block:'start'}); return false; }
  return true;
}
document.getElementById('filter').addEventListener('input', function() {
  var q = this.value.toLowerCase();
  document.querySelectorAll('tbody').forEach(function(tb) {
    tb.querySelectorAll('tr.xrow').forEach(function(tr) {
      var hit = !q || tr.textContent.toLowerCase().includes(q);
      tr.style.display = hit ? '' : 'none';
      if (!hit) { var d = tr.nextElementSibling;
        if (d && d.classList.contains('xdetail')) { d.classList.remove('open'); tr.classList.remove('open'); } }
    });
  });
});
"""


def chip(name, state, detail, anchor):
    cls = state if state in ("ok", "late", "overdue", "new") else "new"
    return (f'<div class="chip" onclick="return jump(\'{anchor}\')">'
            f'<span class="chip-name"><span class="dot {cls}"></span>{esc(name)}</span>'
            f'<span class="chip-detail">{esc(detail)}</span></div>')


def xrow(cells, detail_html):
    """Clickable table row + hidden detail row."""
    tds = "".join(f"<td>{c}</td>" for c in cells)
    return (f'<tr class="xrow"><td><span class="chev">&#9656;</span></td>{tds}</tr>'
            f'<tr class="xdetail"><td></td><td colspan="9">{detail_html}</td></tr>')


def render():
    tmrs = timers()
    events, threads = bus_summary()
    work = autonomous_work()
    claims = claims_rows()
    caps = capabilities_rows()
    canon = canon_rows()
    dname, dmode, dverdict, nseeds, last_seed, nminis, outcomes = dream_meta()
    pipeline = proposal_pipeline()
    pcounts = pipeline.get("counts", {})
    registry, latest_sweep = owned_health()
    reg_name, reg_body = latest_report("regression-latest.md")
    wd_name, wd_body = latest_report("watchdog-*.md")
    cost_name, cost_body = latest_report("cost-heatmap-latest.md")
    roster = agents_roster(events)
    evals = eval_rows()
    n_usage, usage_kinds = usage_stats()
    n_slack, open_slack = slack_open()
    cq = cortex_questions()
    repos = repo_state()
    deltas = platform_deltas()
    gen = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    # ---- summary numbers ----
    total_claims = len(claims)
    active_claims = [c for c in claims if c.get("status") == "active"]
    today = dt.date.today().isoformat()
    stale_claims = [c for c in active_claims if str(c.get("last_verified", "")) < today]
    open_canon = [c for c in canon if c.get("status") != "tested"]
    eval_pass = f"{sum(1 for e in evals if e.get('pass'))}/{len(evals)}" if evals else "n/a"
    ok_timers = sum(1 for t in tmrs if t["state"] == "ok")
    agents_speaking = len({e.get("_outbox") for e in events})

    pending_timers = sum(1 for t in tmrs if t["state"] == "new")
    bad_timers = sum(1 for t in tmrs if t["state"] in ("late", "overdue"))
    agents_speaking = len({e.get("_outbox") for e in events})

    stat = lambda label, value, sub="": f"""
      <div class="stat"><div class="stat-v">{value}</div><div class="stat-l">{label}</div><div class="stat-s">{sub}</div></div>"""

    # ---- machine health chips ----
    chips = "".join(chip(t["name"], t["state"], f'{t["sched"]} · {t["detail"]}', f"fleet-{t['name']}") for t in tmrs)

    # ---- fleet table with log-tail drilldown ----
    fleet_rows = ""
    for t in tmrs:
        d = (f'<div class="muted" style="font-size:11px">{esc(t["label"])} · {esc(t["sched"])}</div>'
             f'<details class="logbox"><summary>log tail — {esc(os.path.basename(t["log"]))}</summary>'
             f"<pre>{esc(tail(t['log'], 30))}</pre></details>"
             f'<a class="filelink" href="file://{esc(t["log"])}">open full log</a>')
        fleet_rows += xrow(
            [f'<span class="dot {t["state"]}" style="display:inline-block"></span> <b>{esc(t["name"])}</b>',
             esc(t["sched"]), esc(t["detail"]),
             f'<span class="muted">{esc(t["last_log"][:110])}</span>'], d)

    # ---- agents ----
    agent_rows = ""
    for a in roster:
        detail = (f'<div class="muted" style="font-size:11px">{esc(a["desc"])}</div>'
                  + (f'<div style="margin-top:6px" class="muted">last post: {esc(rel_or_dash(a["last_ts"]))}</div>'
                     f'<pre>{esc(a["last_line"])}</pre>' if a["last_ts"] else "")
                  + f'<a class="filelink" href="file://{esc(a["path"])}">open outbox / SOP</a>')
        agent_rows += xrow(
            [f'<b>{esc(a["name"])}</b>', f'{a["n24h"]} in 24h', f'<span class="muted">{esc(rel_or_dash(a["last_ts"]))}</span>',
             f'<span class="muted">{esc(a["last_line"][:110])}</span>'], detail)

    # ---- bus timeline ----
    event_rows = ""
    for e in events[:25]:
        event_rows += xrow(
            [f'<span class="muted">{esc(str(e.get("ts",""))[5:16].replace("T"," "))}</span>',
             esc(e.get("_outbox", "")),
             f'<span class="badge {esc(e.get("kind",""))}">{esc(e.get("kind",""))}</span>',
             f'<span class="muted">{esc(e.get("line","")[:130])}</span>'],
            f'<pre>{esc(e.get("_raw",""))}</pre>')

    thread_rows = ""
    for tid, t in sorted(threads.items(), key=lambda kv: (-kv[1]["corr"], -len(kv[1]["witnesses"]))):
        thread_rows += xrow(
            [esc(tid[:44]), f'{t["corr"]}x', f'{len(t["witnesses"])}',
             f'<span class="muted">{esc(t["line"][:120])}</span>'],
            f'<div class="muted">witnesses: {esc(", ".join(sorted(t["witnesses"])))}</div>')

    # ---- claims ----
    claim_rows = ""
    for c in claims:
        if c.get("status") != "active":
            continue
        is_stale = str(c.get("last_verified", "")) < today
        ev = "<br>".join(f'· {esc(e.get("type",""))}: {esc(e.get("ref",""))}' for e in c.get("evidence", []))
        detail = (f'<div>{esc(c.get("claim",""))}</div>'
                  f'<div class="muted" style="margin-top:6px">evidence:</div><div>{ev or "(none)"}</div>'
                  f'<a class="filelink" href="file://{esc(os.path.join(K, "claims", "claims.jsonl"))}">open ledger</a>')
        claim_rows += xrow(
            [f'<span class="mono">{esc(c.get("id",""))}</span>', esc(c.get("subject","")),
             f'<span class="badge {"stale" if is_stale else "active"}">{"stale" if is_stale else "active"}</span>',
             f'<span class="muted">verified {esc(str(c.get("last_verified","")) or "?")}</span>'], detail)

    # ---- capabilities ----
    cap_rows = ""
    for c in reversed(caps[-12:]):
        cap_rows += xrow(
            [f'<span class="muted">{esc(str(c.get("ts",""))[5:10])}</span>', esc(c.get("capability","")[:100]),
             f'<span class="muted">{esc(c.get("evidence","")[:80])}</span>'],
            f'<pre>{esc(json.dumps(c, ensure_ascii=False, indent=1)[:600])}</pre>')

    # ---- canon ----
    canon_rows_html = ""
    for c in canon:
        detail = (f'<div>{esc(c.get("line",""))}</div>'
                  f'<div class="muted" style="margin-top:6px">found {esc(c.get("found",""))} by {esc(c.get("found_by",""))}'
                  f' · test case: {esc(str(c.get("test_case_id") or "none yet"))}</div>')
        canon_rows_html += xrow(
            [f'<span class="mono">{esc(c.get("recipe_id",""))}</span>', esc(c.get("signature","")),
             f'<span class="badge {esc(c.get("status",""))}">{esc(c.get("status",""))}</span>',
             f'<span class="muted">{esc(c.get("line","")[:90])}</span>'], detail)

    # ---- attention queue ----
    queue_lines = [l for l in attention_queue().splitlines() if l.strip() and not l.strip().startswith("#")]
    queue_cards = "".join(
        f'<div class="qcard"><div class="qnum">{i+1}</div><div class="qbody">{esc(l.lstrip("-0123456789. )"))}</div></div>'
        for i, l in enumerate(queue_lines[:7])) or '<div class="qcard"><div class="qbody muted">quiet — nothing attended</div></div>'

    # ---- build ledger ----
    work_rows = ""
    for r in work:
        work_rows += xrow(
            [f'<span class="muted">{esc(str(r.get("ts",""))[5:16].replace("T"," "))}</span>',
             esc(r.get("kind") or r.get("tool", "")),
             f'<span class="mono">{esc(str(r.get("recipe_id") or ""))}</span>',
             f'<span class="muted">{esc((r.get("command") or r.get("tool") or "")[:90])}</span>'],
            f'<pre>{esc(json.dumps(r, ensure_ascii=False)[:600])}</pre>')

    # ---- proposal pipeline (dream queue) ----
    prop_rows = ""
    for it in pipeline.get("items", []):
        st = it.get("status", "?")
        prop_rows += xrow(
            [f'<b>{esc(it.get("title",""))}</b>',
             f'<span class="badge {esc(st)}">{esc(st)}</span>',
             esc(it.get("kind", "?")), f'<span class="muted">{esc(it.get("date",""))}</span>'],
            (f'<div class="muted">risk {esc(it.get("risk","?"))} · file: dreams/proposals/{esc(it.get("file",""))}</div>'
             f'<a class="filelink" href="file://{esc(os.path.join(K, "dreams", "proposals", it.get("file","")))}">open proposal</a>'))
    if not prop_rows:
        prop_rows = "<tr><td colspan=5 class='muted'>proposal queue empty — dreamer files here nightly</td></tr>"

    # ---- evals / usage / cost ----
    eval_rows_html = "".join(
        f'<tr><td>{esc(e.get("id",""))}</td>'
        f'<td><span class="badge {"fixed" if e.get("pass") else "open"}">{"pass" if e.get("pass") else "fail"}</span></td>'
        f'<td>{esc(e.get("score",""))}</td><td class="muted">{esc(e.get("ts",""))[:16]}</td></tr>'
        for e in evals) or "<tr><td colspan=4 class='muted'>no eval results yet</td></tr>"
    kind_str = ", ".join(f"{k} {v}" for k, v in sorted(usage_kinds.items(), key=lambda kv: -kv[1])[:6]) or "quiet"

    # ---- slack presence ----
    slack_rows = "".join(
        f'<tr><td>{esc(str(r.get("date","")))}</td><td>{esc(r.get("channel",""))}</td>'
        f'<td><span class="badge open">{esc(r.get("status","open"))}</span></td>'
        f'<td class="muted">{esc(r.get("summary","")[:110])}</td>'
        f'<td><a class="filelink" href="{esc(r.get("permalink",""))}">open</a></td></tr>'
        for r in open_slack[-8:]) or "<tr><td colspan=5 class='muted'>no open posts — every post answered</td></tr>"

    # ---- repos ----
    repo_rows = "".join(
        f'<tr><td><b>{esc(n)}</b></td><td class="mono">{esc(s.split(" ", 1)[0] if ok else "—")}</td>'
        f'<td class="muted">{esc(s if ok else "(missing repo)")}</td></tr>' for n, p, s, ok in repos)

    # ---- docs deltas ----
    delta_rows = "".join(
        f'<tr><td class="muted">{esc(str(e.get("ts",""))[5:16])}</td>'
        f'<td>{esc(e.get("source", e.get("title", "")))[:60]}</td>'
        f'<td class="muted">{esc(str(e.get("delta", e.get("line", "")))[:110])}</td></tr>'
        for e in deltas) or "<tr><td colspan=3 class='muted'>no platform deltas</td></tr>"

    # ---- cortex questions ----
    cq_rows = "".join(
        f'<div class="qcard"><div class="qnum">?</div><div class="qbody muted">{esc(q.get("question","")[:220])}</div></div>'
        for q in cq) or '<div class="qcard"><div class="qbody muted">no open questions</div></div>'

    nav = "".join(
        f'<a href="#{i}">{esc(lbl)}</a>' for i, lbl in [
            ("health", "health"), ("fleet", "fleet"), ("agents", "agents"), ("attention", "attention"),
            ("bus", "bus"), ("claims", "claims"), ("caps", "capabilities"), ("regression", "regression"),
            ("watchdog", "watchdog"), ("dream", "dream"), ("ops", "ops & cost"), ("slack", "slack"),
            ("work", "work"), ("repos", "repos")])

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>Harness — Agent Network Dashboard</title>
<style>{CSS}</style></head><body>
<header>
  <div class="brand">
    <div class="wordmark">workato<b>&nbsp;|&nbsp;harness</b></div>
    <div class="tagline">agent network, full visibility — click any row to drill down</div>
  </div>
  <div class="hmeta">
    <span class="mode-pill">{esc(dmode or 'report')}</span>
    <span>generated {gen}</span>
    <span>·</span><span>regenerates hourly at :09 · page reloads every 5 min</span>
    <span>·</span><input id="filter" type="search" placeholder="filter all tables...">
  </div>
</header>
<nav class="topnav">{nav}</nav>
<main>

<div class="stats">
  {stat("timers healthy", f"{ok_timers}/{len(tmrs)}", f"{pending_timers} pending first run · {bad_timers} late")}
  {stat("attention items", len(queue_lines) or 0, "cortex queue, cap 7")}
  {stat("bus events 24h", len(events), f"{agents_speaking} agents speaking")}
  {stat("claims active", len(active_claims), f"{total_claims} total · {len(stale_claims)} stale")}
  {stat("canon coverage", (f"{100 - round(100 * len(open_canon) / max(1, len(canon)))}%" if canon else "n/a"), f"{len(canon)} bugs · {len(open_canon)} open")}
  {stat("eval suite", eval_pass, "fitness evals, latest")}
  {stat("harness actions 24h", n_usage, kind_str)}
  {stat("open slack posts", n_slack, "tracked until answered")}
</div>

<h2 id="health">Machine health — every timer, 24h</h2>
<div class="chips">{chips}</div>

<h2 id="fleet">Fleet — schedules, heartbeats, log tails</h2>
<div class="card"><table>
<tr><th></th><th>timer</th><th>schedule</th><th>last check-in</th><th>last log line</th></tr>
{fleet_rows}</table></div>

<h2 id="agents">Agents — SOPs and bus presence</h2>
<div class="card"><table>
<tr><th></th><th>agent</th><th>bus 24h</th><th>last post</th><th>last line</th></tr>
{agent_rows}</table></div>

<h2 id="attention">Attention queue — cortex</h2>
<div>{queue_cards}</div>
<h2 style="margin-top:14px">Cortex open questions</h2>
<div>{cq_rows}</div>

<div class="grid2">
  <div>
    <h2 id="bus">Gossip bus — 24h (click a row for raw JSON)</h2>
    <div class="card"><table><tr><th></th><th>when</th><th>agent</th><th>kind</th><th>finding</th></tr>{event_rows}</table></div>
  </div>
  <div>
    <h2>Threads by corroboration</h2>
    <div class="card"><table><tr><th></th><th>thread</th><th>corr</th><th>witnesses</th><th>what</th></tr>{thread_rows}</table></div>
  </div>
</div>

<div class="grid2">
  <div>
    <h2 id="claims">Claim ledger — active</h2>
    <div class="card"><table><tr><th></th><th>id</th><th>subject</th><th>state</th><th>last verified</th></tr>{claim_rows}</table></div>
  </div>
  <div>
    <h2 id="caps">Capability ledger — newest</h2>
    <div class="card"><table><tr><th></th><th>when</th><th>capability</th><th>evidence</th></tr>{cap_rows}</table></div>
  </div>
</div>

<div class="grid2">
  <div>
    <h2 id="regression">Regression canon — {len(canon)} bugs, {len(open_canon)} open</h2>
    <div class="card"><table><tr><th></th><th>recipe</th><th>signature</th><th>status</th><th>line</th></tr>{canon_rows_html}</table></div>
  </div>
  <div>
    <h2>Regression — latest run ({esc(reg_name or "none")})</h2>
    <div class="card"><pre>{esc(reg_body[:1800])}</pre>
    <a class="filelink" href="file://{esc(os.path.join(K, 'garden-reports', 'regression-latest.md'))}">open full report</a></div>
  </div>
</div>

<div class="grid3">
  <div><h2 id="watchdog">Watchdog — latest ({esc(wd_name or "none")})</h2>
    <div class="card"><pre>{esc(wd_body[:1500])}</pre>
    <a class="filelink" href="file://{esc(os.path.join(K, 'garden-reports'))}">all reports</a></div></div>
  <div><h2>Platform docs deltas</h2>
    <div class="card"><table><tr><th>when</th><th>source</th><th>delta</th></tr>{delta_rows}</table></div></div>
</div>

<div class="grid2">
  <div>
    <h2 id="dream">Dream — latest ({esc(dname)}, +{nminis} minis)</h2>
    <div class="card">
      <div class="verdict">{esc(dverdict) or 'no verdict yet'}</div>
      <div class="muted" style="font-size:11px; margin-bottom:6px">latest vision seed · {nseeds} planted · file-gate: {pcounts.get('dream_inventions', 0)} inventions, {pcounts.get('proposed', 0) + pcounts.get('built', 0)} filed</div>
      <div class="seed">{esc(last_seed) or '(none yet)'}</div>
      <a class="filelink" href="file://{esc(os.path.join(K, 'dreams'))}">dreams directory</a>
    </div>
    <h2>Proposal pipeline — {pcounts.get('proposed', 0)} awaiting decision · {pcounts.get('accepted', 0)} ready to build</h2>
    <div class="card"><table><tr><th></th><th>proposal</th><th>status</th><th>kind</th><th>date</th></tr>{prop_rows}</table></div>
    <h2>Proposal outcomes — ladder accountability</h2>
    <div class="card">{''.join(
        f'<div class="qcard"><div class="qnum">{esc(o.get("action","")[:1].upper())}</div><div class="qbody">{esc(o.get("proposal","")[:110])}'
        f' <span class="badge {esc(o.get("action",""))}">{esc(o.get("action",""))}</span>'
        f'<div class="muted" style="font-size:11px">{esc(o.get("notes",""))[:130]}</div></div></div>'
        for o in reversed(outcomes[-5:])) or '<div class="muted">no outcomes logged yet</div>'}</div>
  </div>
  <div>
    <h2 id="ops">Evals · usage 24h · cost</h2>
    <div class="card">
      <table><tr><th>eval</th><th>result</th><th>score</th><th>when</th></tr>{eval_rows_html}</table>
      <div class="muted" style="margin-top:10px; font-size:11px">harness actions 24h: {esc(kind_str)}</div>
      <details class="logbox"><summary>cost heatmap — {esc(cost_name or "none")}</summary><pre>{esc(cost_body[:1200])}</pre></details>
    </div>
  </div>
</div>

<h2 id="slack">Slack presence — open posts under Josh's name</h2>
<div class="card"><table><tr><th>date</th><th>channel</th><th>status</th><th>summary</th><th></th></tr>{slack_rows}</table></div>

<h2 id="owned">Owned assets — self-discovered, health-swept hourly</h2>
<div class="card">
  <div class="muted" style="font-size:11.5px; margin-bottom:8px">
    registry: {len(registry.get('recipes', []))} recipes (+{len(registry.get('genies', []))} genies) ·
    {sum(1 for e in registry.get('recipes', []) if 'hypercare' in e['flags'])} prod-hypercare ·
    {sum(1 for e in registry.get('recipes', []) if 'new' in e['flags'])} new ·
    latest sweep {esc(latest_sweep.get('ts', '—'))}: {esc(json.dumps(latest_sweep.get('verdicts', {})))}
    — discovered from build-ledger fingerprints (asset-fingerprint.py), swept via wt (workato-health.py)
  </div>
  <table><tr><th>asset</th><th>workspace</th><th>flags</th><th>last touch</th><th>last sweep verdict</th></tr>
  {''.join(
    f'<tr><td class="mono">{esc(e["id"])}</td><td>{esc(",".join(e["servers"]))}</td>'
    f'<td>{esc(" ".join(e["flags"]))}</td><td class="muted">{esc(str(e["last_touch"])[:16])}</td>'
    f'<td class="muted">{esc(next((r["verdict"] for r in latest_sweep.get("failures", []) if r["id"]==e["id"]), "ok" if latest_sweep else "—"))}</td></tr>'
    for e in registry.get('recipes', [])[:15])}
  </table>
  <a class="filelink" href="file://{esc(os.path.join(K, 'workato-health'))}">health directory (sweeps, registry)</a>
</div>

<h2 id="work">Autonomous work — build ledger, 24h</h2>
<div class="card"><table><tr><th></th><th>when</th><th>kind</th><th>recipe</th><th>what</th></tr>{work_rows}</table></div>

<h2 id="repos">Repos</h2>
<div class="card"><table><tr><th>repo</th><th>HEAD</th><th>last commit</th></tr>{repo_rows}</table></div>

</main>
<footer>agentic harness · generated by brain-dashboard.py · the machines wrote this page</footer>
<script>{JS}</script>
</body></html>"""


def attention_queue():
    p = os.path.join(K, "cortex", "attention-queue.md")
    try:
        return open(p, errors="replace").read().strip()
    except OSError:
        return "(no attention queue yet — cortex hasn't pulsed)"


def main():
    os.makedirs(K, exist_ok=True)
    html_out = render()
    with open(OUT, "w") as fh:
        fh.write(html_out)
    print(OUT)
    # mechanical heartbeat (atomic_io, locked): this job runs raw python3, not
    # run-job.sh, and prints nothing on success — log mtime went 8d stale and
    # the dashboard showed a healthy hourly timer as "missed" (found 10-16).
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from atomic_io import atomic_append
        atomic_append(os.path.join(K, "garden-reports", "heartbeat.jsonl"),
                      {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                       "job": "brain-dashboard"})
    except Exception as exc:  # heartbeat must never fail the dashboard write
        print(f"heartbeat append failed: {exc}", file=sys.stderr)
    if "--open" in sys.argv:
        subprocess.run(["open", OUT])


if __name__ == "__main__":
    main()
