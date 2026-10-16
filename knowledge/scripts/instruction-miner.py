#!/usr/bin/env python3
"""instruction-miner.py — nightly correction->instruction miner (zero LLM).

Reads the latest 2 dream reports (~/.claude/knowledge/dreams/2026-*.md) plus any
gossip-bus findings tagged "correction" (thread_id/subject/kind), clusters the
evidence into correction CLASSES by keyword, checks each class against the
current instruction surface (target skill/playbook/CLAUDE.md — does a
counter-rule already exist?), and writes UNCOVERED classes to
~/.claude/knowledge/instruction-patches/queue.jsonl as pending entries.

Covered classes are PROVEN, not assumed: the matching counter-rule line from
each target file is quoted into the run summary (stdout + instruction-patches/coverage-<date>.md).

Default posture: pending entries stay pending until Josh (or the dissenter
weekly path) approves them; instruction-patch.py refuses anything else.

Usage:
  python3 instruction-miner.py              # run the nightly pass
  python3 instruction-miner.py --dry-run    # cluster + coverage check, no writes to queue
"""

import json
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from atomic_io import atomic_append

KNOWLEDGE = Path.home() / ".claude" / "knowledge"
DREAMS = KNOWLEDGE / "dreams"
BUS = DREAMS / "bus"
OUT_DIR = KNOWLEDGE / "instruction-patches"
QUEUE = OUT_DIR / "queue.jsonl"
DOCS_CLAUDE_MD = Path.home() / "Documents" / "CLAUDE.md"
SKILLS = Path.home() / ".claude" / "skills"

# ---------------------------------------------------------------------------
# Correction-class taxonomy. evidence_kw: used to cluster raw correction text.
# coverage_kw: what a counter-rule looks like in the target file — if ANY of
# these substrings (case-insensitive) appear in the target, the class is
# COVERED and no patch is queued.
# ---------------------------------------------------------------------------

CLASSES = [
    {
        "class": "premature-success-claim",
        "desc": "Done/working claimed without a live probe of the changed path",
        "evidence_kw": [
            "premature success", "success claim", "claimed done", "claimed working",
            "claimed fixed", "done without evidence", "unverified claim",
            "indirect signal", "claimed it works", "said it was fixed",
        ],
        "targets": [
            {"file": str(SKILLS / "verify" / "SKILL.md"),
             "coverage_kw": ["live probe", "done claim", "evidence", "not verified"]},
        ],
        "suggested_patch": "Before any done claim: name the live probe (job trace, API response, file read) that proves it — else say NOT verified.",
    },
    {
        "class": "stale-recap",
        "desc": "Recaps/handoffs repeating prior-session claims as current truth",
        "evidence_kw": [
            "stale recap", "stale claim", "old recap", "outdated recap",
            "prior claim", "stale handoff", "repeated old", "last session's claim",
        ],
        "targets": [
            {"file": str(DOCS_CLAUDE_MD),
             "coverage_kw": ["do not repeat stale", "stale claims", "re-verify stale"]},
        ],
        "suggested_patch": "Recaps must re-verify anything they repeat from a prior session against a fresh source; never restate a claim you did not re-check this session.",
    },
    {
        "class": "wrong-approach-rework",
        "desc": "Wrong environment/identity/approach discovered mid-build, forcing rework",
        "evidence_kw": [
            "wrong approach", "wrong-approach", "rework", "started over",
            "torn back out", "rebuild", "should have used", "instead of the",
            "accidentally pointed", "wrong repo", "wrong environment",
        ],
        "targets": [
            {"file": str(SKILLS / "workato-development-playbook" / "SKILL.md"),
             "coverage_kw": ["authoritative surface", "input to verify", "verify material"]},
        ],
        "suggested_patch": "Pin the exact target (repo, environment, workspace, asset ID) from a live read before building on it — a supplied name or URL is input to verify, not proof of the right target.",
    },
    {
        "class": "browser-ui-loop",
        "desc": "Repetitive browser/DOM automation where an API/CLI path exists",
        "evidence_kw": [
            "browser loop", "ui loop", "browser-ui", "playwright", "dom scripting",
            "browser automation", "clicking through", "screen scrape",
        ],
        "targets": [
            {"file": str(DOCS_CLAUDE_MD),
             "coverage_kw": ["playwright or dom-level", "orca only", "browser is last resort"]},
        ],
        "suggested_patch": "Browser automation is LAST RESORT: prefer API/CLI/AIRO; when the browser is required use Orca only, and time-box the attempt before reporting the blocker.",
    },
    {
        "class": "scope-drift",
        "desc": "Corrections starting 'No,' — agent drifted off thread/scope/ownership",
        "evidence_kw": [
            "scope drift", "scope-drift", "ownership drift", "no-prefix",
            "drifted back", "off scope", "out of scope", "still about",
            "what i want", "what i asked",
        ],
        "targets": [
            {"file": str(DOCS_CLAUDE_MD),
             "coverage_kw": ["pin the exact target", "two-strike"]},
        ],
        "suggested_patch": "Before acting on any shared or named resource, restate the owner/scope in one line; if the request could plausibly collide, ask once instead of guessing.",
    },
    {
        "class": "wrong-tool-choice",
        "desc": "Reached for browser/CLI/hand-rolled path when the dedicated tool owns the job",
        "evidence_kw": [
            "wrong tool", "wrong-tool", "use the cli", "via the browser instead",
            "should have used airo", "hand-rolled", "curl instead", "shared connection",
            "dedicated app",
        ],
        "targets": [
            {"file": str(SKILLS / "airo-mcp-playbook" / "SKILL.md"),
             "coverage_kw": ["cli keychain", "dev cli", "browser", "wt`"]},
        ],
        "suggested_patch": "Tool routing order is fixed: dedicated MCP/app first, AIRO/CLI second, browser last resort — never a shared connection where a dedicated one exists.",
    },
    {
        "class": "build-order-skip-verify",
        "desc": "Built forward past a required verify/test gate (order-of-operations miss)",
        "evidence_kw": [
            "skip", "skipped the test", "before testing", "forgot to test",
            "verify after", "after the push", "order of operations", "out of order",
            "build order",
        ],
        "targets": [
            {"file": str(SKILLS / "workato-development-playbook" / "SKILL.md"),
             "coverage_kw": ["verify", "evidence", "uat", "test"]},
            {"file": str(SKILLS / "workato-skill-builder" / "SKILL.md"),
             "coverage_kw": ["recipe's test cases", "verify mappings", "verify the target"]},
        ],
        "suggested_patch": "The build loop is build -> test -> verify-with-trace -> then continue; a step that has not run its Test is not a step that happened.",
    },
    {
        "class": "uat-evidence-gap",
        "desc": "Story/UAT handed over without traces, masking check, or evidence block",
        "evidence_kw": [
            "uat", "evidence gap", "no evidence", "missing trace", "masking",
            "evidence block", "story evidence", "unmasked",
        ],
        "targets": [
            {"file": str(SKILLS / "uat-evidence" / "SKILL.md"),
             "coverage_kw": ["masking", "trace"]},
        ],
        "suggested_patch": "A story is not UAT-ready without: per-case job trace citations, a masking inspection line, and the evidence block in Josh's standards format.",
    },
]

