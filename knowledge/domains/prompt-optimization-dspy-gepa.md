# Prompt optimization: DSPy + GEPA (banked 2026-10-13)

Session-origin analysis: "would DSPy + GEPA play nicely with our system?" Verdicts below
are design-level (no live pilot run). Revisit when a design calls for it — Josh explicitly
parked this ("nothing is itching yet"), NOT a build queue item.

## What they are

- **DSPy**: prompts as compiled code. Define task + metric + train/val set; optimizers
  evolve the instructions against the metric. Requires owning the program loop (Python).
- **GEPA** (Genetic-Pareto, Agrawal et al. 2025, dspy.ai + github.com/gepa-ai/gepa):
  reflective prompt evolution — an LLM reads FULL execution traces of failures and proposes
  targeted instruction edits; keeps a Pareto frontier of candidates; ~35x fewer rollouts
  than RL/GRPO; metric can return `(score, feedback)` text. Production proofs: Shopify
  (~75x cheaper + 2x reliability), Dropbox (2x accuracy) — mostly "optimize then downsize
  the model", so the cost win mostly doesn't apply to us (gateway model already).

## Verdicts by surface

1. **Claude Code harness loop — NO.** Skills/CLAUDE.md/agent prompts are consumed by a
   closed runtime; DSPy would have to approximate the harness in a wrapper, and optimized
   prompts don't transfer (tool lists, MCP context, session state differ). Also our cost
   problem is structural (bench: ~8x input-token tax, 81% MCP context — prompt quality
   can't touch it). The A/B bench (bench/harness-ab/) is the transfer-check if ever needed,
   not the optimization substrate (each full-harness run = 250k-1M in-toks; a GEPA
   "thousands of iterations" against it is economically absurd).
2. **Workato Genie skills — plausible pilot surface** if ever revisited: instructions are
   plain text we own; fixtures + test cases ARE the eval set; flow = genie_get → GEPA
   offline vs fixtures → genie_update. Zero prod contact until approved.
3. **GWS Semantic MCP — strong fit, but ONLY in the offline layer.**
   - HOT PATH IS OFF-LIMITS: routing is keyed exact lookup, zero LLM by design ("the
     refusal to be smart IS the product"); latency invariant (p50 ~2s flat 445→1021
     tuples) exists because resolution never scans/reasons. No prompt there = nothing to
     optimize.
   - **Fit 1 (strongest): the flywheel AI judges.** PR-002 (no human-gated promotions)
     makes the AI-judge prompt (canary sweep 82862814, gpt-4o-mini, judge→fail-closed
     merge→promote-if-ai_green) the ONLY gate on autonomous promotion — highest-leverage
     hand-written prompt in the system, never measured. Metric anchor = hard objective:
     promoted candidate routes correctly + passes conformance or it doesn't; normalizer is
     deterministic (stable fingerprints); events v3 + marker ledger = training data.
     Cautions: optimize against HELD-OUT canary outcomes (anti-gaming); judge prompt is a
     governed artifact — version it in the canonical repo.
   - **Fit 2: vocabulary/paraphrase generation.** DSPy phrase-generator scored by
     "normalizes cleanly → passes phrase sanity → fingerprints to the RIGHT capability, no
     collision" — offline, measurable vs registry 147343. Replaces hand-seeded campaigns.
   - **Fit 3: caller-side helper.** DSPy module "task + discovery roster →
     semantic_facts_json" scored against the P0 corpus — attacks the documented caller
     failure classes (camelCase, wrong intent keys, slot-type mismatches). Caller side =
     outside the hot path, violates nothing.
4. **Semantic-curious external fact**: Business Intelligence is applying these same
   concepts to self-teach and improve the semantic layer + queries for the Enterprise Data
   MCP. Not our build; convergence signal that the pattern is landing in the MCP space.

## Pareto as a decision framework (Josh note, banked same session)

Two distinct senses. 80/20 vital-few = prioritization, already instinctive (triage, P0/P1/P2).
The transferable one is the **Pareto frontier** (multi-objective): keep every candidate no
other candidate beats on ALL axes; scalar ranking forces tradeoff pricing before you know
the choices; the frontier defers pricing until the choice is real. Already implicit in Josh's
governance (red-team FAIL-blocks-but-overridable-by-name refuses to collapse security×urgency
into one number). Candidate mappings if ever formalized: promotion batches (evidence ×
blast-radius × risk → non-dominated promotable set), dreamer proposal shortlists,
model/gateway selection (quality × latency × cost — gmail-token bench already produced
frontier data: semantic wins multi-service sessions, purpose-built wins single-service).
KNOWN COST: frontiers grow — GEPA tames it with sampling pressure; in human loops the
taming mechanism is the human. **Frontier shortlists, never decides.**

## Links

- [Google Semantic MCP project](../projects/google-semantic-mcp.md) (PR-002, canary sweep, flywheel)
- [Harness benchmarking](harness-benchmarking.md) + bench/harness-ab/
- [Model gateway playbook](model-gateway-playbook.md) (judge-model cost experiments)


<!-- demoted from INDEX.md 2026-10-25, librarian pass, branch librarian/2026-10-25. Content preserved verbatim; the INDEX line is now a routing hook. -->

## INDEX line history (demoted 2026-10-25)

- - [Prompt optimization: DSPy + GEPA](domains/prompt-optimization-dspy-gepa.md) — BANKED 2026-10-13, parked (Josh: "nothing is itching yet"): verdicts per surface (harness loop NO — closed runtime + structural token tax; Genie skills plausible pilot; **GWS Semantic MCP strong fit OFFLINE ONLY — hot path stays zero-LLM; strongest target = PR-002's autonomous-promotion AI-judge prompt (canary sweep 82862814), never measured; + paraphrase generation + caller-side facts module**); Pareto-frontier as decision framework (shortlists, never decides); BI applying same concepts to Enterprise Data MCP semantic layer (external, convergence signal)