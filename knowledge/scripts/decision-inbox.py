#!/usr/bin/env python3
"""decision-inbox.py — ONE ranked, budgeted decision surface.

The harness produces findings (triage, proposals, cortex attention,
harness-health) faster than any human consumes them, across four separate
files. This collapses them into a single ranked list with a daily budget, and
routes the harness's own meta-work OUT of Josh's way:

  lane work   — real prod/project work; ranked, top BUDGET shown "today",
                the rest deferred (this is a VIEW; queue status is untouched).
  lane auto   — ticket triage / investigation / technical-plan work that the
                agents now do autonomously (see jira-autotriage skill). NOT
                surfaced. Counted only.
  lane meta   — findings about the harness itself (tooling, ledgers, fleet).
                Safe ones (no prod, no customer, reversible) are auto-drained
                to harness-fix/queue.jsonl instead of becoming Josh's cards;
                unsafe ones surface as work.

Zero-LLM. Outputs:
  ~/.claude/knowledge/now/decision-inbox.md
  ~/.claude/knowledge/now/decision-inbox.json
"""
import datetime as dt
import json
import math
import os
import re
import sys
from pathlib import Path
from atomic_io import atomic_append

HOME = Path(os.path.expanduser("~"))
K = HOME / ".claude" / "knowledge"
TRIAGE = K / "triage" / "queue.jsonl"
PROPOSALS = K / "dreams" / "proposals"
ATTENTION = K / "cortex" / "attention-queue.md"
HARNESS_FIX = K / "harness-fix" / "queue.jsonl"
NOW = K / "now"
HEARTBEAT = K / "garden-reports" / "heartbeat.jsonl"
OUT_MD = NOW / "decision-inbox.md"
OUT_JSON = NOW / "decision-inbox.json"

BUDGET = int(os.environ.get("DECISION_BUDGET", "5"))

# a finding about the harness's own tooling (not prod, not a project)
META_PATTERNS = [
    "proposal-pipeline", "workato-health", "dreamer", "heartbeat", "dispatch",
    "build-ledger", "ledger", "fleet", "brain-guard", "cortex", "gym", "hook",
    "plist", "harness", "triage queue", "value-ledger", "dedupe", "duplicate card",
]
# meta that must NOT be auto-drained — needs a human (prod / outward / destructive)
UNSAFE_PATTERNS = ["prod", "hotfix", "customer", "delete", "destroy", "outward",
                   "promotion", "rollback"]
# ticket triage/investigation/planning is now a standing autonomous grant, so
# the skill files only authority items — the auto lane is driven by an explicit
# lane:"auto" field when a source wants to file a non-decision informational row.


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_jsonl(path):
    if not path.exists():
        return
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def hay(item):
    return " ".join(str(item.get(k, "")) for k in ("slug", "title", "work", "evidence", "source", "name", "kind")).lower()


def classify(it):
    """Lane by ORIGIN first — keyword soup misroutes real work (a prod incident
    that merely mentions 'ledger' is still work)."""
    if it.get("lane") == "auto":
        return "auto"                            # explicit, non-decision informational
    o = it.get("origin")
    if o == "harness-fix":
        return "meta-safe"                       # already the meta lane
    if o in ("proposal", "attention"):
        return "work"                            # decisions and cortex-ranked work
    if it.get("kind") == "hygiene":
        h = hay(it)
        return "meta-unsafe" if any(p in h for p in UNSAFE_PATTERNS) else "meta-safe"
    return "work"


