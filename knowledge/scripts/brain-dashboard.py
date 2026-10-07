#!/usr/bin/env python3
"""brain-dashboard.py — generate the full-page agent-network dashboard.

Assembles the machine's state into one self-contained HTML page
(~/.claude/knowledge/dashboard.html), Workato-branded (teal #108291,
turquoise #67EADD, slate #373D47 on a dark slate background).

Sections: machine health (heartbeats), attention queue (cortex), bus
(threads + corroboration), autonomous work (build ledger 24h), regression,
watchdog alerts, canon, dreams + vision seeds, claims ledger health.

Usage: python3 brain-dashboard.py [--open]
"""

import datetime as dt
import glob
import html
import json
import os
import subprocess
import time

HOME = os.path.expanduser("~")
K = os.path.join(HOME, ".claude", "knowledge")
OUT = os.path.join(K, "dashboard.html")


def read_jsonl(path):
    rows = []
    try:
        for line in open(path, errors="replace"):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
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


def urlize(text):
    out = esc(text)
    return out


# ---- collectors -------------------------------------------------------------

def machine_health():
    hb = read_jsonl(os.path.join(K, "garden-reports", "heartbeat.jsonl"))
    cut = time.time() - 86400
    jobs = {}
    for e in hb:
        if ts_epoch(e.get("ts", "")) >= cut:
            jobs.setdefault(e.get("job", "?"), []).append(e["ts"])
    roster = ["docs-watch", "brain-gardener", "workato-watchdog",
              "harness-backup", "harness-dreamer", "morning-brief"]
    rows = []
    for j in roster:
        ran = jobs.get(j)
        rows.append((j, "ok" if ran else "skip", ran[-1][5:16].replace("T", " ") if ran else "—"))
    return rows


def attention_queue():
    p = os.path.join(K, "cortex", "attention-queue.md")
    try:
        return open(p, errors="replace").read().strip()
    except OSError:
        return "(no attention queue yet — cortex hasn't pulsed)"


def bus_summary():
    events = []
    for f in glob.glob(os.path.join(K, "dreams", "bus", "*.jsonl")):
        for e in read_jsonl(f):
            e["_outbox"] = os.path.basename(f)[:-6]
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


def claims_health():
    claims = read_jsonl(os.path.join(K, "claims", "claims.jsonl"))
    active = [c for c in claims if c.get("status") == "active"]
    stale = [c for c in active if str(c.get("last_verified", "")) < dt.date.today().isoformat()]
    return len(claims), len(active), len(stale)


def canon_rows():
    return read_jsonl(os.path.join(K, "regression-canon", "canon.jsonl"))


def dream_meta():
    dreams = sorted(glob.glob(os.path.join(K, "dreams", "2*.md")))
    verdict = mode = ""
    if dreams:
        head = open(dreams[-1], errors="replace").read(600)
        m = re_search(r"one_line_verdict:\s*(.+)", head)
        v = re_search(r"^mode:\s*(.+)", head, True)
        verdict = m.group(1) if m else ""
        mode = v.group(1) if v else ""
    seeds = read_jsonl(os.path.join(K, "dreams", "visions", "seeds.jsonl"))
    return (os.path.basename(dreams[-1]) if dreams else "none", mode, verdict, len(seeds),
            seeds[-1].get("seed", "")[:240] if seeds else "")


def re_search(pat, text, multiline=False):
    import re
    return re.search(pat, text, re.MULTILINE if multiline else 0)


# ---- render -----------------------------------------------------------------

def chip(label, state, detail):
    cls = "ok" if state == "ok" else "skip"
    return (f'<div class="chip"><span class="chip-name"><span class="dot {cls}"></span>{esc(label)}</span>'
            f'<span class="chip-detail">{esc(detail)}</span></div>')


