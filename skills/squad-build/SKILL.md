---
name: squad-build
description: Parallel multi-agent construction of a multi-asset Workato project — one session spawns a squad of builder agents over the gossip bus, each owning disjoint assets, coordinated by claim posts, with a single verified integration pass at the end. Use when Josh asks to "squad-build", "build this whole project", "fan out a build", or when a spec spans 3+ recipes/functions/MCP assets and speed matters.
---

# Squad build

One session, one spec, many builders. The bus is the coordination layer.
This is for multi-asset builds (Genie + skills + MCP server, a project of
recipes + tables + functions). Single-asset work doesn't need it.

## Roles

- **The lead** (the session that got the spec) — writes the plan, decomposes
  into disjoint asset sets, spawns the squad, integrates, verifies, owns the
  final state.
- **Builders** (spawned agents) — each owns its assets ONLY. Never touches
  another builder's asset without a bus negotiation.
- **The bus** — `knowledge/dreams/bus/harness-dreamer.jsonl` is the squad
  channel for the build (thread_id = the build name). Claims, status, and
  blockers all post there.

## Protocol

1. **Lead: decompose and publish.** Break the spec into asset sets with hard
   ownership boundaries (recipe IDs/names, folders, connections). Post the
   plan to the bus: `kind:"finding"`, subject `squad-<name>-plan`, one line
   per asset with the assigned builder slot.
2. **Spawn builders** with explicit instructions: which assets, which folder,
   which connections, which datapill contracts cross assets, and the bus
   thread to post status to. Each builder posts `kind:"handoff"` style status
   on the thread as it finishes each asset (claimed → built → verified).
3. **Guardrails hold, always.** Builders build in DEV only. Any prod write is
   hook-13-gated as usual; a squad is not a permission. The build ledger
   records every mutation as usual.
4. **Integrate once.** The lead waits for all builders, then does the single
   integration pass: cross-asset wiring, shared connections, one push order
   (functions → tables → recipes → MCP servers).
5. **Verify as one system.** Run the whole thing (test cases or a Test
   Recipe per asset + one end-to-end run). A squad build is not done until
   the integration job is green from a trace, not from five green sub-jobs.
6. **Close the thread.** Post the outcome on the bus thread (assets,
   evidence job IDs), and canonize any bug the build surfaced.

## Failure rules

- A blocked builder posts the blocker on the thread and stops; it never
  improvises outside its asset set.
- Two builders touching the same asset = the lead mis-decomposed. Stop,
  reassign, continue.
- If the lead session dies, the thread is the state — a new lead reads the
  bus and resumes from claimed/built/verified statuses.