def gather():
    items = []

    for r in read_jsonl(TRIAGE):
        if str(r.get("status", "")) != "open":
            continue
        items.append({
            "origin": "triage", "id": r.get("slug", ""),
            "title": r.get("title", ""), "kind": r.get("kind", ""),
            "source": r.get("source", ""), "urgency": r.get("urgency", ""),
            "evidence": r.get("evidence", ""), "work": r.get("work", ""),
            "points": r.get("points"), "ts": str(r.get("ts", ""))[:10],
            "jira": r.get("jira", ""),
        })

    if PROPOSALS.exists():
        for f in sorted(PROPOSALS.glob("*.md")):
            head = f.read_text(errors="replace")[:600]
            status = re.search(r"^status:\s*(\S+)", head, re.M)
            kind = re.search(r"^kind:\s*(\S+)", head, re.M)
            risk = re.search(r"^risk:\s*(\S+)", head, re.M)
            st = status.group(1) if status else "incubating"
            if st in ("built", "rejected", "declined"):
                continue
            name = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", f.stem).replace("-", " ")
            items.append({
                "origin": "proposal", "id": name, "title": name,
                "kind": (kind.group(1) if kind else "proposal"),
                "source": "dreamer", "urgency": "",
                "evidence": f"dreams/proposals/{f.name}",
                "work": f"decide proposal ({risk.group(1) if risk else '?'} risk)",
                "ts": f.name[:10],
            })

    if ATTENTION.exists():
        for m in re.finditer(r"^\d+\.\s+\*\*(.+?)\*\*\s*(.*)$", ATTENTION.read_text(errors="replace"), re.M):
            title = m.group(1).strip()
            rest = re.sub(r"\s+", " ", m.group(2)).strip()
            items.append({
                "origin": "attention", "id": title[:60], "title": title,
                "kind": "attention", "source": "cortex",
                "urgency": "high" if "prod" in title.lower() else "medium",
                "evidence": rest[:240], "work": "cortex attention item",
                "ts": "",
            })

    # harness-fix lane: append-only, so last status per slug wins
    latest = {}
    for r in read_jsonl(HARNESS_FIX):
        if r.get("slug"):
            latest[r["slug"]] = r
    for r in latest.values():
        if str(r.get("status", "")) != "open":
            continue
        items.append({
            "origin": "harness-fix", "id": r.get("slug", ""),
            "title": r.get("title", ""), "kind": "hygiene",
            "source": r.get("source", "harness-health"), "urgency": "low",
            "evidence": r.get("evidence", ""), "work": r.get("work", ""),
            "ts": str(r.get("ts", ""))[:10],
        })

    for it in items:
        it["lane"] = classify(it)
    return items


def drain_meta(meta_safe):
    if not meta_safe:
        return 0
    HARNESS_FIX.parent.mkdir(parents=True, exist_ok=True)
    seen = {r.get("slug") for r in read_jsonl(HARNESS_FIX) if r.get("status") == "open"}
    n = 0
    new_rows = []
    for it in meta_safe:
        slug = it["id"] or it["title"][:60]
        if slug in seen:
            continue
        seen.add(slug)
        new_rows.append({
            "ts": now_iso(), "slug": slug, "title": it["title"],
            "work": it["work"], "evidence": it["evidence"],
            "source": "decision-inbox", "status": "open",
        })
        n += 1
    if new_rows:
        atomic_append(HARNESS_FIX, new_rows)
    return n


def rank_key(it):
    urg = {"high": 0, "medium": 1, "low": 2, "": 3}.get(str(it.get("urgency", "")), 3)
    prod = 0 if "prod" in hay(it) else 1
    ts = it.get("ts") or "9999"
    return (urg, prod, ts)


# ----------------------------------------------------------- #8 SHADOW RANK
# Verdict economy (harness-next10 review 2026-10-11, proposal #8). SHADOW
# MODE ONLY: compute a precision x surprise ordering BESIDE the live
# urgency-then-age one and log both orderings to
# garden-reports/inbox-ranking-<date>.jsonl. The presented order (the
# today/deferred slices below) is UNCHANGED — urgency-then-age stays what
# Josh sees until the logged data shows the new key wins over time.
#
#   precision(source) = accepted+built / total outcomes for that source,
#                       from the trailing PRECISION_WINDOW rows of each
#                       outcome ledger (triage-outcomes + proposal-outcomes).
#                       A source with no outcome rows gets the neutral prior
#                       PRECISION_PRIOR (0.5) and is thin-sample by
#                       definition.
#   surprise(item)    = 1/log2(2 + occurrences), where occurrences = rows in
#                       the trailing SURPRISE_DAYS days that share the item's
#                       source AND slug-prefix family. Fewer recent
#                       similar failures = more surprising = higher weight.
#                       Similarity is deliberately simple (see slug_family).
#   shadow score      = precision * surprise, ranked descending.