# ---------------------------------------------------------------------------
# Evidence collection
# ---------------------------------------------------------------------------

def latest_dream_reports(n=2):
    """Latest n dated dream reports (2026-*.md, not mini-*, not GOSSIP)."""
    cands = sorted(
        (p for p in DREAMS.glob("2026-*.md") if not p.name.startswith("mini")),
        key=lambda p: p.name,
        reverse=True,
    )
    return cands[:n]


def dream_correction_lines(report: Path):
    """Pull candidate correction lines out of a dream report: bullets under
    any '## Corrections' heading, plus quoted '"..."' fragments inside them."""
    lines, in_sec = [], False
    for raw in report.read_text(errors="replace").splitlines():
        if raw.startswith("## "):
            in_sec = "correction" in raw.lower()
            continue
        if in_sec and raw.strip().startswith(("-", "*")):
            text = raw.strip().lstrip("-*").strip()
            if len(text) >= 15:
                lines.append(text)
    return lines


def bus_correction_findings():
    """Bus findings tagged correction: kind == correction, or 'correction' in
    thread_id/subject."""
    out = []
    if not BUS.is_dir():
        return out
    for f in sorted(BUS.glob("*.jsonl")):
        for ln in f.read_text(errors="replace").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                row = json.loads(ln)
            except json.JSONDecodeError:
                continue
            blob = " ".join(str(row.get(k, "")) for k in ("kind", "thread", "thread_id", "subject")).lower()
            if "correction" in blob or str(row.get("kind", "")).lower() == "correction":
                text = str(row.get("line", row.get("body", row.get("text", ""))))
                if len(text) >= 15:
                    out.append({"agent": row.get("agent", f.stem), "text": text,
                                "ref": f"bus:{f.stem}:{row.get('subject', '')}"})
    return out


def proposal_outcome_signals():
    """proposal-outcomes.jsonl: rejected-for-cause outcomes are friction signals
    (rejected-false-alarm entries are NOT corrections)."""
    p = KNOWLEDGE / "garden-reports" / "proposal-outcomes.jsonl"
    out = []
    if not p.exists():
        return out
    for ln in p.read_text(errors="replace").splitlines():
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if row.get("action") in ("rejected", "rejected-for-cause"):
            notes = str(row.get("notes", row.get("proposal", "")))
            if len(notes) >= 15:
                out.append({"text": notes, "ref": f"proposal-outcomes:{row.get('date', '')}:{row.get('proposal', '')[:60]}"})
    return out


# ---------------------------------------------------------------------------
# Clustering + coverage
# ---------------------------------------------------------------------------

def classify(text):
    """Simple keyword clustering: a class claims the text if any evidence
    keyword hits. First class in taxonomy order wins (most specific first)."""
    low = text.lower()
    hits = []
    for c in CLASSES:
        if any(k in low for k in c["evidence_kw"]):
            hits.append(c["class"])
    return hits


