"""Memory-state entropy report (Free Energy framework for the dreaming fleet).

Measures the "digital entropy" of the harness's long-term memory so the
dreaming/consolidation loop has a NUMBER to minimize, not a vibe:

  H_redundancy  - duplicate/near-duplicate claims and knowledge lines
  H_contradiction - conflicting claim pairs (same subject, different verdicts)
  H_decay       - stale claims / stale knowledge files (temporal drift)
  H_dispersion  - how unevenly knowledge is spread across files (Gini of sizes)

Surprise ~= Complexity - Accuracy: the report is the Complexity term. The
gardener acts on it (consolidation = dedup/compress), the dreamer reads it
(high-entropy region = highest-value dream target). Written nightly to
knowledge/dreams/entropy-report.json + appended to the bus.

    python3 -m kb.dream_entropy
"""

from __future__ import annotations

import datetime as dt
import json
import math
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

KNOWLEDGE = Path.home() / ".claude/knowledge"
CLAIMS = KNOWLEDGE / "claims" / "claims.jsonl"
OUT = KNOWLEDGE / "dreams" / "entropy-report.json"


def _claims() -> list[dict]:
    if not CLAIMS.exists():
        return []
    return [json.loads(l) for l in CLAIMS.read_text().splitlines() if l.strip()]


def claim_entropy() -> dict:
    claims = _claims()
    if not claims:
        return {"claims": 0}
    n = len(claims)
    # redundancy: near-duplicate claim texts
    texts = [c.get("claim", "")[:200] for c in claims]
    dup_pairs = 0
    for i in range(n):
        for j in range(i + 1, n):
            if SequenceMatcher(None, texts[i], texts[j]).ratio() > 0.85:
                dup_pairs += 1
    # contradiction: same subject, opposite verdicts
    by_subject: dict[str, set] = defaultdict(set)
    for c in claims:
        subj = (c.get("subject") or "unsubjected").lower()
        verdict = (c.get("verdict") or c.get("status") or "?").lower()
        by_subject[subj].add(verdict)
    contradictions = sum(1 for v in by_subject.values() if {"verified", "unverified"} <= v or len(v) > 1)
    # decay: claims not re-verified in 30d (last_verified missing or old)
    stale = sum(
        1 for c in claims if not c.get("last_verified") or str(c.get("last_verified", ""))[:10] < "2026-09-08"
    )
    return {
        "claims": n,
        "redundant_pairs": dup_pairs,
        "contradictory_subjects": contradictions,
        "stale_claims": stale,
        "stale_ratio": round(stale / n, 3),
        "redundancy_rate": round(dup_pairs / max(n, 1), 3),
    }


def file_dispersion() -> dict:
    """Gini coefficient over knowledge-file sizes — 0 = uniform, 1 = concentrated."""
    files = [p for p in KNOWLEDGE.rglob("*.md") if p.is_file() and p.stat().st_size > 0]
    sizes = sorted(p.stat().st_size for p in files)
    n = len(sizes)
    if not n:
        return {"files": 0}
    total = sum(sizes)
    cum = sum((i + 1) * s for i, s in enumerate(sizes))
    gini = (2 * cum) / (n * total) - (n + 1) / n
    # shannon entropy of the size distribution
    probs = [s / total for s in sizes]
    H = -sum(p * math.log2(p) for p in probs if p > 0)
    return {"files": n, "gini": round(gini, 3), "size_entropy_bits": round(H, 2), "total_kb": round(total / 1e6, 1)}


def main() -> None:
    report = {
        "date": dt.datetime.now().isoformat(timespec="seconds"),
        "claims": claim_entropy(),
        "files": file_dispersion(),
        "reading": "Complexity term of Surprise ~= Complexity - Accuracy. The gardener "
        "minimizes (consolidation); the dreamer exploits (high-entropy regions are "
        "where the interesting dreams live).",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2))
    try:
        with (KNOWLEDGE / "dreams/bus/workato-kb.jsonl").open("a") as f:
            f.write(
                json.dumps(
                    {
                        "ts": report["date"],
                        "agent": "workato-kb",
                        "type": "entropy_report",
                        "summary": f"memory entropy: {report['claims'].get('stale_ratio', '?')} stale-claim ratio, "
                        f"{report['claims'].get('redundant_pairs', '?')} redundant pairs, gini {report['files'].get('gini', '?')}",
                    }
                )
                + "\n"
            )
    except Exception:  # noqa: BLE001
        pass
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
