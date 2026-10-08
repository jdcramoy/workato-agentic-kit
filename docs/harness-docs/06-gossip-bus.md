# The gossip bus: how the agents talk

Parent page: The Agentic Workato Harness

Six-plus agents need to share what they learn without a coordinator, a
message queue, or any infrastructure beyond the file system. The answer is
a maildir pattern: one append-only outbox file per agent, merged on read.

## The mechanics

```
knowledge/dreams/bus/
  docs-watch.jsonl            <- only docs-watch appends here
  brain-gardener.jsonl        <- only the gardener appends here
  workato-watchdog.jsonl      <- only the watchdog appends here
  harness-dreamer.jsonl       <- only the dreamer appends here
  estate-architect.jsonl      <- only the architect appends here
  promotion-orchestrator.jsonl
  dissenter.jsonl
  cortex.jsonl
```

Every file has exactly one writer, so there are no locks, no races, and no
overwrites at any level of parallelism. The merged view is computed on
read, not on write: a small reader script merges all outboxes, sorts by
time, tallies corroborations per thread, and applies expiry. The cost is
zero and the failure mode is "a file", not "a broker".

## The event schema

One JSON object per line:

```json
{"ts":"2026-10-07T23:15:00Z","agent":"watchdog","kind":"finding",
 "subject":"broken-snowflake-conn","line":"one sentence with specifics",
 "refs":["https://app.workato.com/connections"],
 "thread_id":"broken-snowflake-conn","corroborations":0,"ttl_days":14}
```

Four kinds: **finding** (new observation), **verify** (corroboration of an
existing thread), **handoff** (route work to another agent), and
**proposal-ref** (pointer to a dream proposal). The subject and thread_id
are the same slug for every event about the same underlying thing, which
is how corroboration is counted mechanically.

## The protocol

Every agent follows the same three rules, written into its SOP:

1. **Read the bus at start.** If your finding already has a thread, append
   a verify on that thread from your own outbox instead of opening a
   duplicate. Corroboration beats volume.
2. **Post your top findings at end.** Maximum three, terse, with
   references. Nothing goes on the bus without an evidence ref.
3. **Use handoffs to route work.** The watchdog finds it, the dreamer
   proposes a guard, the gardener verifies the claim, the dissenter
   attacks the proposal, Josh approves.

## Corroboration is the confidence unit

One witness is an observation. Two witnesses is a pattern. Three or more
means act on it. Independent agents reaching the same conclusion through
different methods (a connection failure seen by the watchdog's health
check and the estate architect's parity diff) is the strongest evidence
class the harness has, and the morning brief leads with corroborated
threads so the human sees patterns before noise.

The live proof came on the bus's first night: the docs crawler posted the
first real finding (a platform status page change) through the full
pipeline, outbox to merged read, and the network has run on it since.
Adding a new agent to the network is three steps: create its outbox file,
add the gossip section to its SOP, pick a slot in the nightly order.
Nothing else to wire.

Verdict: agent-to-agent communication did not need a message broker; it
needed a convention, a reader script, and the discipline to corroborate
instead of duplicate.
