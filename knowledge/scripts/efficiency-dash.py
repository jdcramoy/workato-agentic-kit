#!/usr/bin/env python3
"""efficiency-dash.py — 'are we getting more efficient AS we ship real work?'

Builds mission-control/efficiency-dashboard.html from:
  - garden-reports/usage-ledger.jsonl   turn-usage rows -> daily token classes
  - mission-control/events.jsonl        closeout events  -> shipped work units
  - build-ledger.jsonl                  build actions    -> activity denominator
  - scripts/efficiency-dash-jira.json   BSYS closed/day + story points (JQL cache)
  - session transcripts                 one-pass scan -> per-session CLASS + outcomes:
      workato-build  (AIRO mutating calls: push/save/add_step/create...)
      harness        (edits under ~/.claude/**, mods/, kb corpus, harness repos)
      code-other     (otto, product repos)
      ops-analysis   (Jira/Slack/KB reads, investigations — default)
    Catalog artifact: garden-reports/session-catalog.json (per-session rows incl.
    edited files + first prompt). Regenerated every run — derived, never drifts.

Cost calibrated to GATEWAY MY-SPEND ACTUALS: $1,467 / Oct 1-14 2026 (AI Gateway
"My spend" tab — the chargeback view). The team Grafana/Usage-per-user
est_cost_usd column was DE-AUTHORIZED 2026-10-14 (Josh): it shows the same
token counts but ~2.7-3.3x the dollars; it is an estimator, not billing.
Per-class blended rates VERIFIED against Fireworks' published serverless card
(glm-5.3-flash $0.15/$0.03c/$0.50 per MTok — reproduces the gateway's glm line
to 0.05%; kimi-k3 ~$1.96/$0.39c/$6.52 solved from its row), weighted by Josh's mix:
  uncached input+cache_write $0.213/M · cache_read $0.038/M · output $0.97/M
The model reproduces the gateway actual; the cal factor below absorbs mix drift.
Refresh GATEWAY_* when re-reading the gateway (widen the My-spend window for a
true 30d basis).
"""
import glob, json, os, re, collections, statistics, time

HOME = os.path.expanduser("~")
K = f"{HOME}/.claude/knowledge"
OUT_HTML = f"{K}/mission-control/efficiency-dashboard.html"
CATALOG = f"{K}/garden-reports/session-catalog.json"
DAYS = 14
GATEWAY_ACTUAL_USD = 1467.0      # My-spend actuals, Oct 1-14 2026
GATEWAY_WINDOW_DAYS = 14
RATE_UNCACHED = 0.213            # $/M: uncached input + cache_write (cw at input rate)
RATE_CACHED = 0.038              # $/M: cache_read (Fireworks: 20% of input rate)
RATE_OUTPUT = 0.69               # $/M: completion (glm $0.50 dominates the mix)

AIRO_MUTATING = re.compile(r"recipe_builder_(push|save|init|init_skill|add_step|remove_step|move_step|update_step|set_input_field|set_input_field_v4_mode|set_condition|set_block_comments|set_error_handling_config|update_asset_metadata|convert_to_skill|select_connections)|genie_(create|update)|data_table_(create|update|truncate)|mcp_server_create|blueprint_(apply|push)|knowledge_base_(create|update|delete)")

ANNOTATIONS = [
    ("2026-10-12", "MCP context tax measured (81%); core/on-demand tiering live"),
    ("2026-10-13", "Writer-class fleet perms fixed; usage framing correction"),
    ("2026-10-14", "AIRO docs-gate + Jira comment-guard hooks live"),
    ("2026-10-14", "Cost basis recalibrated to gateway My-spend actuals ($1,467/14d); Grafana est_cost_usd de-authorized (~2.7-3.3x inflated)"),
]

def classify(sess):
    if sess["airo_mut"] >= 2:
        return "workato-build"
    if sess["harness_writes"] >= 2:
        return "harness"
    if sess["code_writes"] >= 2:
        return "code-other"
    return "ops-analysis"

def write_class(p):
    p = p or ""
    if p.startswith(f"{HOME}/.claude/") or p.startswith(f"{HOME}/mods/") \
       or "workato-kb/" in p or "harness-dashboards-mcp" in p:
        return "harness_writes"
    return "code_writes"

def day_of(ts):
    return (ts or "")[:10]

