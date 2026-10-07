---
name: testcase-authoring
description: Author a Workato test case that actually reproduces a failure class — fixture shape that trips it, assertion that proves the fix. Use when canonizing a bug (the canon's open entries need covering tests), when a fix needs a regression guard, or when Josh asks for test coverage on a recipe.
---

# Test-case authoring

The canon's open entries need tests that BITE. A test case that can't fail
on the bug it was written for is decoration.

## Anatomy of a biting case

1. **The failure signature first.** From the autopsy/canon entry: what input
   or state produced the failure? The fixture must reproduce THAT, not a
   happy path.
2. **Fixture shape.** Name the exact input that trips the failure class:
   empty payload, missing field, oversize payload, expired-token shape,
   boundary value. Write the fixture to produce it deterministically.
3. **The assertion.** What output proves the guard works? Assert on the
   behavior the fix introduced (the guard's message, the empty-state
   handling, the correct count), not on "it ran."
4. **The counter-proof.** If possible, a second case with the healthy input
   proving the guard doesn't over-fire.

## Procedure

1. Read the canon entry / autopsy: signature, origin step, evidence line.
2. Design fixture + assertion against the ORIGIN step's contract.
3. Create the case on the recipe (Test Automation API / UI).
4. Run it: `wt testcases run --recipe <id>`; the case must PASS on the fixed
   recipe and would have FAILED before the fix (state why in the case name
   or description).
5. Link it: update the canon entry's `test_case_id` and status to `tested`.

## Rules

- Name cases after the failure class: `guard-empty-records-json-payload`.
- A case that has never failed on the unfixed code is unproven — say so.
- Never weaken a fixture to make a case pass.
