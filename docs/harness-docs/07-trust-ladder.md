# The dreamer and the trust ladder: self-improvement with a human in the loop

Parent page: The Agentic Workato Harness

This is the layer that makes the harness compound instead of decay: it
watches itself, learns from every session, and proposes its own
improvements, with the amount of autonomy explicitly governed and the
blast radius deciding where the human sits in the loop.

## How the harness records itself

During the day, everything is captured: the mods ledger every mutation,
telemetry logs every call, and session transcripts record the full
conversation. At night, the dreamer reads all of it.

## The dreamer's two mandates

**Pragmatic**: evidence-cited findings for four questions. What is the
human working on, what is being repeated, what are the frequent mistakes,
and what would have made yesterday faster. Every finding cites a
transcript, a ledger line, or a count. The first three-day mining run
covered 42 sessions and 11,000 turns and surfaced 6 correction patterns.

**The vision**: the richest member of the fleet is the dreamer who sits
back and dreams about what is to come. Every night leaves at least one
forward-looking seed (what the harness becomes in 3 to 12 months, what a
fleet of agents plus a hundred sessions a week makes possible that nobody
is doing). No evidence requirement; the quality bar is "would this make
the reader think differently". Visions mature down a pipeline: vision,
then invention, then proposal, then skill.

## The trust ladder

How much the dreamer may do without asking is enforced by a config file it
must read first every run. Upgrading or downgrading is one command.

| Mode | What the dreamer may do |
|---|---|
| report | Write the dream report. Zero writes outside the dreams directory. |
| propose | Also file proposals. Nothing is applied; a human reviews. |
| auto-safe | Also auto-apply knowledge-file deltas, index lines, memory pointers, and claim verifications only. |
| auto-dev | Also bounded dev fixes: development-estate edits, stop/start/test, test-case runs, status comments. Mandatory snapshot, edit, test, verify, ledger; any failure reverts and downgrades to a proposal. Capped at three fixes per night. |

**never_auto is constitutional in every mode**: skills, hooks, mods,
agents, settings, schedules, MCP config, and commands are proposal-only
forever, no matter how safe an individual change looks. The only way to
change that list is for a human to edit the config directly.

## The human review surface: /proposals

Proposals accumulating in a queue nobody reviews would just be a slower
way to drift. The review surface is one command, `/proposals` (the silver
platter), which covers BOTH dreamers: the harness-dreamer's harness
improvements and the project-dreamer's architecture and feature
proposals. One interactive pass renders every pending proposal as a
decision card: slug, kind, risk, source dreamer, age, the proposal's own
value case, its strongest evidence ref, and blast radius for anything
touching a live Workato asset. Oldest first, so stale proposals get
decided or die.

Verdicts are collected in one batched pass, four proposals at a time:
**approve** (queued for build), **build now**, **reject** (the note is
the taste signal), or **defer** (untouched, re-offered next time). Every
verdict is recorded mechanically: a recorder script stamps the proposal
and appends the outcomes log that the gardener's meta-improvement phase
reads, so acceptance rates per proposal kind are measured, not remembered.

Two semantics matter. First, "build now" on a harness item is the approval
that unlocks a never_auto item for that one build, stated as it happens;
on a project item it executes only the bounded first move, and anything
touching UAT or production keeps its standing sign-off gate. Second,
rejections teach: when three or more rejections share a reason, the
pattern goes back to the dreamers' bus thread as taste, which is how the
proposal quality improves week over week.

The suggested cadence is earn-then-extend: run report for a week and read
the reports, upgrade to propose and review the proposals for another week,
then decide on auto-safe. The destination rung, auto-dev, exists and is
defined, and only a human can switch it on.

## Why autonomy scales with blast radius

The ladder is not a single yes-or-no switch because risk is not uniform.
A stale claim getting its last-verified date bumped is cheap and reversible;
a hook that gates production writes must never be changed by the thing it
gates. So autonomy is granted in bands: knowledge updates (low blast
radius) can go automatic first, development-estate fixes (contained by the
dev environment and the snapshot-verify cycle) next, and the harness
itself (the highest blast radius) is permanently human-gated. Every
applied change lands in the nightly backup, so anything the machines did
overnight is one `git revert` away from undone.

## The hidden lane

The dreamer's full report is nightly, but signal does not wait politely
for 23:43. A headless mini-runner fires hourly with a silence contract:
it exits without a trace unless there is new signal (new correction
patterns, or unanswered handoffs on the bus), and even then it writes a
bounded seed note, never a proposal, never a surface. The morning brief is
the only place mini-findings appear. The humans turn around and live their
day; the machines stay hidden and leave a note on the fridge.

Verdict: a self-improving system with no governor is a liability with
momentum, and one with a human approving every line is an assistant that
never gets faster. The trust ladder is the working compromise: the harness
earns autonomy band by band, and the constitution makes the important
lines uncrossable by configuration alone.