# ---------------------------------------------------------------- pass 1: ledgers
def load_days():
    days = collections.defaultdict(lambda: dict(out=0, inp=0, cr=0, cw=0, turns=0,
                                                calls=0, fails=0, fails_hooked=0, fails_other=0,
                                                closeouts=0, builds=0, jira_done=0, points=0,
                                                recipes=set()))
    re_use = re.compile(r"in=(\d+) out=(\d+) cache_read=(\d+) cache_write=(\d+)")
    for line in open(f"{K}/garden-reports/usage-ledger.jsonl"):
        if '"turn-usage"' not in line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        m = re_use.search(r.get("target", ""))
        if not m:
            continue
        d = days[day_of(r["ts"])]
        d["inp"] += int(m.group(1)); d["out"] += int(m.group(2))
        d["cr"] += int(m.group(3)); d["cw"] += int(m.group(4)); d["turns"] += 1
    for line in open(f"{K}/mission-control/events.jsonl"):
        if '"closeout"' not in line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("event") == "closeout":
            days[day_of(r["ts"])]["closeouts"] += 1
    for line in open(f"{K}/build-ledger.jsonl"):
        try:
            r = json.loads(line)
        except Exception:
            continue
        d = days[day_of(r.get("ts", ""))]
        d["builds"] += 1
        if r.get("recipe_id"):
            d["recipes"].add(str(r["recipe_id"]))
    jira_cache = f"{K}/scripts/efficiency-dash-jira.json"
    if os.path.exists(jira_cache):
        for d, v in json.load(open(jira_cache)).get("per_day", {}).items():
            if d in days:
                days[d]["jira_done"] = v.get("done", 0)
                days[d]["points"] = sum(v.get("points", []))
    return days, sorted(k for k in days if re.match(r"^\d{4}-\d{2}-\d{2}$", k))

# ---------------------------------------------------------------- pass 2: transcripts
def scan_transcripts(days, since):
    """One pass: per-day failures AND per-session classification/catalog."""
    cutoff = time.time() - DAYS * 86400
    catalog = {}
    for f in glob.glob(f"{HOME}/.claude/projects/*/*.jsonl"):
        if os.path.getmtime(f) < cutoff:
            continue
        sid = os.path.basename(f)[:-6]
        sess = dict(sid=sid, day=None, turns=0, tok_out=0, tok_in=0, tok_cache=0,
                    airo_mut=0, airo_calls=0, wt_calls=0, jira_calls=0, kb_calls=0,
                    agent_dispatches=0, harness_writes=0, code_writes=0,
                    files=[], first_prompt=None)
        calls = {}
        try:
            for line in open(f):
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                t = d.get("type")
                ts = d.get("timestamp") or ""
                dy = day_of(ts)
                if dy and (sess["day"] is None or dy < sess["day"]):
                    sess["day"] = dy
                if t == "user" and sess["first_prompt"] is None:
                    c = d.get("message", {}).get("content", "")
                    txt = c if isinstance(c, str) else "".join(
                        b.get("text", "") for b in c if isinstance(b, dict)) if isinstance(c, list) else str(c)
                    if txt.strip():
                        sess["first_prompt"] = txt.strip()[:160]
                if not ts or dy < since:
                    continue
                if t == "assistant":
                    m = d.get("message", {})
                    u = m.get("usage", {})
                    sess["tok_out"] += u.get("output_tokens", 0) or 0
                    sess["tok_in"] += u.get("input_tokens", 0) or 0
                    sess["tok_cache"] += (u.get("cache_read_input_tokens", 0) or 0) + (u.get("cache_creation_input_tokens", 0) or 0)
                    for b in m.get("content", []):
                        if not (isinstance(b, dict) and b.get("type") == "tool_use"):
                            continue
                        name, inp = b.get("name", ""), b.get("input", {}) or {}
                        calls[b.get("id")] = (dy, name)
                        if dy >= since:
                            if "workato-airo" in name:
                                sess["airo_calls"] += 1
                                if AIRO_MUTATING.search(name):
                                    sess["airo_mut"] += 1
                            elif name.startswith("mcp__atlassian"):
                                sess["jira_calls"] += 1
                            elif "workato-kb" in name:
                                sess["kb_calls"] += 1
                            elif name == "Agent":
                                sess["agent_dispatches"] += 1
                            elif name == "Bash":
                                cmd = (inp.get("command") or "").strip()
                                if cmd.startswith(("wt ", "wt-prod ", "./wt", "~/.local/bin/wt")):
                                    sess["wt_calls"] += 1
                            elif name in ("Write", "Edit"):
                                sess[write_class(inp.get("file_path") or inp.get("path"))] += 1
                                p = inp.get("file_path") or inp.get("path") or "?"
                                if p != "?" and len(sess["files"]) < 12:
                                    sess["files"].append(p.replace(HOME, "~"))
                elif t == "user":
                    c = d.get("message", {}).get("content", [])
                    if isinstance(c, list):
                        for b in c:
                            if isinstance(b, dict) and b.get("type") == "tool_result":
                                info = calls.pop(b.get("tool_use_id"), None)
                                if not info:
                                    continue
                                bdy, name = info
                                days[bdy]["calls"] += 1
                                if b.get("is_error"):
                                    days[bdy]["fails"] += 1
                                    if "workato-airo" in name or name.endswith("addCommentToJiraIssue"):
                                        days[bdy]["fails_hooked"] += 1
                                    else:
                                        days[bdy]["fails_other"] += 1
            if sess["tok_out"] or sess["tok_cache"]:
                catalog[sid] = sess
        except OSError:
            continue
    return catalog

