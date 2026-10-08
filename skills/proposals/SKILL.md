---
name: proposals
description: Interactive approval queue for dreamer proposals from BOTH the harness-dreamer and the project-dreamer. Use when Josh says "review proposals", "show the proposal queue", "what needs a decision", "approve or reject proposals", "silver platter", or invokes /proposals. Renders every pending proposal as a decision card, collects verdicts in one batched pass, records them via proposal-decide.py, and dispatches approved work.
---

# Proposals — the silver platter

One interactive pass over everything the dreamers filed that needs Josh's
call. The mechanical recorder already exists (`proposal-decide.py`); this
skill is the face on it.

## Procedure

1. **Load the queue:**

   ```bash
   python3 ~/.claude/knowledge/scripts/proposal-decide.py list
   python3 ~/.claude/knowledge/scripts/proposal-pipeline.py --json
   ```

   If nothing is pending: say so in one line, done. No ceremony.

2. **Build one decision card per pending proposal.** Compact, scannable:

   - slug, `kind`, `risk`, source dreamer (harness/project — from the
     `project:` frontmatter; project-dreamer files carry it), age in days
   - the one-line value case (from the proposal's own headline — not your
     paraphrase)
   - the evidence anchor (its strongest ref)
   - for kind architecture/feature touching a live Workato asset: run the
     blast-radius skill and put the radius on the card.

   Order oldest-first (the stale ones get decided or die).

3. **Collect verdicts in ONE batched pass.** Use AskUserQuestion, up to 4
   proposals per call (loop batches until done). Options per proposal:

   - **Approve** — record accepted; queued for build (not built now)
   - **Build now** — accepted AND built in this session (see step 5)
   - **Reject** — recorded rejected; the note is the taste signal
   - **Defer** — untouched, re-offered next time

   Josh's "Other" free-text becomes the logged note. Never call
   AskUserQuestion twice for the same proposal.

4. **Record every verdict mechanically:**

   ```bash
   python3 ~/.claude/knowledge/scripts/proposal-decide.py <slug> accept "note"
   python3 ~/.claude/knowledge/scripts/proposal-decide.py <slug> reject "note"
   ```

   `proposal-decide.py` is the ONE recorder — it stamps the proposal
   frontmatter AND appends `garden-reports/proposal-outcomes.jsonl` (which
   the gardener's Phase 0 and the dreamers' taste-matching read). Do NOT
   use `proposal-outcome.py` (legacy duplicate, writes a second outcomes
   file — flagged for retirement, not deleted). Defer = no command, but
   list deferrals in your summary.

5. **Dispatch Build-now, scoped by kind:**

   - **Harness items** (skill/hook/mod/agent/settings/cron): build in this
     session per the proposal's exact-change draft. Josh's Build-now answer
     IS the approval for a never_auto item — state each build as you do it,
     full paths. After building, re-run decide with `build` and the
     evidence ref.
   - **Project items** (architecture/feature): execute only the bounded
     first move this session. Anything UAT/prod-touching keeps its standing
     sign-off gate — Build-now does NOT bypass it. Anything bigger than a
     first move: write the handoff/build plan (Jira story with Story
     Points) and record `accept` with "build plan filed" as the note.

6. **Close with a summary table:** slug | verdict | note | what happened
   next (built + evidence / queued / filed handoff / deferred / rejected).
   If 3+ rejections share a reason, append that taste pattern as one line
   to the dreamer's bus thread (`proposal-taste`) — that is how the
   dreamers learn.

## Hard rules

- Never decide for Josh. The queue renders facts and recommendation
  (you may mark a recommended option), the verdict is his.
- Never edit a proposal file's status by hand — the recorder does it.
- Rejected stays rejected: re-proposing needs materially new evidence
  (the dreamers' briefs already say this; don't soften it here).
- Batch, don't drip: one AskUserQuestion round per ≤4 proposals, then move.
