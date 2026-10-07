---
name: rollback-rehearsal
description: Prove a fix is revertable by actually rehearsing the revert — snapshot restore, verify, re-apply. Use after any auto-dev fix before marking it done, or whenever a change is claimed "revertable" and should be demonstrated.
---

# Rollback rehearsal

"Revertable" is demonstrated, not claimed. Before a fix is marked done,
prove the escape hatch works.

## Procedure

1. **Baseline exists?** Confirm the pre-fix snapshot: recipe-history git log
   for the recipe, or the ledger's recorded before-state. No baseline = the
   fix was never revertable; say so and make one now.
2. **Rehearse the revert.** Restore the baseline version (recipe version
   history or the snapshot), confirm the recipe state matches the baseline
   (recipe_get version + key fields).
3. **Re-apply.** Restore the fix and re-verify (the fix's own acceptance
   evidence).
4. **Report both directions:** revert evidence + re-apply evidence. The
   report line: "reverted and re-applied cleanly" with both job/verification
   refs.

## Rules

- Dev only. Rehearsals never run against prod recipes.
- If the revert does not restore cleanly, the fix is NOT done: flag it as
  "revert failed rehearsal" and escalate to Josh.
- Running recipes: stop → rehearse → start, and prove the running state at
  the end (the silent no-op trap).
