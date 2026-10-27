# The nightly machine: schedules and the morning brief

Parent page: The Agentic Workato Harness

The agents work at night, on a schedule whose order is load-bearing: each
agent can read what the previous one posted, and the dreamer runs last so
its synthesis covers the whole night. In the morning, one brief hands a
human the entire night with corroboration counts as the trust signal.

## The timeline

| Time | Job | Role on the bus |
|---|---|---|
| 21:37 | KB sync (launchd, unattended) | syncs all documentation sources into the RAG++ corpus, contextualizes, re-indexes, rebuilds the concept graph, writes the memory-entropy report and the diff report |
| 22:07 | KB digest (launchd, unattended) | per-agent briefs: what changed, live lens queries per agent's domain, so every agent opens its night knowing what moved |
| 22:15 | Docs crawler (launchd, unattended) | first poster: platform documentation and status page deltas |
| 22:31 | Docs crawler summary | folds deltas into the bus and the gardener's report |
| 22:43 | Brain gardener | curates knowledge, posts stale-claim findings |
| 23:13 | Workato watchdog | posts connection health, stalls, autopsies; opens with the heartbeat check |
| 23:33 | Harness backup | snapshots the whole harness, secrets redacted; then auto-pushes the knowledge-tree and kit remotes (token-scan refusal on staged diffs; no-op when up to date) |
| 23:43 | Harness dreamer | reader-in-chief: merges the night, writes the dream report |
| 00:37 | Project dreamer | architecture dreamer for one project per night (deep pass Sundays): mines the project's sessions, memory, repo, and git; dissenter-gated proposals |
| hourly | Hidden lane (launchd) | headless mini-mines and the cortex pulse, silent unless there is new signal |
| Mon 06:07 | Corpus indexer | recipes and task counters, development and production |
| Mon 06:27 | Board minutes (fleet job) | renders the dreaming team's week through the sanitizer and publishes a reviewable draft page in the team space |
| Mon 06:37 | Estate architect | full weekly estate review |
| 00:13 | Regression harness | runs every recipe's test cases through the Test Automation API, reports failures with job IDs |
| weekly | Antigen drill (fleet job) | chaotic-drill day: inject one known fault class into a dedicated dev canary, verify the pipeline notices, record detection verdict and immunity in a ledger |
| 05:17 | Librarian (fleet job) | corpus consolidation and external-content procurement on a beat list |
| Tue 07:07 | Turn audit (zero-LLM) | classifies every turn from the week's transcripts into productive, verification, or waste, separates blind retries from honest polls, and posts the trend: waste rate is the number the turn-discipline program moves |
| daily 06:23 | Efficiency dashboard (zero-LLM) | renders the fleet's whole bill as one self-contained page: burn by day and token class, failure rates with hooked classes split from unhooked, tokens per shipped closeout and per story point, the full session catalog. Appends its own heartbeat, so a silent failure shows up in the morning brief |
| 04:43 | Frontier nightly (zero-LLM) | no model is spawned: refresh the estate twin, resolve due predictions and publish the calibration table, run the precursor radar, backfill and report skill fitness. Five python scripts, one log, zero tokens |
| 05:xx | Evidence hunt | re-checks the last 24 hours' "done/fixed/verified" claims against live state; FALSE verdicts get a dissenter review |
| daily 07:07 | Nightly receipts gate | reads each nightly job's OUTPUT artifact (freshness-checked), not self-reported receipts: a job that ran but produced nothing is RED; escalations post to the bus before the morning brief (born from the crash-after-work class the 2026-10-20 build caught live) |
| every 900s | Knowledge write stash | hardlink-cumulative snapshots of the mutable knowledge ledgers (8-point rotation) with a restore command; born from the silent git-revert class that ate bash appends (2026-10-19/20) |
| daily 06:57 | Harness-docs sync (nightly, was weekly Tuesday per the operator 2026-10-15) | live-harness-to-repo sync + doc drift check + sanitized Confluence publish, self-rearming durable cron |
| 07:13 | Morning brief | one digest: machine heartbeat, bus patterns, dream verdict, watchdog P1s, Jira moves, repo commits, plus the decision inbox: today's ranked decisions with a budget, deferred ones rolling forward, and the day's loadout with work pre-staged |

## Schedule mechanics

