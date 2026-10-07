# Claim ledger

Durable knowledge as structured claims instead of scattered prose. One JSON
object per line in `claims.jsonl`. The gardener re-verifies active claims each
run and disputes/supersedes stale ones; contradictions become mechanically
detectable (same `subject`, conflicting `claim`).

## Schema

```json
{
  "id": "clm-NNN",
  "subject": "stable-kebab-topic",
  "claim": "the assertion, one sentence",
  "evidence": [{ "type": "job-trace|memory|skill|doc|rule|live-call", "ref": "path or ID" }],
  "confidence": "high | medium | low",
  "asserted_at": "YYYY-MM-DD",
  "last_verified": "YYYY-MM-DD",
  "status": "active | disputed | superseded | tombstoned"
}
```

## Rules

- A claim is superseded, never edited: the old line gets
  `"status": "superseded"` and the new claim gets a fresh id +
  `"supersedes": "clm-NNN"`.
- Contradiction = two `active` claims on the same subject with conflicting
  claims. The gardener flags these; only Josh/main-session resolve them.
- Re-verification: gardener samples active claims, checks evidence refs
  (file exists, asset still exists) and bumps `last_verified`, or marks
  `disputed` with a note in the garden report.
- Prose memory/knowledge files remain the narrative layer; the ledger is the
  index of *checkable assertions*. Write a claim when a fact is (a) load-bearing
  and (b) verifiable or time-decaying.
