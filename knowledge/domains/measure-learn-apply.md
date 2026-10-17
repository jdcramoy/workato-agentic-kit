# Measure → Learn → Apply — the closed loop (Josh: "build it all and weld it shut", 2026-10-09)

The harness's self-improvement contract. Every feature built today is one
vertex of one loop; the weld is that each vertex's output is the next one's
input, and nothing terminates without landing.

## The loop

1. **MEASURE** — the ledgers: usage-ledger (brain-guard), heartbeat
   (fleet), dispatches (cortex), runs (triage), fixtures verdicts,
   proposal-outcomes (gardener), ROI ledger. Plus the session-shadow's
   now-file for live focus. Every job appends; nothing counts as run
   without a heartbeat (run-job.sh validation contract).
2. **LEARN** — the analysts: dreamer mines corrections and friction;
   gardener audits the knowledge tree; the evidence agent re-verifies
   "done" claims against live state; the cost-governor computes
   per-class posteriors and budget alarms; spec-score grades delivered
   work against its own spec.
3. **APPLY** — the mechanisms: instruction-patch applies Josh-approved
   instruction edits to the skills/playbooks (airo-mcp-playbook,
   workato-development-playbook, workato-skill-builder among them);
   the cortex proposes routing-table changes; canonize-failure turns
   failures into fixtures + canon + nightly regression slots;
   rollback-rehearsal proves every fix revertible before it's called done.

## Loop-closure rules (the teeth)

- Every production failure terminates in: autopsy + fixture + canon entry
  + nightly regression slot. A failure missing any of the four is OPEN.
- Every recipe fix terminates in: fixture pass + rehearsal ledger entry +
  build-ledger line. A fix without rehearsal is not done.
- Every build starts with a spec (spec-distiller, or grill-gate when the
  ask is already crisp) and ends with a spec-score in the report.
- Every correction Josh gives a fleet agent lands in the instruction-patch
  queue; uncovered classes surface weekly via the gardener with a
  dissenter-reviewed diff, Josh approves, instruction-patch applies.
- The cost-governor writes proposals to the cortex attention queue; the
  routing table only changes through that gate.
- The evidence agent's FALSE claims route to the dissenter; repeated
  false claims about a capability retire it (governor KILL line).

## What NOT to do

- No agent edits the playbooks without a Josh-approved patch record.
- The governor never writes model-routing.json; it proposes.
- The evidence agent never soft-fails: a claim without a live check is
  UNVERIFIED, never assumed true.

## Cost/quality governor — LIVE 2026-10-09

- `scripts/cost-governor.py` (daily, zero-LLM): per-task-class posterior table
  from model-routing.json + usage-ledger + dispatches + heartbeat + validation
  + triage/proposal outcome ledgers; budget alarm = spend proxy >2x median AND
  pass <80%; proposals-only into cortex/attention-queue.md ("## Cost governor").
- `scripts/roi-report.py` (monthly, run by the fleet job on the 1st): per
  capability KILL/PROMOTE/KEEP from heartbeat invocations, file-counted
  findings, and consumed findings (triage built / proposal accepted,
  single-keyword attribution). Backup exempt (no findings by design).
- Fleet job `cost-governor` (kit bin/fleet/jobs/cost-governor.env/.prompt),
  glm-5.3-flash lane. Known instrumentation gap (proposed, not built):
  brain-guard turn-usage lines carry no job/model field, so per-class token
  cost stays a proxy until that field lands; flywheel outcomes jsonl does not
  exist yet — governor consumes it first when it does.

## Scheduler state (2026-10-09)

- cost-governor: plist INSTALLED + loaded (daily 05:07) — Josh armed it.
- instruction-miner: fleet job + plist INSTALLED (nightly 00:47).
- evidence: fleet job def + plist WRITTEN but NOT loaded — Josh names it
  ("arm the evidence nightly") to arm; on-demand works via the Agent tool.

## Value ledger — the missing half of ROI (2026-10-09)

roi-report.py measured cost + *consumption* (finding → built/accepted) but could
never say what a capability was WORTH. The value side is now instrumented:

- `scripts/value-ledger.py` — append-only `garden-reports/value-ledger.jsonl`.
  `derive` (idempotent, zero-LLM) walks triage-outcomes (built/filed),
  proposal-outcomes (built), build-ledger (ONE row per ticket — the ledger
  records every mutation, so keying per-mutation inflated 1380 rows / 4140h;
  recount-don't-increment), jira-triage runs (fixed/planned/replied).
  `note --capability X --hours N --ref Y --what "..."` is the human row for
  what ledgers can't see (incident prevented, decision unblocked).
- Hours are a labeled heuristic (`DEFAULT_HOURS` per outcome class, conservative);
  incident_prevented / decision_unblocked default 0 — never auto-asserted.
- `scripts/value-report.py` — monthly value-vs-cost roll
  (`garden-reports/value-<YYYY-MM>.md`), imports roi-report's JOB_TO_CAP so the
  two reports agree. Fleet job `com.josh.fleet.value-ledger` nightly 23:50
  (derive), rolls the report on the 1st.
- Month-to-date at build: 53 rows / 132.0h returned.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [The Agentic Workato Harness: a self-improving development organism](../../kb-corpus/confluence/extbt/2938830860-the-agentic-workato-harness-a-self-improving-development-organism.md)
- [The Workato KB: RAG++ over all documentation, and the dreaming team](../../kb-corpus/confluence/extbt/2938929237-the-workato-kb-rag-over-all-documentation-and-the-dreaming-team.md)
- [Operational Monitoring](../../kb-corpus/confluence/extbt/2940272642-operational-monitoring.md)
<!-- kb-bridges:end -->