GOOD_ACTIONS = {"accepted", "built"}     # a verdict that ended in real work
PRECISION_WINDOW = 20                    # trailing rows per outcome ledger
SURPRISE_DAYS = 14
PRECISION_PRIOR = 0.5
OUTCOME_LEDGERS = [
    K / "garden-reports" / "triage-outcomes.jsonl",
    K / "garden-reports" / "proposal-outcomes.jsonl",
]
RANK_LOG = K / "garden-reports" / (
    "inbox-ranking-" + dt.date.today().isoformat() + ".jsonl")


def slug_family(s):
    """Documented similarity: lowercase, split on non-letters (digits and
    separators act as boundaries — ids, dates and recipe numbers vanish),
    keep the first two remaining word tokens. E.g.
    'recipe-health-82272892-new-failures' -> ('recipe', 'health');
    'uat-sweep-82862205' -> ('uat', 'sweep'). Two findings are 'similar'
    iff same source AND same family. Two tokens is enough to separate
    'recipe-health' from 'uat-sweep' without overfitting to slugs."""
    toks = [t for t in re.split(r"[^a-z]+", str(s).lower()) if t]
    return tuple(toks[:2]) or ("<none>",)


def row_source(r):
    """Producer of an outcome row. proposal-outcomes rows carry no source —
    the dreamer proposed them, so their producer is 'dreamer'."""
    if r.get("source"):
        return str(r["source"])
    if "proposal" in r:
        return "dreamer"
    return "?"


def row_slug(r):
    return r.get("slug") or r.get("proposal") or ""


def outcome_rows():
    rows = []
    for led in OUTCOME_LEDGERS:
        rows.extend(list(read_jsonl(led))[-PRECISION_WINDOW:])
    return rows


def precision_table(rows):
    """{source: {good, n, precision}} — precision = good/n, thin n<5."""
    agg = {}
    for r in rows:
        a = agg.setdefault(row_source(r), {"good": 0, "n": 0})
        a["n"] += 1
        if str(r.get("action", "")).lower() in GOOD_ACTIONS:
            a["good"] += 1
    for a in agg.values():
        a["precision"] = (a["good"] / a["n"]) if a["n"] else PRECISION_PRIOR
    return agg


def surprise(item, rows14):
    fam = slug_family(item["id"])
    occ = sum(1 for r in rows14
              if row_source(r) == item["source"]
              and slug_family(row_slug(r)) == fam)
    return 1.0 / math.log2(2 + occ)


def shadow_rank(work_items):
    """Returns (per-item {precision, surprise}, shadow-ordered item list).
    Purely additive — nothing here feeds the presented slices."""
    rows = outcome_rows()
    ptable = precision_table(rows)
    cutoff = (dt.date.today() - dt.timedelta(days=SURPRISE_DAYS)).isoformat()
    rows14 = [r for r in rows if str(r.get("date", ""))[:10] >= cutoff]
    scored = []
    for it in work_items:
        src = ptable.get(it["source"], {"precision": PRECISION_PRIOR, "n": 0})
        sup = surprise(it, rows14)
        scored.append((it, src["precision"], src.get("n", 0), sup))
    order = sorted(range(len(scored)),
                   key=lambda i: (-(scored[i][1] * scored[i][3]),
                                  scored[i][0].get("ts") or "9999"))
    rank_map = {idx: r + 1 for r, idx in enumerate(order)}
    return scored, rank_map, ptable


def log_shadow_ranking(scored, rank_map):
    out_rows = []
    for i, (it, p, n, sup) in enumerate(scored):
        out_rows.append({
            "ts": now_iso(), "item": f"{it['origin']}:{it['id']}",
            "urgency_rank": i + 1, "precision_surprise_rank": rank_map[i],
            "precision": round(p, 4), "surprise": round(sup, 4),
        })
    if out_rows:
        atomic_append(RANK_LOG, out_rows)
    return len(out_rows)


