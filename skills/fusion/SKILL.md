---
name: fusion
description: Surgical multi-model Fusion — N gateway models answer the same task and their answers are cross-checked. Use ONLY when the P0 gate passes (hard-to-reverse or prod-facing AND wrong-answer cost > ~$5 AND subtle failure mode), or when Josh explicitly asks to fuse. Carries Josh's invocation policy from domains/model-gateway-playbook.md. Never use for investigations, searches, drafts, or cheap-to-redo work.
---

# Fusion — surgical multi-model cross-check

Josh's ruling (2026-10-10): fusion is a surgical tool with a decision framework, NOT a
default. Single-model is the default; role-routed pins (Phase 3) already capture most of
the benefit at zero marginal cost.

## The gate (ALL three must hold — check before doing anything)

1. **Hard-to-reverse or prod-facing.** Prod hotfix plans, recipes with financial side
   effects, security-sensitive changes, UAT-signoff decisions.
2. **A wrong answer costs more than ~$5 of tokens.** Fusion costs N× a single run plus
   your judging time.
3. **The failure mode is subtle** — plausible-but-wrong output, not a loud error.

If any box is unchecked: do NOT fuse. Run single-model and say so.

Also fuse when Josh says "fuse it" / "cross-check with another model" — his call overrides
the gate, but still state the cost shape (N models × max_tokens) before running.

## Two invocation modes

**Mode A — script (one-shot prompts, no tools needed):**
`python3 ~/.claude/knowledge/scripts/fusion-run.py --task-file <file> --models m1,m2[,m3]`
- Default trio: `fireworks/kimi-k3,baseten/kimi-k3,fireworks/glm-5.3-flash` (2 model
  families + 2 providers). Swap in `baseten/deepseek-v4-pro` for pure-text analytical tasks
  (it is vision-less and collapses on big multi-file generation — do not use it as the
  code-writer candidate).
- Only for prompts answerable in one shot: a plan critique, a diff verdict, a risk call.
- Thinking models (glm family) emit long `reasoning_content` BEFORE the answer — give
  headroom or content comes back empty (the script detects this and says so). The
  >=1500 guidance is far too low for dense analytical prompts: empirically (2026-10-10
  design-critique run) glm-5.3-flash and deepseek-v4-pro both exhausted 6,000 tokens in
  reasoning alone and only answered at --max-tokens 12000; fireworks/kimi-k3 TIMED OUT at
  12000 on the same prompt (use it at <=6000, or accept truncation and rerun the tail).
  Rule of thumb: analytical critique prompts need 12000 for glm/deepseek panelists.
  2026-10-11 data point (dense ideation prompt, ~2k tokens): glm EXHAUSTED 12000 and
  needed 20000 to answer (worth it — 4 unique top-tier ideas); deepseek answered fully
  at 12000 in ~2 min (best speed/depth); kimi-k3 at 6000 spent the whole budget on
  visible brainstorming (fireworks) or silent reasoning (baseten) — for ideation prompts
  kimi needs an "answer-first, no preamble" instruction or a much bigger cap.

**Mode B — Agent-tool relay (task needs tools: reading files, pulling recipes, editing):**
Spawn 2-3 subagents IN ONE MESSAGE (parallel), each with a different `model` value, same
task prompt, and file ownership made disjoint or read-only. Then diff their reports
yourself. Never let fused agents write to the same files.

## Judging the answers

- Similarity ratios from the script are a heuristic, never a verdict.
- Disagreement is the product: identify WHAT differs, decide which model has the evidence
  advantage, and if you cannot decide, present the diff to Josh in one card per answer —
  do not average, do not merge.
- Unanimous + wrong is possible (shared model-family blindness): if the task is also
  kimi-shaped, add a non-kimi family to the panel rather than trusting unanimity.
  LIVE EXAMPLE (2026-10-10): two panelists independently and confidently asserted
  "Workato connections are env-local and cannot be promoted via manifest" — flat wrong;
  docs (recipe-development-lifecycle/export) + Josh's own promotion history show
  connections ARE packageable manifest assets, only their credentials don't transfer.
  When a panel's confident claim contradicts the operator's lived experience or a
  checkable doc, the claim loses.
- Log rows land in `knowledge/models-evals/fusion.jsonl` automatically (Mode A).

## Cost guardrail

State the shape before running: "Fusing 3 models × ~2k output tokens ≈ N cents-$X." If a
fusion run would exceed ~$5 of tokens, stop and get Josh's ok first. Concurrency: ≤3
parallel requests — the gateway per-key cap is ~30-40; a fusion panel plus a running swarm
can trip it, so stagger if other agents are active.
