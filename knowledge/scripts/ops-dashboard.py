#!/usr/bin/env python3
"""ops-dashboard.py — generates the self-contained ops-visibility dashboard.

  generate   Reads ops-visibility/records-*.jsonl + diagnoses.jsonl + config,
             writes ops-dashboard.html (all CSS/JS inline, embedded JSON via a
             <script> tag, no external resources). Buttons POST to the
             /api/* endpoints on 127.0.0.1:8771; on fetch failure shows a
             "server down" banner (copy-prompt fallback still works).

Stdlib only, Python 3.9+.
"""

import glob
import json
import os
import sys
from datetime import datetime, timezone

KNOWLEDGE = os.path.expanduser("~/.claude/knowledge")
OPS_DIR = os.path.join(KNOWLEDGE, "ops-visibility")
OUTPUT_PATH = os.path.join(OPS_DIR, "ops-dashboard.html")
API_BASE = "http://127.0.0.1:8771"


def read_jsonl(pattern):
    rows = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict):
                        rows.append(rec)
        except OSError:
            continue
    return rows


def read_json(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def render_card(rec):
    return """
    <div class="card" id="card-__SIG__">
      <div class="card-head">
        <span class="badge __ENVCLASS__">__ENV__</span>
        <a class="recipe" href="https://app.workato.com/recipes/__RID__" target="_blank" rel="noopener">__NAME__</a>
        __SWALBADGE__
        __JIRABADGE__
        <span class="chip chip-__ST__">__ST__</span>
        __CAPTURED__
      </div>
      <div class="error">__ERROR__</div>
      <div class="meta">
        <a href="__JOBURL__" target="_blank" rel="noopener">job __JID__</a>
        &middot; count <b>__COUNT__</b>
        &middot; first <b>__FIRST__</b>
        &middot; last <b>__LAST__</b>
      </div>
      __DIAG__
      <div class="actions">
        <button onclick="doTriage('__SIG__')">Send to triage</button>
        <button onclick="doAutopsy('__SIG__')">Request autopsy</button>
        <button onclick="doRefresh()">Refresh</button>
        <a class="btn" href="__JOBURL__" target="_blank" rel="noopener">Open job</a>
        <button class="btn" onclick="copyPrompt('__SIG__')">Copy investigate prompt</button>
      </div>
      <div class="result" id="res-__SIG__"></div>
    </div>"""
    # placeholders substituted below with replace (str.format braces conflict with JS)


def build_html(records, diagnoses, config):
    diag_by_sig = {}
    for d in diagnoses:
        sig = d.get("sig")
        if sig and (sig not in diag_by_sig or (d.get("diagnosed_ts") or "") >= (diag_by_sig[sig].get("diagnosed_ts") or "")):
            diag_by_sig[sig] = d

    open_records = [r for r in records if not r.get("resolved")]
    for r in open_records:
        r["_diag"] = diag_by_sig.get(r.get("sig"))
        if r.get("_diag") and r.get("status") == "open":
            r["status"] = "diagnosed"
            if r.get("diagnosis") is None:
                r["diagnosis"] = r["_diag"].get("root_cause")

    open_records.sort(key=lambda r: (
        0 if r.get("env") == "prod" else 1,
        {"open": 0, "sent-to-triage": 1, "diagnosed": 2, "jira-filed": 3}.get(r.get("status"), 4),
        -(r.get("count") or 0),
        r.get("sig") or "",
    ))

    counts = {
        "open": sum(1 for r in open_records if r.get("status") == "open"),
        "sent-to-triage": sum(1 for r in open_records if r.get("status") == "sent-to-triage"),
        "diagnosed": sum(1 for r in open_records if r.get("status") == "diagnosed"),
        "swallowed": sum(1 for r in open_records if r.get("swallowed")),
    }

    cards = []
    for r in open_records:
        env = r.get("env") or "?"
        st = r.get("status") or "open"
        card = render_card(r)
        card = (card
                .replace("__SIG__", r.get("sig") or "")
                .replace("__ENV__", env)
                .replace("__ENVCLASS__", "env-prod" if env == "prod" else "env-dev")
                .replace("__NAME__", escape_html(r.get("recipe_name") or r.get("recipe_id") or ""))
                .replace("__RID__", r.get("recipe_id") or "")
                .replace("__SWALBADGE__", '<span class="badge badge-swallow">swallowed</span>' if r.get("swallowed") else "")
                .replace("__JIRABADGE__", ('<a class="badge badge-jira" href="https://workato.atlassian.net/browse/%s" target="_blank" rel="noopener">%s</a>' % (r.get("jira_key"), r.get("jira_key"))) if r.get("jira_key") else "")
                .replace("__CAPTURED__", ('<div class="captured">captured by <a href="https://app.workato.com/recipes/%s">%s</a> — attributed to source recipe (Josh ruling 2026-10-09)</div>' % (r.get("captured_by_id"), escape_html(r.get("captured_by") or ""))) if r.get("captured_by") else "")
                .replace("__ST__", st)
                .replace("__ERROR__", escape_html((r.get("error") or "")[:300]))
                .replace("__JOBURL__", r.get("job_url") or "#")
                .replace("__JID__", escape_html(r.get("job_id") or ""))
                .replace("__COUNT__", str(r.get("count") or 1))
                .replace("__FIRST__", escape_html(r.get("first_seen") or ""))
                .replace("__LAST__", escape_html(r.get("last_seen") or "")))
        diag = r.get("_diag")
        if diag:
            diag_html = ('<div class="diag"><b>Diagnosis</b> (%s confidence): %s<br>'
                         '<b>Proposed fix:</b> %s</div>' % (
                             escape_html(str(diag.get("confidence") or "?")),
                             escape_html(str(diag.get("root_cause") or "")),
                             escape_html(str(diag.get("proposed_fix") or ""))))
            card = card.replace("__DIAG__", diag_html)
        else:
            card = card.replace("__DIAG__", "")
        cards.append(card)

    payload = json.dumps({
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "counts": counts,
        "records": [{k: v for k, v in r.items() if not k.startswith("_")} for r in open_records],
    }, ensure_ascii=False).replace("</", "<\\/")  # keep </script> out of embedded JSON

    html = TEMPLATE
    html = html.replace("/*__PAYLOAD__*/", payload)
    html = html.replace("/*__APIBASE__*/", json.dumps(API_BASE))
    html = html.replace("__CARDS__", "\n".join(cards) or '<div class="empty">No open failure or swallowed-error records. The pipeline is running; records land here as ticks find failures.</div>')
    html = html.replace("__COUNT_OPEN__", str(counts["open"]))
    html = html.replace("__COUNT_TRIAGE__", str(counts["sent-to-triage"]))
    html = html.replace("__COUNT_DIAG__", str(counts["diagnosed"]))
    html = html.replace("__COUNT_SWALLOW__", str(counts["swallowed"]))
    return html


def escape_html(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Workato Ops Visibility</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
         background: #0d1117; color: #c9d1d9; padding: 28px; max-width: 900px; margin: 0 auto; }
  h1 { font-size: 18px; font-weight: 600; color: #e6edf3; margin-bottom: 4px; }
  .sub { font-size: 12px; color: #7d8590; margin-bottom: 18px; }
  .banner { display: none; background: #2d1a1a; border: 1px solid #f85149; color: #ffa198;
            padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-bottom: 14px; }
  .banner code { background: #161b22; padding: 2px 6px; border-radius: 4px; color: #e6edf3; }
  .counts { display: flex; gap: 10px; margin-bottom: 20px; flex-wrap: wrap; }
  .stat { background: #161b22; border: 1px solid #21262d; border-radius: 8px;
          padding: 10px 16px; min-width: 110px; }
  .stat .n { font-size: 22px; font-weight: 700; color: #e6edf3; }
  .stat .l { font-size: 11px; color: #7d8590; text-transform: uppercase; letter-spacing: .05em; }
  .stat.sw .n { color: #d29922; }
  .card { background: #161b22; border: 1px solid #21262d; border-radius: 10px;
          padding: 14px 16px; margin-bottom: 12px; }
  .card-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
  .badge { font-size: 10px; font-weight: 700; text-transform: uppercase;
           letter-spacing: .06em; padding: 2px 8px; border-radius: 10px; }
  .env-prod { background: rgba(248,81,73,.15); color: #f85149; border: 1px solid rgba(248,81,73,.4); }
  .env-dev  { background: rgba(56,139,253,.15); color: #58a6ff; border: 1px solid rgba(56,139,253,.4); }
  .badge-swallow { background: rgba(210,153,34,.15); color: #d29922; border: 1px solid rgba(210,153,34,.4); }
  .badge-jira { background: rgba(56,139,253,.15); color: #539bf5; border: 1px solid rgba(56,139,253,.4); text-decoration: none; }
  .captured { font-size: 11px; color: #8b949e; margin-top: 6px; }
  .captured a { color: #8b949e; }
  .chip { font-size: 10px; padding: 2px 8px; border-radius: 10px; border: 1px solid #30363d;
          color: #7d8590; margin-left: auto; }
  .chip-open { color: #f85149; border-color: rgba(248,81,73,.4); }
  .chip-sent-to-triage { color: #d29922; border-color: rgba(210,153,34,.4); }
  .chip-diagnosed { color: #3fb950; border-color: rgba(63,185,80,.4); }
  .recipe { color: #e6edf3; font-weight: 600; font-size: 14px; text-decoration: none; }
  .recipe:hover { color: #58a6ff; }
  .error { font-size: 13px; color: #c9d1d9; background: #0d1117; border: 1px solid #21262d;
           border-radius: 6px; padding: 8px 10px; margin-bottom: 8px;
           font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
           white-space: pre-wrap; word-break: break-word; }
  .meta { font-size: 12px; color: #7d8590; margin-bottom: 10px; }
  .meta a { color: #58a6ff; text-decoration: none; }
  .meta b { color: #c9d1d9; }
  .diag { font-size: 12px; background: rgba(63,185,80,.08); border: 1px solid rgba(63,185,80,.25);
          border-radius: 6px; padding: 8px 10px; margin-bottom: 10px; color: #c9d1d9; }
  .actions { display: flex; gap: 8px; flex-wrap: wrap; }
  button, .btn { font-size: 12px; padding: 5px 12px; border-radius: 6px; cursor: pointer;
          border: 1px solid #30363d; background: #21262d; color: #c9d1d9; text-decoration: none;
          font-family: inherit; }
  button:hover, .btn:hover { background: #30363d; color: #e6edf3; }
  .result { font-size: 12px; color: #3fb950; margin-top: 8px; min-height: 0; }
  .empty { color: #7d8590; font-size: 14px; padding: 30px 0; text-align: center; }
</style>
</head>
<body>
  <h1>Workato Ops Visibility</h1>
  <div class="sub">failed &amp; swallowed-error jobs &middot; generated <span id="gen"></span> &middot; auto-refreshed every collection tick</div>
  <div class="banner" id="banner">Server down (127.0.0.1:8771 unreachable) &mdash; buttons are disabled.
    Use <b>Copy investigate prompt</b> and paste into a Claude session as the fallback.</div>
  <div class="counts">
    <div class="stat"><div class="n">__COUNT_OPEN__</div><div class="l">open</div></div>
    <div class="stat"><div class="n">__COUNT_TRIAGE__</div><div class="l">sent to triage</div></div>
    <div class="stat"><div class="n">__COUNT_DIAG__</div><div class="l">diagnosed</div></div>
    <div class="stat sw"><div class="n">__COUNT_SWALLOW__</div><div class="l">swallowed</div></div>
  </div>
  <div id="cards">
__CARDS__
  </div>
<script id="ops-payload" type="application/json">
/*__PAYLOAD__*/
</script>
<script>
var API = /*__APIBASE__*/ || "http://127.0.0.1:8771";
var payload = {};
try { payload = JSON.parse(document.getElementById("ops-payload").textContent); } catch (e) {}
document.getElementById("gen").textContent = payload.generated_at || "";
function setStatus(sig, msg, ok) {
  var el = document.getElementById("res-" + sig);
  if (el) { el.textContent = msg; el.style.color = ok ? "#3fb950" : "#f85149"; }
}
function markCard(sig, status) {
  var card = document.getElementById("card-" + sig);
  if (!card) return;
  var chip = card.querySelector(".chip");
  if (chip) { chip.textContent = status; chip.className = "chip chip-" + status; }
}
function post(path, body, sig, okMsg) {
  fetch(API + path, { method: "POST", headers: { "Content-Type": "application/json" },
                      body: JSON.stringify(body) })
    .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
    .then(function (d) {
      if (sig) { setStatus(sig, okMsg, true); markCard(sig, d.status || "sent-to-triage"); }
      else { setStatus("all", okMsg, true); }
    })
    .catch(function (e) {
      document.getElementById("banner").style.display = "block";
      if (sig) setStatus(sig, "failed: " + e.message + " — use the copy fallback", false);
      else setStatus("all", "refresh failed: " + e.message, false);
    });
}
function doTriage(sig) {
  var rec = (payload.records || []).find(function (r) { return r.sig === sig; });
  post("/api/triage", { sig: sig }, sig, "sent to triage queue");
  if (rec) rec.status = "sent-to-triage";
}
function doAutopsy(sig) { post("/api/autopsy", { sig: sig }, sig, "autopsy requested"); }
function doRefresh() { post("/api/refresh", {}); }
function copyPrompt(sig) {
  var rec = (payload.records || []).find(function (r) { return r.sig === sig; });
  if (!rec) return;
  var text = "Autopsy workato job " + rec.job_id + " on recipe " + rec.recipe_id +
             " (" + rec.env + ") — root cause, proposed diff, regression test.";
  function done() { setStatus(sig, "prompt copied to clipboard", true); }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(function () { fallbackCopy(text, done); });
  } else { fallbackCopy(text, done); }
}
function fallbackCopy(text, done) {
  var ta = document.createElement("textarea");
  ta.value = text; document.body.appendChild(ta); ta.select();
  try { document.execCommand("copy"); done(); } catch (e) {}
  document.body.removeChild(ta);
}
</script>
</body>
</html>
"""


def cmd_generate(_args):
    records = read_jsonl(os.path.join(OPS_DIR, "records-*.jsonl"))
    # dedup by sig, LATEST occurrence wins (day files carry history forward;
    # without this, stale prior-day copies render as duplicate cards)
    _latest = {}
    for rec in records:
        _latest[rec.get("sig") or json.dumps(rec, sort_keys=True)] = rec
    records = list(_latest.values())
    diagnoses = read_jsonl(os.path.join(OPS_DIR, "diagnoses.jsonl"))
    config = read_json(os.path.join(OPS_DIR, "config.json"), {}) or {}
    html = build_html(records, diagnoses, config)
    with open(OUTPUT_PATH, "w") as f:
        f.write(html)
    print("ops-dashboard: wrote %s (%d open record(s), %d diagnoses)"
          % (OUTPUT_PATH, len([r for r in records if not r.get("resolved")]), len(diagnoses)))
    return 0


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="ops-visibility dashboard generator")
    sub = parser.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="regenerate ops-dashboard.html")
    g.set_defaults(func=cmd_generate)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
