---
name: promotion-readiness
description: Score whether a changed Workato asset is ready for promotion — tested, masked, VUA-verified, documented, snapshot-safe — as a checklist with evidence per row. Use when the estate-architect reviews the estate, when the orchestrator assembles a batch, or when Josh asks "what's ready to promote", "is <recipe> ready".
---

# Promotion-readiness scoring

Every promotion candidate gets the same scorecard, evidence-backed per row.
The score is a gate input for the orchestrator, not a suggestion.

## The scorecard (each row: pass / fail / n/a + evidence ref)

1. **Tested** — test cases exist AND last run is green (regression registry
   or `wt testcases status`).
2. **Masked** — job trace shows data-bearing steps masked in the latest run.
3. **Identity verified** — VUA/connection mode confirmed post-last-push
   (the revert-after-push trap is history only if verified).
4. **Documented** — the governing Story/comment reflects the current state.
5. **Canon-clean** — no open canon entry against this recipe (or its canon
   entry is `tested`).
6. **No external drift** — updated_at not newer than the last ledgered edit
   (someone else touching it between promotion prep and promote is the
   classic mess).
7. **Dependencies staged** — called functions/tables are in the batch or
   already healthy in prod.

## Output

Per asset: a one-line verdict (ready / not ready: <first failing row>) plus
the scorecard rows with evidence. The orchestrator blocks batches containing
a not-ready asset unless Josh explicitly overrides by name.

## Rules

- A row without evidence fails. "Probably masked" is a fail.
- The score is computed fresh at batch-assembly time, never cached from an
  older session.
- n/a rows need the reason (e.g. "no test cases exist for this asset class
  yet" — which itself becomes a finding).
