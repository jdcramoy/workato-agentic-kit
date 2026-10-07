---
name: workato-autopsy
description: Root-cause autopsy for a failed Workato job — walks the trace to the ORIGIN step (not the reported error step), correlates with recipe code + job history + build ledger, classifies the failure, and produces a fix-ready report with the proposed diff and the test case that would have caught it. Use whenever a recipe/job failed, a canon violation fired, or a regression test failed. Trigger on "autopsy this failure", "why did this recipe fail", "root cause", or any watchdog/regression failure handoff.
---

# Workato autopsy

Turns "the recipe failed with error X" into "this step, this input, this
diff, this test." The output must be executable by a fixer agent without any
further investigation.

## Evidence sources (always all four)

1. The failed job's trace: `job_get` (recipe_id + job_id). The step-by-step
   execution record.
2. The recipe's code: `recipe_get`. Map trace lines to steps.
3. Job history: `job_list` for the recipe — last green job, first red job.
4. The build ledger: what changed between green and red
   (`~/.claude/knowledge/build-ledger.jsonl`).

## The round trip

1. **Trace walk — find the ORIGIN step.** Workato reports where the job
   died; you walk backward from the error to the first step whose output was
   malformed, empty, or wrong. That step is the origin. The error step is
   usually a victim. Name both, plainly.
2. **Correlate.** Against the recipe code: what was the origin step's input
   supposed to be? Against time: last green run vs first red run vs ledger
   entries in that window. No recipe change in the window = the answer is
   upstream (data, connection, platform).
3. **Classify into exactly one bucket:** input-contract violation / upstream
   data change / platform change / code bug / connection-auth / config drift.
   The class determines the fix class.
4. **Canon check.** Match the failure signature against
   `~/.claude/knowledge/regression-canon/canon.jsonl`. Known signature = link
   it; new class = this autopsy becomes the candidate entry.
5. **Produce the fix-ready autopsy:**
   - origin step + victim step, named
   - the evidence line from the trace (quoted)
   - the classification
   - the proposed edit as an actual diff against the current recipe code
   - the test case that would have caught it (fixture shape + assertion)
   - the verification criterion: the exact trace line a fixed job must show
6. **Close the loop.** The fix is proven only when a new job's trace shows
   the origin step producing correct output. Verification reads the SAME
   evidence the autopsy cited.

## Hard rules

- Never diagnose from the error message alone. The trace or it didn't happen.
- Never classify "platform issue" without checking the platform delta feed
  (docs-watch posts to the bus) and the workspace status first.
- An autopsy without a proposed diff is a report, not an autopsy.
