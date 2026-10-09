"""Nightly KB digest fan-out: per-agent briefs of what changed in the KB.

Runs right after the nightly sync (before the agent fleet wakes). For each
agent it writes ~/.claude/knowledge/kb-digests/<agent>.md containing:
  - the change surface (added/changed docs from last night's diff report)
  - agent-specific KB queries run live, top hits with URLs
Each agent SOP then tells the agent to read its digest, form an OPINION about
how the changes relate to ongoing work, and post 1-3 lines to its gossip-bus
outbox. Proposals remain the dreamer's job — opinions are corroboration fuel.

    python3 -m kb.digest
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from .common import DATA_ROOT
from .search import search, format_hits

DIGEST_DIR = Path.home() / ".claude/knowledge/kb-digests"

# sources where recency IS the signal; lens hits for these are re-ordered
# fresh-first (see _recency_key) before the top-3 is taken
RECENCY_SOURCES = {"changelog", "blog"}
LENS_K = 12  # oversampled, then recency-ordered + doc-deduped down to 3

# per-agent lens: what to query the KB for, and what an opinion means for them
AGENTS = {
    "harness-dreamer": {
        "queries": [
            ("new platform launches", "--source changelog", "new release OR launch OR generally available OR deprecated"),
            ("product strategy signals", "--source blog", "AI agents platform roadmap vision"),
        ],
        "note": "You synthesize proposals from the whole digest (Mandate B2).",
    },
    "workato-watchdog": {
        "queries": [
            ("monitoring/ops changes", "--source docs", "monitoring job failures error handling troubleshooting"),
            ("operational releases", "--source changelog", "API rate limits jobs errors deprecation"),
        ],
        "note": "Opinion: do these changes affect how we detect/monitor recipe health or platform ops?",
    },
    "estate-architect": {
        "queries": [
            ("architecture/lifecycle changes", "--source docs", "recipe lifecycle management environments deployment"),
            ("integration design", "--source eip", "message routing transformation pattern"),
        ],
        "note": "Opinion: do these change architecture patterns, parity, or deprecation posture?",
    },
    "brain-gardener": {
        "queries": [
            ("platform claims surface", "--source docs", "API behavior limits formulas"),
            ("claude platform changes", "--source claude", "API features limits"),
        ],
        "note": "Opinion: does anything in the change surface invalidate or strengthen existing claims (clm-*)?",
    },
    "cortex": {
        "queries": [
            ("attention-worthy signals", "--source changelog", "major launch new capability"),
            ("cross-agent relevance", "", "best practices patterns"),
        ],
        "note": "Opinion: who should be paying attention to what this week? Route attention.",
    },
    "project-dreamer": {
        "queries": [
            ("capability for projects", "--source docs", "new connector capability feature"),
            ("architecture inspiration", "--source github", "architecture pattern design principle"),
        ],
        "note": "Opinion: do new capabilities map to active projects' next milestones?",
    },
}


def latest_diff() -> dict | None:
    diff_dir = DATA_ROOT / "diffs"
    if not diff_dir.exists():
        return None
    files = sorted(diff_dir.glob("*.json"))
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text())
    except Exception:  # noqa: BLE001
        return None


def change_surface(diff: dict | None) -> list[str]:
    lines = []
    if not diff:
        return ["(no diff report yet — first sync may still be running)"]
    for source, res in diff.get("results", {}).items():
        if not isinstance(res, dict):
            continue
        changed = res.get("changed", 0)
        if source == "index":
            lines.append(f"- index: +{res.get('docs_added', 0)} docs, {res.get('chunks', 0)} chunks, {res.get('embedded', 0)} embedded")
        elif changed:
            lines.append(f"- {source}: {changed} docs changed")
    if diff.get("errors"):
        lines.append(f"- errors: {len(diff['errors'])} (see diffs file)")
    return lines or ["- no changes since previous sync"]


def _doc_year(h) -> int | None:
    """Best-effort publish year from the URL slug or title (e.g.
    'on-prem-file-major-update-2018', 'Product Scoop - March 2026'). The
    corpus stores no publish-date field, so slug/title year is the only
    recency signal a lens hit carries."""
    m = re.search(r"(20\d{2})", h.url) or re.search(r"(20\d{2})", h.title)
    return int(m.group(1)) if m else None


def _recency_key(h, this_year: int):
    y = _doc_year(h)
    if y == this_year:
        return 0  # current year
    if y is None:
        return 1  # undated (evergreen/current pages carry no year)
    return 2  # stale


def build_digests() -> dict:
    from .search import search as kb_search

    diff = latest_diff()
    surface = change_surface(diff)
    today = dt.date.today().isoformat()
    this_year = dt.date.today().year
    out = {}
    for agent, cfg in AGENTS.items():
        parts = [
            f"# KB digest — {agent} — {today}",
            "",
            "## Change surface (nightly sync)",
            *surface,
            "",
            "## Lens queries (live retrieval)",
        ]
        for label, source_flag, query in cfg["queries"]:
            parts.append(f"\n### {label}")
            try:
                src = None
                if "--source" in source_flag:
                    src = source_flag.split("--source ")[1].split()[0]
                hits, meta = kb_search(query, k=LENS_K, source=src)
                if src in RECENCY_SOURCES:
                    # stable sort keeps retrieval rank within each recency
                    # bucket; dedupe by doc_id (rerank surfaces several chunks
                    # of the same page)
                    hits.sort(key=lambda h: _recency_key(h, this_year))
                    seen: set[int] = set()
                    deduped = []
                    for h in hits:
                        if h.doc_id in seen:
                            continue
                        seen.add(h.doc_id)
                        deduped.append(h)
                    hits = deduped[:3]
                    if not any(_doc_year(h) == this_year for h in hits):
                        parts.append(f"_lens staleness: no {this_year} {src} hit in top {LENS_K} — "
                                     f"retrieval may be degraded; flag it on the bus_")
                conf = meta.get("confidence_bits")
                parts.append(f"_query: `{query}`{f' (source: {src})' if src else ''} — confidence {conf} bits_")
                for i, h in enumerate(hits, 1):
                    snippet = h.text[:200].replace("\n", " ")
                    parts.append(f"{i}. [{h.source}] {h.title}")
                    parts.append(f"   {h.url}")
                    parts.append(f"   {snippet}...")
            except Exception as e:  # noqa: BLE001 - digest never fails the fleet
                parts.append(f"_query failed: {e}_")
        parts += ["", "## Your job", cfg["note"], "Read the hits, form an OPINION (1-3 lines: how does this relate to ongoing work / your domain?), post it to your gossip-bus outbox. Do NOT file proposals — that is the dreamer's synthesis job."]
        DIGEST_DIR.mkdir(parents=True, exist_ok=True)
        (DIGEST_DIR / f"{agent}.md").write_text("\n".join(parts) + "\n")
        out[agent] = "written"
    return {"date": today, "digests": out}


if __name__ == "__main__":
    print(json.dumps(build_digests(), indent=2))
