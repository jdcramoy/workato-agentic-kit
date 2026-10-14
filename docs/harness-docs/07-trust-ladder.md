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

## The human review surfaces: /proposals and /triage

Two queues feed the human's decision passes, kept deliberately separate
because they answer different questions.

**/proposals** covers IDEAS: both dreamers' proposals (the harness-dreamer's
harness improvements and the project-dreamer's architecture and feature
proposals). One interactive pass renders every pending proposal as a
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

**/triage** covers DISCOVERED WORK: evidence-backed findings the watchers
file as they run (watchdog autopsies and self-heal candidates, regression
failures, the gardener's actionable hygiene items, estate-architect
recommendations, cortex work-shaped attention items), plus every Jira
attention item the autotriage loop files each pass: technical plans
awaiting authorization, hotfix-class bugs, ambiguous tickets, and inbound
signals (new tickets assigned to Josh, new comments, tickets aging
without movement).

Same pass shape: decision cards ranked by URGENCY
first, then age, so time-sensitive work never hides behind old hygiene;
batched verdicts (file story or bug, build now in dev, queue only,
reject, defer), one mechanical recorder, one summary table. Filing
creates the Jira Story or Bug immediately under the governing epic (a
certain existing epic, or a new one under the FY27 V2MOM work item),
assigned to Josh, points set at creation, the finding's evidence inline.
Build-now executes dev-estate work only, with the
snapshot-edit-test-verify-ledger cycle; UAT and production keep their
standing gates.

Rejection patterns feed a triage-taste thread on the bus,
so the watchers stop re-raising what the human already declined.

The suggested cadence is earn-then-extend: run report for a week and read
the reports, upgrade to propose and review the proposals for another week,
then decide on auto-safe. The destination rung, auto-dev, exists and is
defined, and only a human can switch it on.

## What changed since the ladder was written

**The Jira autonomy grant (2026-10-09).** Triage, investigation, autopsies,
and technical planning became a standing grant: the loop works every ticket
in the queue autonomously and in bulk, because a plan is a work product,
not an approval item. The gate moved to where the risk is: development
itself, hotfixes, and production writes stay human-gated. The queue got
smaller without the authority getting larger.

**Standing orders: legislate once (2026-10-11).** The decision inbox
exposed the real bottleneck: the human re-adjudicating the same classes of
decisions. Standing orders are the fix: a decision rule (scope, cap,
expiry, a ratchet that auto-expires on any breach) is drafted from real
decision history, attacked by the dissenter, approved once, and every
future matching decision is pre-sorted.

**The living manifest (2026-10-12).** The first standing order to run
through that pipe: every build carries an export manifest of the assets it
touches, created when the build starts and updated the moment an asset
enters it, never batched at the end. A guard hook enforces it at session
end. What started as promotion paperwork became a build-time discipline:
the manifest is how "what did this change actually touch" is answered from
the first minute, not reconstructed from memory at review time. One
carve-out followed the rule's first collision with reality (2026-10-13):
throwaway test probes, named as such, need no manifest. Only real builds
destined for promotion do.

**The red-team gate (2026-10-12).** The second: nothing reaches production
without an independent security verdict on record before the push. An
independent reviewer agent (never the builder) attacks the asset at a
depth the risk dictates, a fail blocks promotion unless the human overrides
by name, and a guard hook stops any production-bound session that ends
without a verdict. Hotfixes included: urgency changes the review tier,
never the requirement.

**Authority does not delegate downward (2026-10-12).** A batched approval
authorizes the queue, not the writes. Each individual production write
still needs first-hand confirmation in the session that fires it, because
an approval round and a production mutation are different events and
conflating them is how autonomy quietly widens itself.

The unit of interaction shifts
from decisions to policies. Three draft policies exist and await review;
the matcher only ever shows what it would do.


**Measured trust (2026-10-11).** The calibration ledger scores every
agent's falsifiable predictions (Brier), so the ladder's rungs can
eventually be sized by evidence instead of instinct: a well-calibrated
watchdog earns wider autonomy; a poorly calibrated one gets its findings
cross-checked.

The shadow estate supports this with a regret ledger:
deferred decisions are counterfactually checked against live state, so
over-caution and under-caution both become visible.

**Surgical fusion (2026-10-10).** For the decisions where a wrong answer
is expensive and subtle (production-facing, hard to reverse), a fusion
command puts the same question to several model families on the gateway
and diffs the answers before the human signs. Gated, not default: most
work runs single-model with role-routed model pins.

**The pipeline today.** The replay gym (rehearsing past incidents as
replays) is accepted and next to build; the proposal pipeline stands at 26
filed, 8 built, and an incubation queue that the new evidence and
calibration layers are designed to drain.

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
