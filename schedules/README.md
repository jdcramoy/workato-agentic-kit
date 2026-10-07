# Schedules

The agents and scripts run on these cadences. Two install paths:

## launchd (script-only jobs; runs with NO session open)

    ./install-launchd.sh

Also installs `com.josh.dream-mini` (the hidden lane): every 3h, headless,
silent unless there is new signal since the last run (new corrections or
unanswered dreamer handoffs) — then a bounded mini-dream via `claude -p`,
output only to knowledge/dreams/ + the bus.

    ./install-launchd.sh

Installs `com.josh.workato-docs-watch` (docs crawler, daily 22:15). The
crawler is pure python + network, needs no permissions, safe unattended.

## Claude Code scheduled tasks (agent jobs; fire while a session is idle)

The agent jobs (brain gardener, watchdog, corpus indexer, estate architect)
need MCP tools, so they run as Claude Code scheduled tasks in your default
work project. Create them by telling Claude in that project:

> Create a durable recurring cron task: cron `43 22 * * *`, prompt:
> [paste brain-gardener-nightly prompt from this folder]

Each template file in this folder is the exact prompt. Every task is
self-rearming (re-creates itself before the 7-day scheduler expiry) and
appends to the heartbeat log the watchdog checks.

| Cron | Job | Template |
|---|---|---|
| 22:31 daily | docs crawler summary | docs-watch-nightly.txt |
| 22:43 daily | brain gardener (incremental) | brain-gardener-nightly.txt |
| 23:13 daily | workato watchdog (+ heartbeat check) | workato-watchdog-nightly.txt |
| Mon 06:07 | corpus indexer | corpus-indexer-weekly.txt |
| 23:33 daily | harness backup (git, secrets redacted) | harness-backup-nightly.txt |
| 23:43 daily | harness dreamer (mine + report + proposals; trust ladder) | harness-dreamer-nightly.txt |
| 07:13 daily | morning brief (machine + bus + dream + Jira + repos, one digest) | morning-brief-daily.txt |
| Mon 06:37 | estate architect | estate-architect-weekly.txt |

Promotion prep is ON-DEMAND (batches are inventory-driven, not
calendar-driven): say "prepare a promotion batch" when /promotion-ready
shows enough.


## Nightly order (matters: gossip bus)

docs-watch 22:15/22:31 (first poster) → brain gardener 22:43 → watchdog
23:13 → harness backup 23:33 → dreamer 23:43 (reader-in-chief). Estate
architect runs Mon 06:37 and reads the week. Each agent appends only to its
own outbox (`knowledge/dreams/bus/<agent>.jsonl`); the dreamer merges and
synthesizes. Protocol: knowledge/dreams/GOSSIP.md.
