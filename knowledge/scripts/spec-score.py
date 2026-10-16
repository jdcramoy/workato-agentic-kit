#!/usr/bin/env python3
"""spec-score.py — mechanical self-score of a spec against an evidence list.

Reads a spec file (~/.claude/knowledge/specs/<slug>.md) plus the run's
evidence strings (from the builder's report or a /triage run log) and scores
every `- [ ]` acceptance criterion MET / PARTIAL / MISSED by keyword overlap.
Zero LLM calls — deliberately mechanical and humble: a criterion with no
overlapping evidence is MISSED, never assumed met.

Usage:
  spec-score.py <spec.md> <evidence-file>          # .json = [str] or {"evidence":[..]}; .txt = one evidence line per line
  spec-score.py <spec.md> --inline "evidence 1" "evidence 2"

Writes <slug>-score.json next to the spec (appends a new entry under
"runs") and prints a human-readable checklist.

Exit codes: 0 = scored (any outcome), 2 = usage/IO error.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "on", "in", "to", "for", "with",
    "is", "are", "be", "was", "were", "at", "by", "from", "that", "this",
    "it", "its", "as", "into", "after", "before", "shows", "show", "still",
    "when", "while", "not", "no", "than", "then", "each", "any", "all",
    "has", "have", "had", "was", "were", "been", "being", "returns",
    "return", "per", "over", "under", "within", "against", "via", "does",
    "did", "done", "remains", "remain", "flat", "intact",
}
MIN_TOKEN = 3  # keep tokens like "mcp", "job", "403", "vua"


def tokenize(text):
    words = re.findall(r"[a-z0-9_\-]+", text.lower())
    return {
        w for w in words
        if (len(w) >= MIN_TOKEN and w not in STOPWORDS) or w.isdigit()
    }


def parse_criteria(spec_text):
    criteria = []
    for line in spec_text.splitlines():
        m = re.match(r"^\s*-\s*\[\s*\]\s+(.+)$", line)
        if m:
            criteria.append(m.group(1).strip())
    if not criteria:
        sys.exit("error: no unchecked `- [ ]` acceptance criteria found in spec")
    return criteria


def load_evidence(path):
    p = Path(path)
    if p.suffix == ".json":
        data = json.loads(p.read_text())
        if isinstance(data, dict):
            data = data.get("evidence", [])
        if not isinstance(data, list):
            sys.exit("error: evidence JSON must be a list of strings or {\"evidence\": [..]}")
        return [str(x) for x in data]
    return [
        line.strip() for line in p.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]


def score_criterion(criterion, evidence):
    """Score one criterion against evidence strings by keyword overlap.

    MET: >= 2 keyword hits in one evidence string, or >= 60% of keywords.
    PARTIAL: exactly 1 keyword hit somewhere.
    MISSED: nothing overlaps.
    """
    toks = tokenize(criterion)
    best, best_hits, best_src = set(), 0, None
    for ev in evidence:
        ev_toks = tokenize(ev)
        hits = toks & ev_toks
        if len(hits) > best_hits:
            best, best_hits, best_src = hits, len(hits), ev
    frac = (len(best) / len(toks)) if toks else 0.0
    if best_hits >= 2 or frac >= 0.6:
        verdict = "MET"
    elif best_hits == 1:
        verdict = "PARTIAL"
    else:
        verdict = "MISSED"
    return {
        "criterion": criterion,
        "verdict": verdict,
        "matched_keywords": sorted(best),
        "best_evidence": best_src,
    }


def main():
    args = sys.argv[1:]
    if len(args) < 2 or args[1] == "--help":
        print(__doc__)
        sys.exit(2)
    spec_path = Path(args[0]).expanduser()
    if args[1] == "--inline":
        evidence = args[2:]
    else:
        evidence = load_evidence(Path(args[1]).expanduser())
    if not evidence:
        # Humble: empty evidence = everything missed, by design.
        evidence = []

    spec_text = spec_path.read_text()
    criteria = parse_criteria(spec_text)
    results = [score_criterion(c, evidence) for c in criteria]

    met = sum(1 for r in results if r["verdict"] == "MET")
    partial = sum(1 for r in results if r["verdict"] == "PARTIAL")
    missed = sum(1 for r in results if r["verdict"] == "MISSED")

    entry = {
        "spec": str(spec_path),
        "scored_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "evidence_count": len(evidence),
        "total": len(criteria),
        "met": met,
        "partial": partial,
        "missed": missed,
        "verdict": f"{met}/{len(criteria)} met ({partial} partial, {missed} missed)",
        "results": results,
        "note": "mechanical keyword-overlap score; a MISSED row may be a "
                "matching-vocabulary problem, not a real gap — read the "
                "evidence before judging the build",
    }

    score_path = spec_path.with_name(spec_path.stem + "-score.json")
    if score_path.exists():
        try:
            doc = json.loads(score_path.read_text())
            doc.setdefault("runs", []).append(entry)
        except (json.JSONDecodeError, KeyError):
            doc = {"slug": spec_path.stem, "runs": [entry]}
    else:
        doc = {"slug": spec_path.stem, "runs": [entry]}
    score_path.write_text(json.dumps(doc, indent=2) + "\n")

    print(f"Spec: {spec_path.name}  ({len(criteria)} criteria, {len(evidence)} evidence strings)")
    print(f"Score: {entry['verdict']}")
    print("-" * 72)
    for r in results:
        print(f"[{r['verdict']:7s}] {r['criterion']}")
        if r["best_evidence"]:
            print(f"          via: {r['best_evidence'][:100]}")
    print("-" * 72)
    print(f"Wrote {score_path}")
    if missed:
        print("Reminder: MISSED = no evidence overlapped; verify the build "
              "or the evidence wording before treating it as a real failure.")


if __name__ == "__main__":
    main()
