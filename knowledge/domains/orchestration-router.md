# Orchestration Router — teams vs fanout decision engine (2026-10-15)

Answers "who does this work?" without Josh deciding: **solo / fanout / pipeline / team**.

Script: `~/.claude/knowledge/scripts/orchestration-router.py`

## The two layers

1. **Hard rules (strategic gates, override everything):**
   - `--prod-write` → **orchestrator-gated**: the write happens in the main session after
     first-hand confirmation. Never delegated — blanket delegations never satisfy prod gates.
     Workers may gather read-only evidence first.
   - `--adversarial` → **team**: builder never reviews its own work; the reviewer must be a
     distinct persistent role. One-shot fanout cannot provide gate continuity.
   - high collision-risk + multi-subtask → **team** (disjoint ownership, no ordering races —
     the agent-swarm rule).
   - single small subtask → **solo** (dispatch overhead exceeds value).

2. **Weighted feature score (seven features, 0–1 each):**
   `independence`, `statefulness`, `coordination`, `context-volume`, `collision-risk`,
   `latency-sensitivity`, `sequential` (strict stage ordering → pipeline; added after the
   E2E battery caught an ETL case misrouting to team — coordination alone can't tell mesh
   from handoff) — argmax over four pattern score vectors. Margins < 0.5 print a
   note naming which feature would flip the verdict (measure that one, don't guess).

## When to reach for which

- **solo** — trivial lookup, one file, answer is faster than the dispatch.
- **fanout** — collect N facts and merge. Stateless, disjoint, parallel. I stay the
  verification gate; worker claims never enter the thread un-checked.
- **pipeline** — staged work where each stage's output feeds the next (Workflow tool,
  fixed prompts, auditability).
- **team** — the *process* is the product: roles, handoffs, adversarial checks, multi-turn
  grinding, shared state needing ownership.

## Why not teams everywhere (Josh Q 2026-10-15)

Direct channels bypass the verification point (corroboration ≠ truth — that's the evidence
agent's whole job); persistent agents create persistent state that rots (stale claims);
mesh chat enables permission laundering across session boundaries; emergent coordination is
unauditable. Teams where collaboration is the product; fanout where the artifact is.

## Cross-session availability

Agent roles load from `~/.claude/agents/*.md` / project `.claude/agents/` into every session.
`ListAgents` sees in-process agents, teammates, other local sessions, cloud sessions.
`SendMessage` to a completed agent's name resumes it with context intact.

## Usage

    python3 ~/.claude/knowledge/scripts/orchestration-router.py --task "..." \
      --independence 0.9 --statefulness 0.1 --coordination 0.0 \
      --context-volume 0.7 --collision-risk 0.0 --latency-sensitivity 0.8 \
      --sequential 0.1 [--subtask-count N] [--prod-write] [--adversarial] [--json]

Calibrated cases (E2E battery, 8/8 pass 2026-10-15): trivial lookup → solo (hard rule);
10-repo sweep → fanout (margin 2.05); ETL stages → pipeline (margin 1.55, after adding
`sequential`); squad-build → team by score (margin 2.05); build+review → team (adversarial
hard rule); prod hotfix → orchestrator-gated (hard rule); shared-table edits → team
(collision hard rule); JSON mode + range validation verified.
