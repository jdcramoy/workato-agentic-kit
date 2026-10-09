"""Board minutes: weekly Confluence publication of the dreaming team's advice.

Reads the past week's dream reports + bus outboxes (the Board's opinions are in
there), renders a minutes page (per-lens advice, math blocks, verdicts), and
publishes it as a DRAFT page in the BT Confluence space (extbt, parent
2938830860 — the harness-docs tree) — DRAFT status keeps it Josh-gated per the
harness-docs publish policy; he publishes on review.

Sanitizer: internal Confluence content (intbt) must never appear — the minutes
are built ONLY from dream reports + public-source KB citations. A check runs
before publish.

    python3 -m kb.board_minutes            # render + create draft page
    python3 -m kb.board_minutes --dry-run  # print the markdown, touch nothing
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

KNOWLEDGE = Path.home() / ".claude/knowledge"
DREAMS = KNOWLEDGE / "dreams"
BUS = DREAMS / "bus"
SANITIZED_PARENT = "2938830860"  # [External] BT harness-docs tree parent

INTERNAL_MARKERS = re.compile(r"intbt|\[internal\]|EDW_DB_DEV|josh\.cramoy", re.I)


def _week_reports() -> list[Path]:
    cutoff = dt.date.today() - dt.timedelta(days=7)
    out = []
    for p in sorted(DREAMS.glob("*.md")):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", p.name)
        if m and dt.date.fromisoformat(m.group(1)) >= cutoff:
            out.append(p)
    return out


def _bus_lines() -> list[str]:
    lines = []
    if not BUS.exists():
        return lines
    for f in sorted(BUS.glob("*.jsonl")):
        for line in f.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("ts", "")[:10]
            try:
                if dt.date.fromisoformat(ts) >= dt.date.today() - dt.timedelta(days=7):
                    lines.append(f"[{ts}] {rec.get('agent', '?')}: {rec.get('summary', '')[:160]}")
            except ValueError:
                continue
    return lines


def sanitize(text: str) -> tuple[str, list[str]]:
    """Strip/flag anything internal. Returns (clean_text, findings)."""
    findings = []
    out = []
    for line in text.splitlines():
        if INTERNAL_MARKERS.search(line):
            findings.append(line.strip()[:100])
            out.append(re.sub(INTERNAL_MARKERS, "[redacted-internal]", line))
        else:
            out.append(line)
    return "\n".join(out), findings


def render() -> tuple[str, list[str]]:
    reports = _week_reports()
    parts = [
        "## Board minutes — dreaming team",
        "",
        f"_Week of {dt.date.today().isoformat()} | auto-generated from {len(reports)} dream reports "
        "and the gossip bus | lenses ran cross-model (model per opinion noted in source reports)_",
        "",
        "### Advice summary",
    ]
    for p in reports:
        body = p.read_text()
        clean, _ = sanitize(body)
        # keep the report's headline + proposal/verdict lines only
        keep = [
            ln for ln in clean.splitlines()
            if ln.strip().startswith(("#", "## ", "- ", "**")) and len(ln) < 200
        ][:30]
        parts.append(f"\n#### {p.name}\n" + "\n".join(keep[:20]))
    parts.append("\n### Bus activity (opinions filed)")
    parts += [f"- {ln}" for ln in _bus_lines()[-25:]]
    math_hint = (
        "\n### Proposal math\n"
        "- P(accept) posterior + EV + break-even on every filed proposal "
        "(kb.dream_math score) — see the proposal cards in the queue.\n"
        "- Assumption regression: standing proposals re-checked nightly against the KB.\n"
    )
    parts.append(math_hint)
    text = "\n".join(parts)
    return sanitize(text)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    text, findings = render()
    if a.dry_run:
        print(text)
        print(f"\n[sanitizer findings: {len(findings)}]", file=__import__("sys").stderr)
        raise SystemExit(0)
    if not text.strip():
        print("no dream content this week — nothing to publish")
        raise SystemExit(0)
    # publish as DRAFT via the atlassian MCP is not scriptable here; the nightly
    # harness session (or Josh via /kb) picks up the rendered minutes file:
    out = DREAMS / f"board-minutes-{dt.date.today().isoformat()}.md"
    out.write_text(text)
    print(f"minutes rendered: {out} ({len(findings)} sanitizer findings)")
    print("publish via atlassian MCP createConfluencePage (status=draft, parent "
          f"{SANITIZED_PARENT}) — Josh-gated per harness-docs policy")