def main():
    items = gather()
    work = sorted([i for i in items if i["lane"] == "work"], key=rank_key)

    # #8 shadow: score + log both orderings. NEVER re-sorts `work` itself.
    try:
        scored, rank_map, ptable = shadow_rank(work)
        logged = log_shadow_ranking(scored, rank_map)
    except Exception as e:                       # shadow must never break the inbox
        scored, rank_map, ptable, logged = [], {}, {}, 0
        print(f"  shadow-ranking skipped: {e!r}", file=sys.stderr)

    meta_safe = [i for i in items if i["lane"] == "meta-safe"]
    meta_unsafe = [i for i in items if i["lane"] == "meta-unsafe"]
    auto = [i for i in items if i["lane"] == "auto"]
    drained = drain_meta(meta_safe)

    today = work[:BUDGET]
    deferred = work[BUDGET:]

    NOW.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": now_iso(), "budget": BUDGET,
        "today": today, "deferred_count": len(deferred),
        "deferred": deferred,
        "auto_handled": len(auto), "meta_drained": drained,
        "meta_unsafe": meta_unsafe,
    }
    OUT_JSON.write_text(json.dumps(payload, indent=1))

    L = [f"# Decision inbox — {now_iso()}", ""]
    L.append(f"**{len(today)} to decide today** (budget {BUDGET}) · "
             f"{len(deferred)} deferred · {len(auto)} handled autonomously · "
             f"{len(meta_safe)} harness-meta in the auto lane "
             f"({drained} newly filed this run).")
    L.append("")
    L.append("## Today (ranked)")
    L.append("")
    if not today:
        L.append("_Nothing needs a decision. Queue is clear._")
    for i, it in enumerate(today, 1):
        urg = it.get("urgency") or "-"
        pts = f" · {it['points']}pt" if it.get("points") else ""
        L.append(f"{i}. **[{it['origin']} · {it['kind']} · {urg}{pts}] {it['title']}**")
        if it.get("work"):
            L.append(f"   - do: {it['work']}")
        if it.get("evidence"):
            L.append(f"   - evidence: {str(it['evidence'])[:200]}")
        L.append(f"   - id: `{it['id']}`")
    L.append("")
    if meta_unsafe:
        L.append(f"## Harness-meta needing a human ({len(meta_unsafe)})")
        for it in meta_unsafe:
            L.append(f"- {it['title']}  (`{it['id']}`)")
        L.append("")
    L.append(f"## Deferred ({len(deferred)}) — not shown, oldest first, rolls "
             "forward as the budget frees")
    L.append("")
    for it in deferred[:20]:
        L.append(f"- [{it['origin']}] {it['title']}  (`{it['id']}`)")
    if len(deferred) > 20:
        L.append(f"- ...and {len(deferred) - 20} more")
    L.append("")
    if meta_safe:
        L.append(f"## Harness-meta in the auto lane ({len(meta_safe)}) — worked "
                 "without you; see harness-fix/queue.jsonl")
        L.append("")
        for it in meta_safe:
            L.append(f"- {it['title']}  (`{it['id']}`)")
    OUT_MD.write_text("\n".join(L) + "\n")

    atomic_append(HEARTBEAT, {"ts": now_iso(), "job": "decision-inbox"})

    print(f"decision-inbox: {len(today)} today, {len(deferred)} deferred, "
          f"{len(auto)} auto, {drained} meta drained, {len(meta_unsafe)} meta-unsafe")
    print(f"  -> {OUT_MD}")
    if scored:
        print(f"  shadow (#8): {logged} rows -> {RANK_LOG}")
        print("  precision by producer (trailing 20 rows/ledger, "
              f"good=accepted+built; n<5 = THIN):")
        for src in sorted(ptable, key=lambda s: -ptable[s]["precision"]):
            a = ptable[src]
            thin = " THIN" if a["n"] < 5 else ""
            print(f"    {src:22s} precision={a['precision']:.2f} "
                  f"({a['good']}/{a['n']}){thin}")
        movers = [i for i in range(len(scored))
                  if rank_map[i] != i + 1]
        if movers:
            print(f"  items that would move under precision x surprise: "
                  f"{len(movers)}/{len(scored)}")
            for i in sorted(movers, key=lambda i: rank_map[i])[:10]:
                it, p, n, sup = scored[i]
                print(f"    #{i + 1} -> #{rank_map[i]} "
                      f"(p={p:.2f}{'/THIN' if n < 5 else ''} "
                      f"s={sup:.2f}) {it['origin']}:{it['id'][:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