def render():
    health = machine_health()
    events, threads = bus_summary()
    work = autonomous_work()
    total, active, stale = claims_health()
    canon = canon_rows()
    dname, dmode, dverdict, nseeds, last_seed = dream_meta()
    reg_name, reg_body = latest_report("regression-latest.md")
    wd_name, wd_body = latest_report("watchdog-*.md")
    gen = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    thread_rows = "".join(
        f"<tr><td>{esc(tid[:40])}</td><td>{t['corr']}x</td><td>{len(t['witnesses'])}</td>"
        f"<td class='muted'>{esc(t['line'][:110])}</td></tr>"
        for tid, t in sorted(threads.items(), key=lambda kv: (-kv[1]["corr"], -len(kv[1]["witnesses"])))) \
        or "<tr><td colspan=4 class='muted'>bus quiet</td></tr>"

    work_rows = "".join(
        f"<tr><td class='muted'>{esc(str(r.get('ts',''))[5:16].replace('T',' '))}</td>"
        f"<td>{esc(r.get('kind') or r.get('tool',''))}</td>"
        f"<td class='mono'>{esc(r.get('recipe_id') or '')}</td>"
        f"<td class='muted'>{esc((r.get('command') or r.get('tool') or '')[:80])}</td></tr>"
        for r in work) or "<tr><td colspan=4 class='muted'>no autonomous work in 24h</td></tr>"

    event_rows = "".join(
        f"<tr><td class='muted'>{esc(str(e.get('ts',''))[5:16].replace('T',' '))}</td>"
        f"<td>{esc(e.get('_outbox',''))}</td><td><span class='badge {esc(e.get('kind',''))}'>{esc(e.get('kind',''))}</span></td>"
        f"<td class='muted'>{esc(e.get('line','')[:120])}</td></tr>"
        for e in events[:15]) or "<tr><td colspan=4 class='muted'>bus quiet</td></tr>"

    canon_html = "".join(
        f"<tr><td class='mono'>{esc(c.get('recipe_id',''))}</td><td>{esc(c.get('signature',''))}</td>"
        f"<td><span class='tag tag-{esc(c.get('status',''))}'>{esc(c.get('status',''))}</span></td>"
        f"<td class='muted'>{esc(c.get('line','')[:90])}</td></tr>"
        for c in canon) or "<tr><td colspan=4 class='muted'>canon empty</td></tr>"

    def excerpt(body, n=1200):
        return esc(body[:n]) if body else "(none)"

    stat = lambda label, value, sub="": f"""
      <div class="stat"><div class="stat-v">{value}</div><div class="stat-l">{label}</div><div class="stat-s">{sub}</div></div>"""

    pulses_24h = sum(1 for e in events)
    agents_active = len({e.get('_outbox') for e in events})
    p1_count = wd_body.count('**P1') or ('P1' in wd_body and 1 or 0)
    open_canon = sum(1 for c in canon if c.get('status') != 'tested')
    coverage = f"{100 - round(100 * open_canon / max(1, len(canon)))}%" if canon else "n/a"

    queue_lines = [l for l in attention_queue().splitlines() if l.strip() and not l.strip().startswith('#')]
    queue_cards = "".join(
        f'<div class="qcard"><div class="qnum">{i+1}</div><div class="qbody">{esc(l.lstrip("-0123456789. )"))}</div></div>'
        for i, l in enumerate(queue_lines[:7])) or '<div class="qcard"><div class="qbody muted">quiet — nothing attended</div></div>'

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Harness — Agent Network Dashboard</title>
<style>
:root {{
  --teal:#108291; --turf:#67EADD; --slate:#373D47;
  --bg:#0A1018; --card:#101826; --card2:#15202F; --line:#1F2E42;
  --text:#E3EDF7; --muted:#7E93AC; --ok:#3DDC97; --warn:#FFC24B; --bad:#FF6B6B;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--text);
  font:14px/1.55 -apple-system,'SF Pro Text','Segoe UI',system-ui,sans-serif; }}
