---
name: uat-evidence
description: Assemble the UAT evidence block for a Jira story — run the recipe's test cases, pull the traces, verify masking held, and produce the evidence section in Josh's standards format. Use when preparing a story for review/UAT, when the promotion orchestrator stages a batch, or when Josh says "collect UAT evidence", "prepare evidence for BSYS-...", or "is this UAT-ready".
---

# UAT evidence collector

The promotion bottleneck is evidence assembly, not testing. This skill
produces the evidence section a story needs, in Josh's standards format,
without him assembling it by hand.

## Procedure

1. **Scope.** Recipe/asset IDs from the ticket or the batch manifest. Pin
   them (never from names).
2. **Run the tests.** `wt testcases run --recipe <id>` per asset; poll to
   completion (`wt testcases status`). Record run IDs and per-case results.
3. **Pull the traces.** For each material case: the job URL + the key trace
   lines (the steps that prove the behavior). Real job IDs only — never a
   paraphrase of what a job "would" show.
4. **Masking gate.** Inspect the actual job trace for the recipe: confirm
   every data-bearing step is masked. An unmasked PII line in a trace FAILS
   the evidence, full stop — that goes back as a defect, not a footnote.
5. **Assemble the block** (Josh's UAT Evidence section):
   - test run IDs + pass/fail rows
   - evidence job URLs (each resolving under its owning recipe)
   - masking confirmation with the trace reference
   - what is proven vs structural-only vs not yet tested
6. **Attach to the story** via comment in Josh's voice (doc register), or
   return the block for his review before posting (his call per ticket).

## Rules

- Empty or pending UAT is written as "UAT pending: evidence will record X"
  — never implied.
- Evidence that cites a job that doesn't resolve = invalid block.
- Masking is a gate, not a note. Failing the gate blocks the story's
  promotion, not the evidence assembly.
