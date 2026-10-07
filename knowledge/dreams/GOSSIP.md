# The gossip bus

Shared channel for Josh's agent network: docs-watch, brain-gardener,
workato-watchdog, harness-dreamer, estate-architect, promotion-orchestrator.

## Layout: maildir pattern, no shared writable file

`~/.claude/knowledge/dreams/bus/<agent>.jsonl` — ONE outbox per agent. An
agent appends ONLY to its own outbox, so every file has exactly one writer.
No locks, no races, safe at any level of parallelism. Read-side aggregation
instead of write-side coordination.

```
knowledge/dreams/bus/
  docs-watch.jsonl
  brain-gardener.jsonl
  workato-watchdog.jsonl
  harness-dreamer.jsonl
  estate-architect.jsonl
  promotion-orchestrator.jsonl
```

## Event schema (one JSON object per line)

```json
{"ts":"2026-10-07T23:15:00Z","agent":"watchdog","kind":"finding","subject":"broken-snowflake-conn","line":"one sentence with the specifics","refs":["https://app.workato.com/..."],"thread_id":"broken-snowflake-conn","corroborations":0,"ttl_days":14}
```

- `agent` — your name (and your outbox): docs-watch | brain-gardener |
  workato-watchdog | harness-dreamer | estate-architect | promotion-orchestrator
- `kind` — finding (new observation) | verify (corroboration of an existing
  thread) | handoff (asking another agent to act) | proposal-ref (pointer to
  a dream proposal)
- `subject` / `thread_id` — same short-kebab-slug for every event about the
  same underlying thing. This is how corroboration is counted.
- `refs` — clickable Workato URLs, Jira keys, ledger lines, transcript refs
- `ttl_days` — 14 default; harvest deletes expired lines per-outbox

## Reading the bus

`python3 ~/.claude/knowledge/scripts/gossip-read.py` merges all outboxes,
sorts by time, tallies corroborations per thread, applies TTL. Flags:
`--since 24h|7d|all`, `--thread <slug>`, `--agent <name>`, `--json`.

## Protocol (every agent)

1. **READ at start**: run gossip-read.py (`--since 24h` by default). If what
   you were about to report already has a thread (same subject), do NOT open
   a new one — append `kind:"verify"` to YOUR OWN outbox on that thread_id
   with YOUR independent evidence and bump `corroborations`.
2. **POST at end**: append your top findings (max 3, terse one-liners with
   refs) to your own outbox. Nothing goes on the bus without a ref.
3. **HANDOFF**: if another agent should act (dreamer should propose a guard,
   orchestrator should include an asset, gardener should verify a claim),
   append `kind:"handoff"` on the thread naming the agent and the action.
4. **Never rewrite** an outbox line. Corrections are new lines. Harvest
   deletes expired lines only; the backup preserves everything.

## Corroboration = confidence

Corroboration count is the dreamer's trust signal and Josh's review shortcut:
1 witness = observation, 2 = pattern, 3+ = act on it. Independent agents
corroborating is the strongest evidence class the harness has.

## Why not one shared file

A single gossip.jsonl many agents append to races as the network grows
(interleaved writes, read-while-harvest mutation). Per-agent outboxes are
single-writer by construction; the merged view is computed on demand. If the
network ever outgrows grep-and-cat volume (it won't soon: ~30 lines/night),
the upgrade path is a SQLite bus behind the same gossip-read.py interface.
