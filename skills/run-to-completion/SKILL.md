---
name: run-to-completion
description: Governs turn behavior on any multi-step or long-running task. Once a task starts, do NOT end the turn until the work is done and verified, or you are genuinely blocked on Josh (destructive/outward-facing mutation, or information only he has). Never end a turn to narrate intent, report a single sub-step, or ask whether to continue. Batch independent tool calls in parallel, chain dependent ones, and drive every phase of the spec in one continuous run. Applies to every task, not just Workato.
---

# Run to Completion

## The rule
A turn ends ONLY when:
1. The full task is complete and verified with live evidence, OR
2. A step is destructive / outward-facing / UAT-production and needs explicit sign-off, OR
3. Information is required that only Josh can supply and cannot be looked up.

Finishing a tool call, a sub-step, or a phase is NEVER a reason to stop.

## Behaviors
- Never emit "Now I'll do X" / "Moving on to Y" and stop. Delete the sentence; make the tool call.
- Narration is allowed only as a short prefix on a turn that ALSO contains tool calls doing the work.
- Batch independent tool calls in one message. Chain dependent ones back-to-back.
- For a multi-phase spec: run all phases without pausing between them. Batch everything up to the single irreversible gate, then present that gate once, as a yes/no.
- Verification with live evidence (job ID, trace line, API response) is part of "done" — not optional.

## The failure this prevents
Ending the turn after a short task (a file read, a search) and forcing Josh to say "continue" repeatedly. Claude/ChatGPT don't do this; the fix is behavioral, not config.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [BT Workflow Enablement Guide](../../kb-corpus/confluence/intbt/2557640730-bt-workflow-enablement-guide.md)
- [BTOps Workflow Guide](../../kb-corpus/confluence/intbt/2557640742-btops-workflow-guide.md)
- [BT Ops Workflow Guide](../../kb-corpus/confluence/intbt/2060451866-bt-ops-workflow-guide.md)
- [[SA-23] Step ups - automatic stage progression to closed won](../../kb-corpus/confluence/intbt/554401912-sa-23-step-ups---automatic-stage-progression-to-closed-won.md)
<!-- kb-bridges:end -->
