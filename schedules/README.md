# Schedules

The fleet runs on launchd — one `com.josh.fleet.<job>` plist per job,
all executing `~/.local/bin/fleet/run-job.sh` with per-job prompts and env
from `bin/fleet/jobs/` (mkdir locks, timeouts, per-job logs). Jobs run with
NO session open. Install:

    ./install-launchd.sh

42 jobs as of 2026-10-16. Zero-LLM jobs are pure python (no model spawn);
agent jobs spawn headless `claude` runs; skill jobs set `CLAUDE_JOB=yes`
(the session-budget exemption).

## The fleet

| When | Job | What it does |
|---|---|---|
| hourly | cortex | Coordinator pulse: reads everything, routes attention |
| hourly | health | Fleet liveness probe |
| hourly :41 | bus-actuate | Corroboration tally to consequences (zero-LLM) |
| every 2h | jira-triage | Identify-triage-investigate-plan loop over the Jira queue |
| 22:31 daily | docs-watch | Vendor docs crawler (zero-LLM) + summary; first bus poster |
| 22:43 daily | gardener | Brain gardener: drift/conflict/rot checks + proposal pipeline |
| 23:13 daily | watchdog | Estate health + heartbeat check |
| 23:20 daily | harness-health | The watchdog for the harness itself |
| 23:33 daily | backup | Harness backup (git, secrets redacted, push if configured) |
| 23:37 daily | healer | Watchdog's repair phase (DEV workspace only) |
| 23:43 daily | dreamer | Harness dreamer; reader-in-chief of the bus |
| 23:50 daily | regression | Nightly test-case pass via the Test Automation API (zero-LLM) |
| 23:50 daily | value-ledger | Value half of the ROI loop (zero-LLM) |
| 00:37 daily | project-dreamer | Architecture dreamer, one project per night (deep pass Sundays) |
| 00:47 daily | instruction-miner | Correction-mining for the instruction-patch loop (zero-LLM) |
| 00:53 daily | evidence | Nightly claim hunt: re-checks done claims against live state |
| 01:07 daily | gym | Replay gym; Sundays add the immune fire drill |
| 03:07 daily | synaptic-strength | (zero-LLM) |
| 03:17 daily | index-budget | Knowledge-index budget check (zero-LLM) |
| 03:17 daily | uat-sweep | Read-only UAT verification sweep over the dev workspace |
| 03:27 daily | titer-report | (zero-LLM) |
| 03:37 daily | replay-sample | (zero-LLM) |
| 03:47 daily | queue-drift | Rebuild-and-diff of the triage queue projection (zero-LLM) |
| 04:37 daily | restore-drill | Rehearse the backup restore (zero-LLM) |
| 04:43 daily | frontier-nightly | Twin refresh, prediction resolution, calibration, precursor radar (zero-LLM) |
| 05:07 daily | cost-governor | Cost governance scripts (zero-LLM) |
| 05:07 daily | wave3-nightly | Trigger ledger, coincidence scoring, ratchet watch (zero-LLM; Sundays add null-miner/pleiotropy/MAP-Elites) |
| 06:05 daily | canary | Command canary |
| 06:07 daily | ops-autopsy | Failed-job autopsies |
| Wed 06:07 | antigen | Inject one fault class into the dev canary, verify detection, record immunity |
| Mon 06:07 | corpus | Corpus indexer: recipes + task counters, dev and prod |
| Mon 06:27 | minutes | Board minutes (zero-LLM) |
| Mon 06:27 | roi-weekly | ROI weekly (zero-LLM) |
| Mon 06:37 | architect | Estate architect weekly review |
| 07:13 daily | brief | Morning brief: machine + bus + dream + Jira + repos in one digest |
| 07:20 daily | decision-inbox | One ranked, budgeted decision surface |
| 07:37 / 14:07 / 19:37 daily | kb-audit | KB corpus/pipeline integrity audit, three passes |
| 07:45 daily | loadout | Morning load-out assembled from the brief |
| 08:10 daily | harness-fix | Auto-lane worker for the harness's own approved fixes |
| Tue 07:07 | turn-audit | Turn-discipline classification (zero-LLM) |
| Tue 07:27 | kb-corpus-sync | Weekly knowledge-corpus export to this repo |
| unscheduled | ops-visibility | Event-driven |

## Nightly order (matters: gossip bus)

docs-watch 22:31 (first poster) → brain gardener 22:43 → watchdog 23:13 →
harness-health 23:20 → backup 23:33 → healer 23:37 → dreamer 23:43
(reader-in-chief) → project-dreamer 00:37 → instruction-miner 00:47 →
evidence 00:53. Each agent appends only to its own outbox
(`knowledge/dreams/bus/<agent>.jsonl`); the dreamer merges and synthesizes.
Protocol: `knowledge/dreams/GOSSIP.md`.

## Legacy lane: Claude Code scheduled tasks

Before the launchd fleet, agent jobs ran as Claude Code scheduled tasks
(fire only while a session is idle). That lane still works for jobs you
want gated on an open session — create them by telling Claude in your work
project:

> Create a durable recurring cron task: cron `43 22 * * *`, prompt:
> [paste the job prompt from this folder]

Every task is self-rearming (re-creates itself before the 7-day scheduler
expiry) and appends to the heartbeat log the watchdog checks. The launchd
fleet superseded this lane for everything scheduled; prefer launchd.

Promotion prep is ON-DEMAND (batches are inventory-driven, not
calendar-driven): say "prepare a promotion batch" when /promotion-ready
shows enough.