def coverage_for(cls):
    """For each target file: does a counter-rule already exist? Returns
    (covered: bool, proofs: [str])."""
    proofs, covered = [], False
    for t in cls["targets"]:
        f = Path(t["file"])
        if not f.exists():
            proofs.append(f"MISSING TARGET: {f}")
            continue
        body = f.read_text(errors="replace")
        # Skip YAML frontmatter and name/description lines: those match
        # trivially on the file's own name and prove nothing about rules.
        in_front = False
        found = None
        for line in body.splitlines():
            if line.strip() == "---":
                in_front = not in_front
                continue
            if in_front or line.strip().lower().startswith(("name:", "description:", "#")):
                continue
            ll = line.lower()
            if any(k in ll for k in t["coverage_kw"]):
                found = line.strip()
                break
        if found:
            covered = True
            proofs.append(f"{f}: \"{found[:160]}\"")
        else:
            proofs.append(f"{f}: no counter-rule matched keywords {t['coverage_kw']}")
    return covered, proofs


def main():
    import argparse
    # --help/-h gate (2026-10-16): bare main() ran the real mining pass and
    # wrote the coverage file, triage queue rows and a heartbeat even on a
    # naive --help.
    ap = argparse.ArgumentParser(
        description="instruction-miner (flags --dry-run still read from "
                    "argv; run bare for the real pass)")
    ap.parse_args()
    dry = "--dry-run" in sys.argv
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    reports = latest_dream_reports(2)
    evidence = []  # {text, ref}
    for r in reports:
        for line in dream_correction_lines(r):
            evidence.append({"text": line, "ref": f"dreams/{r.name}"})
    for b in bus_correction_findings():
        evidence.append(b)
    for p in proposal_outcome_signals():
        evidence.append(p)

    # Cluster
    by_class = {c["class"]: [] for c in CLASSES}
    for ev in evidence:
        for cls in classify(ev["text"]):
            by_class[cls].append(ev)

    # Coverage check + queue build
    uncovered, covered_proofs, queue_rows = [], [], []
    for c in CLASSES:
        cls_evidence = by_class[c["class"]]
        covered, proofs = coverage_for(c)
        if covered:
            covered_proofs.append({
                "class": c["class"],
                "evidence_count": len(cls_evidence),
                "proofs": proofs,
            })
            continue
        uncovered.append(c["class"])
        if cls_evidence:
            primary = cls_evidence[0]
            slug = c["class"]
            queue_rows.append({
                "ts": now,
                "slug": slug,
                "class": c["class"],
                "evidence_ref": primary["ref"],
                "evidence_count": len(cls_evidence),
                "evidence_sample": primary["text"][:200],
                "target_file": c["targets"][0]["file"],
                "suggested_patch": c["suggested_patch"],
                "status": "pending",
            })
        else:
            covered_proofs.append({
                "class": c["class"],
                "evidence_count": 0,
                "proofs": proofs,
            })

    # Write queue (dedupe: never overwrite a slug already pending/approved/applied)
    existing = []
    if QUEUE.exists():
        for ln in QUEUE.read_text().splitlines():
            try:
                existing.append(json.loads(ln))
            except json.JSONDecodeError:
                pass
    known = {r.get("slug") for r in existing}
    new_rows = [r for r in queue_rows if r["slug"] not in known]

    if not dry:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        atomic_append(QUEUE, new_rows)

    # Coverage proof report (always written — this is the evidence trail)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cov_path = OUT_DIR / f"coverage-{date.today().isoformat()}.md"
    lines = [
        f"# instruction-miner coverage — {now}",
        f"Dream reports read: {', '.join(r.name for r in reports) or 'none'}",
        f"Evidence items: {len(evidence)}; bus correction findings: "
        f"{len([e for e in evidence if e['ref'].startswith('bus:')])}",
        "",
        "## Covered classes (counter-rule quoted)",
    ]
    for cp in covered_proofs:
        lines.append(f"- **{cp['class']}** — evidence items: {cp['evidence_count']}")
        for pr in cp["proofs"]:
            lines.append(f"  - {pr}")
    lines += ["", "## Uncovered classes (queued)"]
    if not uncovered:
        lines.append("- NONE — every correction class has a counter-rule on the instruction surface.")
    else:
        for u in uncovered:
            lines.append(f"- {u}")
    if queue_rows and not any(r["slug"] in known for r in queue_rows) and not dry:
        pass
    lines += ["", f"Queued this run: {len(new_rows)} ({', '.join(r['slug'] for r in new_rows) or 'none new'})"]
    cov_path.write_text("\n".join(lines) + "\n")

    print(f"dream reports: {[r.name for r in reports]}")
    print(f"evidence items: {len(evidence)}")
    print(f"covered: {len(covered_proofs)} classes (proofs in {cov_path})")
    print(f"uncovered: {uncovered or 'none'}")
    print(f"queued: {len(new_rows)} new -> {QUEUE}")

    hb = KNOWLEDGE / "garden-reports" / "heartbeat.jsonl"
    atomic_append(hb, {"ts": now, "job": "instruction-miner"})
    return 0


if __name__ == "__main__":
    sys.exit(main())
