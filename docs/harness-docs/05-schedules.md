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
| 22:07 | KB digest (launchd, unattended) | per-agent briefs: what changed, live lens queries per agent's domain — every agent opens its night knowing what moved |
| 22:15 | Docs crawler (launchd, unattended) | first poster: platform documentation and status page deltas |
| 22:31 | Docs crawler summary | folds deltas into the bus and the gardener's report |
| 22:43 | Brain gardener | curates knowledge, posts stale-claim findings |
| 23:13 | Workato watchdog | posts connection health, stalls, autopsies; opens with the heartbeat check |
| 23:33 | Harness backup | snapshots the whole harness, secrets redacted |
| 23:43 | Harness dreamer | reader-in-chief: merges the night, writes the dream report |
| 00:37 | Project dreamer | architecture dreamer for one project per night (deep pass Sundays): mines the project's sessions, memory, repo, and git; dissenter-gated proposals |
| hourly | Hidden lane (launchd) | headless mini-mines and the cortex pulse, silent unless there is new signal |
| Mon 06:07 | Corpus indexer | recipes and task counters, development and production |
| Mon 06:27 | Board minutes (fleet job) | renders the dreaming team's week through the sanitizer and publishes a reviewable draft page in the team space |
| Mon 06:37 | Estate architect | full weekly estate review |
| 00:13 | Regression harness | runs every recipe's test cases through the Test Automation API, reports failures with job IDs |
| 07:13 | Morning brief | one digest: machine heartbeat, bus patterns, dream verdict, watchdog P1s, Jira moves, repo commits |

## Schedule mechanics

The schedules are launchd plists and self-rearming session crons. Recurring
scheduled tasks expire after seven days by platform design, so every job
re-creates its own schedule before expiry lapses; the fleet launcher keeps
per-job prompt files, locks, timeouts, and logs. Durable scheduled tasks
only fire while a session is open and idle, so the parts that must run
unattended (the crawler, the hidden lane) are launchd jobs that need no
session at all.

## The heartbeat contract

Every fleet job must check in to a shared heartbeat ledger with a timestamp
and a job name. The watchdog opens its nightly report with that ledger: a
skipped job is the first finding, not an invisible one. The dashboard
renders the same data as timer chips, green for ran-within-window, grey for
loaded-but-never-fired, red only for genuinely overdue.

## The morning brief

One digest, under 40 lines, written at 07:13: the machine heartbeat first (a
skipped nightly job is the headline), bus threads with patterns before solo
findings, the dream verdict, watchdog P1s, Jira movements, and repo commits
from the last 24 hours. Empty sections say "nothing" instead of padding.
The design constraint is respect for the reader's morning: if you read one
thing before coffee, read this, and it will tell you what the machines did,
what they found, and what they need from you.

Verdict: a nervous system that only works while someone is watching it is a
demo; this one works the night shift and files its own attendance sheet.