The schedules are launchd plists and self-rearming session crons — 60+ jobs
total (2026-10-20 count; see `schedules/README.md` in the repo (see `schedules/README.md` in the repo
for the full table). Recurring
scheduled tasks expire after seven days by platform design, so every job
re-creates its own schedule before expiry lapses; the fleet launcher keeps
per-job prompt files, locks, timeouts, and logs. Durable scheduled tasks
only fire while a session is open and idle, so the parts that must run
unattended (the crawler, the hidden lane) are launchd jobs that need no
session at all.

## The validation contract (added 2026-10-08)

Firing is not running. The fleet runner validates every attempt for
EVIDENCE of work: a fresh heartbeat for the job inside the run window, or
non-empty output (a silent rc=0 exit with zero output is a STUB, not a
run; this class silently killed the 22:15-23:43 jobs on 2026-10-07 when
launchd's environment could not find claude or the gateway credentials,
and nobody noticed for a full day). The runner repairs the launchd
environment itself (PATH + gateway env), retries a stub once, and on a
double stub writes `garden-reports/fleet-validation.jsonl`, a confirmed
execution failure the watchdog escalates to the bus and the morning burn.
Since 2026-10-20 the ledger also records a success row per validated-clean
run, same shape as the failure rows (`result: "valid"`): the ledger used to
record failures only, so a clean run was indistinguishable from a never-ran
job without raw-log archaeology. Success writes the heartbeat mechanically,
so the dashboard's heartbeat-first evidence ladder is enforced by the
runner, not by the model's good manners.

Three runner upgrades landed 2026-10-27 (born from the gardener's 10-24
dark run, which executed a day late on wake and escalated twice with
nothing on disk). First, a run-date convention: the runner derives
`FLEET_RUN_DATE` from the plist fire time exactly like the receipts gate
(now before the fire time means yesterday) and exports it to the spawned
agent, so report artifacts are named by run-date instead of wall clock —
a late-executing job no longer looks like a missing run. Second, a
runner-written receipt: every attempt, including prelaunch death, leaves
a dated `garden-reports/<run-date>-fleet-receipt-<job>.md` (even a
one-line failure receipt), so the nightly receipts gate never again sees
a silent dark run; the receipt is mechanical, same trust tier as the
heartbeat, never model self-reported. Third, the stub retry backs off
once before retrying (default 120 seconds, `FLEET_RETRY_BACKOFF`
overridable; 0 restores immediate retry) with a cheap DNS probe so the
retry outcome is attributable — the old immediate retry let one outage
window stub three agents on two separate nights.

## The heartbeat contract

Every fleet job must check in to a shared heartbeat ledger with a timestamp
and a job name. The watchdog opens its nightly report with that ledger: a
skipped job is the first finding, not an invisible one. The dashboard
renders the same data as timer chips, green for ran-within-window, grey for
loaded-but-never-fired, red only for genuinely overdue.

## The receipts gate: artifact existence, not job say-so (added 2026-10-17)

A heartbeat proves a job started; a job's own status line proves only that
the job says so. The receipts gate closes both gaps: each nightly job's
OUTPUT is a known artifact (the docs-watch diff, the gardener report, the
watchdog report, the backup archive, the KB sync diff, the dream report),
and one launchd gate checks each artifact's existence and parses cleanly
before the morning brief reads anything. A job that died mid-run leaves a
receipt gap, and the gap itself is the alarm — the same inversion as the
heartbeat, one layer deeper. This gate absorbed the dreamer's
report-existence tripwire as one of its checks rather than letting it ship
as a separate guard.

## The resume clobber (2026-10-19) and the write rule

Resuming an old session made the harness rewrite the project's scheduled
tasks file from the resumed session's own state — silently dropping every
durable task other sessions had created. Eight of nine fleet tasks died at
once, and the first thing that noticed was the next morning's missed
firings. Two rules came out of it. Scheduled tasks are created and deleted
only through the cron tools, never by writing the file directly: a direct
write is what made the clobber invisible and non-atomic. And a rearm check
compares the task's own age (five days) before re-creating it, so a fresh
task is never churned by a job running on schedule.

## The zero-LLM rule for machine-only work (added 2026-10-11)

Jobs that need no judgment (snapshotting, scoring, reporting) no longer
spawn a model at all: one bash wrapper runs five python scripts in sequence
and logs to a single file. The fleet's fixed nightly cost stopped growing
when the frontier stack landed, because its jobs were born zero-LLM.

## The morning brief

One digest, under 40 lines, written at 07:13: the machine heartbeat first (a
skipped nightly job is the headline), bus threads with patterns before solo
findings, the dream verdict, watchdog P1s, Jira movements, and repo commits
from the last 24 hours, plus the last two days of dropped sessions (work
left mid-flight by a crashed or hard-killed session, with what to absorb
before continuing it). Empty sections say "nothing" instead of padding.
The design constraint is respect for the reader's morning: if you read one
thing before coffee, read this, and it will tell you what the machines did,
what they found, and what they need from you.

Verdict: a nervous system that only works while someone is watching it is a
demo; this one works the night shift and files its own attendance sheet.