header {{ padding:26px 40px 22px; background:linear-gradient(100deg,#0E4A54 0%,var(--teal) 55%,#0C6E79 100%);
  border-bottom:1px solid var(--line); position:relative; overflow:hidden; }}
header::after {{ content:""; position:absolute; inset:0;
  background:radial-gradient(600px 200px at 85% -40%, rgba(103,234,221,.28), transparent 60%); pointer-events:none; }}
.brand {{ display:flex; align-items:baseline; gap:14px; }}
.wordmark {{ font-weight:800; font-size:22px; color:#fff; letter-spacing:.5px; }}
.wordmark b {{ color:var(--turf); font-weight:800; }}
.tagline {{ color:#BFE6EA; font-size:12.5px; letter-spacing:.3px; }}
.hmeta {{ margin-top:10px; display:flex; gap:10px; align-items:center; color:#CDEDF0; font-size:12px; }}
.mode-pill {{ background:rgba(255,255,255,.12); border:1px solid rgba(255,255,255,.25);
  color:#fff; padding:2px 12px; border-radius:99px; font-weight:700; font-size:11px; letter-spacing:.8px; text-transform:uppercase; }}
main {{ max-width:1360px; margin:0 auto; padding:26px 40px 70px; }}
.stats {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:14px; margin-top:-2px; }}
.stat {{ background:linear-gradient(180deg,var(--card2),var(--card)); border:1px solid var(--line);
  border-radius:14px; padding:16px 18px 14px; }}
.stat-v {{ font-size:30px; font-weight:800; color:#fff; letter-spacing:-.5px; }}
.stat-l {{ font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:1px; color:var(--turf); margin-top:2px; }}
.stat-s {{ font-size:11px; color:var(--muted); margin-top:2px; }}
h2 {{ font-size:12px; font-weight:800; text-transform:uppercase; letter-spacing:1.6px; color:var(--turf);
  margin:34px 0 12px; display:flex; align-items:center; gap:10px; }}
h2::after {{ content:""; flex:1; height:1px; background:var(--line); }}
.card {{ background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px 18px; }}
.grid2 {{ display:grid; grid-template-columns:1.15fr 1fr; gap:16px; }}
.grid3 {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px; }}
@media (max-width: 900px) {{ .grid2 {{ grid-template-columns:1fr; }} }}
.qcard {{ display:flex; gap:12px; align-items:flex-start; background:var(--card2);
  border:1px solid var(--line); border-radius:10px; padding:10px 14px; margin-bottom:8px; }}
.qnum {{ flex:none; width:24px; height:24px; border-radius:50%; background:var(--teal); color:#fff;
  font-weight:800; font-size:12px; display:flex; align-items:center; justify-content:center; }}
.qbody {{ font-size:13px; }}
.chips {{ display:flex; flex-wrap:wrap; gap:10px; }}
.chip {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 14px; min-width:150px; }}
.chip-name {{ font-weight:700; font-size:13px; display:flex; align-items:center; gap:7px; }}
.dot {{ width:8px; height:8px; border-radius:50%; display:inline-block; }}
.dot.ok {{ background:var(--ok); box-shadow:0 0 8px rgba(61,220,151,.7); }}
.dot.skip {{ background:var(--warn); box-shadow:0 0 8px rgba(255,194,75,.6); }}
.chip-detail {{ color:var(--muted); font-size:11px; margin-top:2px; }}
table {{ width:100%; border-collapse:collapse; font-size:12.5px; }}
th {{ color:var(--muted); font-size:10.5px; font-weight:700; text-transform:uppercase; letter-spacing:1px;
  text-align:left; padding:4px 8px; }}
td {{ padding:7px 8px; border-bottom:1px solid var(--line); vertical-align:top; }}
tr:last-child td {{ border-bottom:none; }}
tr:hover td {{ background:rgba(103,234,221,.03); }}
.muted {{ color:var(--muted); }}
.mono {{ font-family:ui-monospace,'SF Mono',Menlo,monospace; font-size:12px; }}
.badge {{ display:inline-block; padding:1px 9px; border-radius:99px; font-size:10.5px; font-weight:700; }}
.badge.finding {{ background:#123c33; color:var(--ok); }}
.badge.verify {{ background:#123044; color:#7CC7F5; }}
.badge.handoff {{ background:#3a2f12; color:var(--warn); }}
.badge.open {{ background:#3a2f12; color:var(--warn); }}
.badge.fixed {{ background:#123c33; color:var(--ok); }}
.badge.tested {{ background:#123044; color:#7CC7F5; }}
.verdict {{ font-size:14.5px; line-height:1.6; color:#EAF3FA; border-left:3px solid var(--turf);
  padding:6px 0 6px 16px; margin:4px 0 10px; }}
.seed {{ font-style:italic; color:#9FB4C8; border-left:3px solid var(--line); padding:4px 0 4px 16px; }}
pre {{ white-space:pre-wrap; font:11.5px/1.55 ui-monospace,Menlo,monospace; color:#B9C9DB; margin:0;
  max-height:340px; overflow:auto; }}
footer {{ color:var(--muted); font-size:11px; padding:26px 40px; text-align:center; }}
</style></head><body>
<header>
  <div class="brand">
    <div class="wordmark">workato<b>&nbsp;|&nbsp;harness</b></div>
    <div class="tagline">agent network, live</div>
  </div>
  <div class="hmeta">
    <span class="mode-pill">{esc(dmode or 'report')}</span>
    <span>generated {gen}</span>
    <span>·</span><span>every figure below is machine-collected and evidence-cited</span>
  </div>
</header>
<main>

<div class="stats">
  {stat("attention items", len(queue_lines) or 0, "cortex queue, cap 7")}
  {stat("bus events 24h", pulses_24h, f"{agents_active} agents speaking")}
  {stat("autonomous actions", len(work), "build ledger, 24h")}
  {stat("claims", active, f"{total} total · {stale} stale")}
  {stat("canon coverage", coverage, f"{len(canon)} bugs canonized")}
  {stat("seeds planted", nseeds, "vision stream")}
</div>

<h2>Machine health — 24h</h2>
<div class="chips">{''.join(chip(j, s, d) for j, s, d in health)}</div>

<h2>Attention queue</h2>
<div>{queue_cards}</div>

<div class="grid2">
  <div>
    <h2>Gossip bus — 24h</h2>
    <div class="card"><table><tr><th>when</th><th>agent</th><th>kind</th><th>finding</th></tr>{event_rows}</table></div>
  </div>
  <div>
    <h2>Threads by corroboration</h2>
    <div class="card"><table><tr><th>thread</th><th>corr</th><th>witnesses</th><th>what</th></tr>{thread_rows}</table></div>
  </div>
</div>

<h2>Autonomous work — build ledger, 24h</h2>
<div class="card"><table><tr><th>when</th><th>kind</th><th>recipe</th><th>what</th></tr>{work_rows}</table></div>

<div class="grid2">
  <div>
    <h2>Dream — latest ({esc(dname)})</h2>
    <div class="card">
      <div class="verdict">{esc(dverdict) or 'no verdict yet'}</div>
      <div class="muted" style="font-size:11px; margin-bottom:6px">latest vision seed</div>
      <div class="seed">{esc(last_seed) or '(none yet)'}</div>
    </div>
  </div>
  <div>
    <h2>Regression canon</h2>
    <div class="card"><table><tr><th>recipe</th><th>signature</th><th>status</th><th>line</th></tr>{canon_html}</table></div>
  </div>
</div>

<div class="grid3">
  <div><h2>Regression — latest</h2><div class="card"><pre>{excerpt(reg_body)}</pre></div></div>
  <div><h2>Watchdog — latest</h2><div class="card"><pre>{excerpt(wd_body)}</pre></div></div>
</div>

</main>
<footer>agentic harness · generated by brain-dashboard.py · the machines wrote this page</footer>
</body></html>"""


def main():
    os.makedirs(K, exist_ok=True)
    html_out = render()
    with open(OUT, "w") as fh:
        fh.write(html_out)
    print(OUT)
    if "--open" in __import__("sys").argv:
        subprocess.run(["open", OUT])


if __name__ == "__main__":
    main()
