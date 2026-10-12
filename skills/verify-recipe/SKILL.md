---
name: verify-recipe
description: >-
  Verify a Workato recipe or skill end-to-end against live evidence — a real
  job trace, not reasoning about the DSL or "it should work now." Use this any
  time a recipe/skill has just been built, edited, or debugged and needs proof
  before being called done: after a bug fix, after adding a step, before
  telling the user UAT is ready, or whenever asked to "verify", "test", "check
  if this works", or "prove" a recipe's behavior. Produces a pass/fail table
  where every row cites the specific job trace line, job ID, or API response
  that backs it — never a claim without a citation. Complements
  workato-skill-builder (this *is* that skill's Step 3, pulled out as a
  standalone, repeatable procedure usable outside a full build) and
  airo-mcp-playbook (for the AIRO tool traps encountered while pulling the
  trace). Do not use for editing/building recipe logic itself — this is
  verification only, after the build is done.
---

# Verify Recipe

A recipe or skill isn't "done" because the last push succeeded — it's done
when a live run proves the specific behavior it's supposed to have. This
skill is the repeatable discipline behind that proof: define what "correct"
means before running anything, then run it and quote the trace.

This directly encodes the pattern behind the sessions that shipped clean on
the first pass (the HR Genie weekend-counting fix, the Reconciler deferred-
task work) versus the ones that needed a correction cycle because a claim
outran its evidence.

## When to reach for this

- Right after a build or bug-fix push, before reporting it as ready for UAT.
- When asked directly to verify, test, or prove a recipe's behavior.
- When a prior claim about a recipe's behavior is in doubt and needs
  re-grounding in fresh evidence.

Not for: designing or editing the recipe's logic (that's the build itself,
per `workato-skill-builder`) — this skill assumes the build is finished and
checks it.

## Procedure

### 1. Write the acceptance checklist first

Before triggering anything, write down what a passing run actually looks
like — as a numbered list of testable assertions, not a vague "it should
work." For each input condition or failure mode in scope:

- What input/trigger condition is being tested
- What branch/step the recipe should take
- What the resulting field values, output, or downstream write should be
- What should happen on each relevant error path

If any assertion depends on a business rule that isn't in the ticket, spec,
or schema (a timeout, a grace period, an edge-case default), **stop and ask**
instead of guessing one — see the Verification Rules in `CLAUDE.md`. A guessed
rule that gets written into the checklist just launders the guess as fact.

### 2. Confirm the target before running anything

State which recipe/skill (name + ID + full Workato URL via `asset_url_get`)
and which environment (dev vs prod — this project develops in dev, per
`josh-develops-in-dev-not-prod`) you're about to test. Re-pull
(`recipe_builder_pull` / `recipe_get`) if the recipe hasn't been read in this
conversation yet, or if it was edited/pushed since the last read.

### 3. Trigger and capture the run

Trigger a real test run against real or representative data — a manual run,
a test case (`test_case_list` / `test_run_request_get`), or by waiting for
the next live trigger, whichever fits how this recipe runs. Get the job ID
(`job_list` / `job_get`).

### 4. Check every assertion against the trace — cite, don't summarize

Go through the checklist from step 1 one item at a time. For each one, quote
the **specific job trace line, field value, or error message** that proves
pass or fail. "The job succeeded" is not evidence for a specific field-
mapping or branch-taken assertion — pull the actual step output.

If an assertion fails, diagnose from the trace (not from re-reading the DSL
in isolation) and loop back to fixing the recipe — that's a return to
`workato-skill-builder`'s build step, not this skill.

If verification is blocked (missing permission, no test data, connection not
authorized), say exactly what's blocked and what would unblock it. Do not
report "not possible" — most Workato verification blockers are permission or
data gaps, not structural impossibilities.

### 5. Report the pass/fail table

```
## Verification — <recipe/skill name> (<full Workato URL>)
Job: <job_id> — <full job URL>

| # | Assertion | Result | Evidence |
|---|---|---|---|
| 1 | <what was checked> | PASS/FAIL | <exact trace line / field value / error> |
| 2 | ... | ... | ... |

Unverified / blocked: <anything not checked, and why>
```

Don't paste the full raw job trace into the response — it already cost
tokens once to fetch; quote only the lines each row's evidence needs (see
`airo-mcp-playbook`'s token-efficiency section).

### 6. Hand off

If this verification is part of a build heading to UAT, feed the pass/fail
table into the `handoff` skill's state doc, or into `workato-skill-builder`'s
Promotion Handoff block once every assertion passes.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [Test automation - Test case - Create](../../kb-corpus/docs/en/test-automation/test-case-create.md)
- [Testing recipes](../../kb-corpus/docs/en/recipes/testing.md)
- [Test automation - overview](../../kb-corpus/docs/en/test-automation.md)
- [Rerunning jobs](../../kb-corpus/docs/en/recipes/rerun-job.md)
<!-- kb-bridges:end -->