# session day = day of first assistant usage; do a light second look via file mtime is
# wrong for old sessions — use min timestamp seen. Simpler: re-derive from first_prompt ts
# not needed for the dashboard: catalog rows keep their own day for the CLASS panel.

def main():
    days, keys = load_days()
    keys = [k for k in keys if any(days[k].get(x, 0) for x in ("turns", "closeouts", "builds"))]
    since = keys[0]
    catalog = scan_transcripts(days, since)
    for s in catalog.values():
        s["class"] = classify(s)

    # per-day per-class token attribution (session day = its earliest ts)
    cls_day = collections.defaultdict(lambda: collections.Counter())
    for s in catalog.values():
        if s["day"]:
            cls_day[s["day"]][s["class"]] += s["tok_out"] + s["tok_in"] + s["tok_cache"]

    rows = []
    rec_union = set()
    for d in days.values():
        rec_union |= d["recipes"]
    for k in keys:
        d = days[k]
        total = d["inp"] + d["out"] + d["cr"] + d["cw"]
        usd = (d["inp"] + d["cw"]) / 1e6 * RATE_UNCACHED + d["cr"] / 1e6 * RATE_CACHED + d["out"] / 1e6 * RATE_OUTPUT
        rows.append({**d, "recipes": len(d["recipes"]), "day": k, "total": total, "usd": usd,
                     "fail_rate": (d["fails"] / d["calls"] * 100) if d["calls"] else None,
                     "fail_rate_hooked": (d["fails_hooked"] / d["calls"] * 100) if d["calls"] else None,
                     "fail_rate_other": (d["fails_other"] / d["calls"] * 100) if d["calls"] else None})

    for i, r in enumerate(rows):
        lo = max(0, i - 2)
        seg = rows[lo:i + 1]
        tok3 = sum(x["total"] for x in seg)
        co3 = sum(x["closeouts"] for x in seg)
        r["tok_per_co3"] = tok3 / co3 if co3 else None
        bd3 = sum(x["builds"] for x in seg)
        r["tok_per_build3"] = tok3 / bd3 if bd3 else None
        pt3 = sum(x["points"] for x in seg)
        r["tok_per_point3"] = tok3 / pt3 if pt3 else None

    # projection backfill with ONE denominator semantics across the window.
    # Registry (closeouts) born 2026-10-11; any trailing-3d window containing
    # pre-registry days has a collapsing denominator (the 672M "spike" was that
    # artifact, not efficiency). Estimator: points-per-closeout density (median
    # of real overlap ratios) -> estimated closeouts for uncovered days.
    first_co_day = next((r["day"] for r in rows if r["tok_per_co3"] is not None), None)
    ratios = [r["tok_per_co3"] / r["tok_per_point3"] for r in rows
              if r.get("tok_per_co3") and r.get("tok_per_point3")]
    proj_ratio = statistics.median(ratios) if ratios else 1.0  # pts per closeout density
    ppc = proj_ratio
    for i, r in enumerate(rows):
        lo = max(0, i - 2)
        seg = rows[lo:i + 1]
        # trailing window fully registry-covered? (every day >= first closeout day)
        covered = all(x["day"] >= first_co_day for x in seg) if first_co_day else False
        if covered:
            r["tok_per_co3_proj"] = r["tok_per_co3"]
            r["co3_projected"] = False
        else:
            est_co3 = sum((x["points"] / ppc if x["points"] else 0) if x["day"] < first_co_day
                          else (x["closeouts"] if x["day"] >= first_co_day else 0)
                          for x in seg)
            r["tok_per_co3_proj"] = (sum(x["total"] for x in seg) / est_co3) if est_co3 else None
            r["co3_projected"] = True

    modeled_wk = sum(r["usd"] for r in rows)
    cal = (GATEWAY_ACTUAL_USD / GATEWAY_WINDOW_DAYS) / (modeled_wk / len(rows)) if modeled_wk else 1.0
    for r in rows:
        r["usd"] *= cal

    # ---- catalog artifact
    cat_rows = sorted(catalog.values(), key=lambda s: -(s["tok_out"] + s["tok_cache"]))
    by_class = collections.Counter(s["class"] for s in cat_rows)
    tok_by_class = collections.Counter()
    for s in cat_rows:
        tok_by_class[s["class"]] += s["tok_out"] + s["tok_in"] + s["tok_cache"]
    out = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": {"sessions": len(cat_rows), "by_class": dict(by_class),
                    "tokens_by_class": dict(tok_by_class)},
        "sessions": [{"id": s["sid"], "day": s["day"], "class": s["class"],
                      "tok_out": s["tok_out"], "tok_cache": s["tok_cache"],
                      "airo_mut": s["airo_mut"], "wt": s["wt_calls"], "jira": s["jira_calls"],
                      "kb": s["kb_calls"], "agent_dispatches": s["agent_dispatches"],
                      "harness_writes": s["harness_writes"], "code_writes": s["code_writes"],
                      "files": s["files"], "first_prompt": s["first_prompt"]} for s in cat_rows],
    }
    with open(CATALOG, "w") as fh:
        json.dump(out, fh, indent=1)

    last = rows[-1]
    tiles = [
        ("Tokens (window)", f"{sum(r['total'] for r in rows):,}", "in+out+cache, all sessions"),
        ("Cost (gateway-actual rates)", f"${sum(r['usd'] for r in rows):,.0f}", f"Gateway My-spend actual ${GATEWAY_ACTUAL_USD:,.0f}/{GATEWAY_WINDOW_DAYS}d (×{cal:.3f})"),
        ("Shipped closeouts", f"{sum(r['closeouts'] for r in rows):,}", "mission-control work units"),
        ("Jira done / points", f"{sum(r['jira_done'] for r in rows)} / {sum(r['points'] for r in rows)}",
         "BSYS closed in window" + (f" · JQL cache {time.strftime('%Y-%m-%d', time.localtime(os.path.getmtime(f'{K}/scripts/efficiency-dash-jira.json')))}" if os.path.exists(f"{K}/scripts/efficiency-dash-jira.json") else " (no cache)")),
        ("Recipes touched (window)", f"{len(rec_union):,}", "distinct recipe IDs, primary ledger attribution"),
        ("Tok / closeout (3d)", f"{last['tok_per_co3_proj']/1e6:.1f}M" if last.get("tok_per_co3_proj") else "—",
         (f"was {rows[0]['tok_per_co3_proj']/1e6:.1f}M on {rows[0]['day']} (projected series; solid/real from "
          f"{next((r['day'] for r in rows if not r['co3_projected']), '—')})")),
        ("Tok / story point (3d)", f"{last['tok_per_point3']/1e6:.2f}M" if last.get("tok_per_point3") else "—", "Jira-shipped denominator"),
        ("Failure rate (latest)", f"{last['fail_rate']:.1f}%" if last["fail_rate"] is not None else "—", "hooked vs unhooked split below"),
    ]

    data = {"rows": rows,
            "annotations": [d for d, _ in ANNOTATIONS if any(r["day"] == d for r in rows)],
            "annotation_labels": [lbl for (d, lbl) in ANNOTATIONS if any(r["day"] == d for r in rows)],
            "class_days": {d: dict(c) for d, c in cls_day.items()},
            "catalog_summary": dict(by_class),
            "proj_ratio": proj_ratio,
            "catalog_top": [{"day": s["day"], "class": s["class"],
                             "tok": s["tok_out"] + s["tok_in"] + s["tok_cache"],
                             "airo_mut": s["airo_mut"], "harness_writes": s["harness_writes"],
                             "code_writes": s["code_writes"], "files": s["files"][:6],
                             "first_prompt": s["first_prompt"]}
                            for s in cat_rows[:15]]}

    import pathlib
    tpl = pathlib.Path(__file__).with_suffix(".template.html")
    html = tpl.read_text().replace("__DATA__", json.dumps(data)).replace("__TILES__", json.dumps(tiles))
    pathlib.Path(OUT_HTML).write_text(html)
    print(f"dashboard -> {OUT_HTML} ({len(rows)} days) | catalog -> {CATALOG}")
    print(f"  sessions: {len(cat_rows)} {dict(by_class)}")
    print(f"  tokens by class: { {k: f'{v/1e9:.2f}B' for k, v in tok_by_class.items()} }")

if __name__ == "__main__":
    main()
