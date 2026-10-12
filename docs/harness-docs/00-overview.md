# The Agentic Workato Harness: a self-improving development organism

Repo: https://github.com/Workato-All/workato-agentic-kit

## What it is

A development harness wrapped around Claude Code that turns AI-assisted
Workato development from "a smart intern with amnesia" into a compound
asset. It is built from these layers:

- **Enforcement mods** that make the standing rules mechanical.
- **Playbook skills** that pass everything already learned into every new session.
- **A Developer API wrapper** for the operations the platform tools do not expose.
- **Watcher agents** that inspect the estate on a schedule and corroborate each other over a shared message bus.
- **A curated knowledge system** that captures lessons and re-verifies them against live platform behavior.
- **A promotion pipeline** that turns tracked dev work into governed production releases.
- **A nightly dreamer** that mines every session transcript to improve the harness itself.
- **A RAG++ knowledge base** over all Workato documentation with a fractal memory layer: one self-similar schema at every scale, zoom retrieval answers memory questions at 10-30x less context, and it drills to exact evidence on demand.
- **A science layer** for the dreaming team: prediction-error protocol, neuromodulation, per-agent calibration, an adversarial dissenter triad, and counterfactual rehearsal.
- **The newest layer** (added 2026-10-11) turns the fleet from observers into an economy: an offline digital twin of the whole estate, proof-carrying claims, a denominator for every "done", a calibration ledger that measures trust instead of declaring it, standing orders that let the human legislate once instead of adjudicating forever, and a chaos canary that rehearses failures against the twin.

**Why fractal memory matters (the case in numbers):** before it, a question
paid for a whole file even when one section answered it: 2-10K tokens per
memory look-up. The fractal ladder answers at the coarsest level that's
correct (~300-500 tokens) and drills only when a decision needs the detail:
10-30x less context per memory question, with provenance (the exact evidence
line) one drill away. The single schema at every scale means one tool set
serves all of memory: the same zoom works on a transcript line, a knowledge
file, a claim, or a docs page, and the coverage auditor makes completeness
a checked fact instead of a hope. Brains organize memory this way (the same
code recurs at every scale, retrieval zooms by cue); the harness version is
queryable at any depth instantly, which is where it beats biology.


The design goal, stated once and repeated everywhere: no rule should
depend on memory, no failure should depend on luck, and no knowledge
should live only in one session's context.

## Why it exists

Every team adopting agentic development hits the same three failure
modes, and this harness exists because we hit all of them:

1. **Rules that live in memory.** A governance rule written in prose is a
   wish. The agent that "knows" the rule on Monday skips it on Thursday
   under time pressure. So the rules that matter became code: hooks that
   redact secrets, gate production writes, require story points, and
   block risky pushes regardless of what the model remembers.
2. **Failures that live in luck.** Without enforcement, "the agent
   forgot" and "the connection got broken silently" are the same thing.
   So every mutating action is ledgered, every pushed recipe is
   snapshotted to git, every scheduled job leaves a heartbeat, and a
   watchdog checks the checkers.
3. **Knowledge that dies with the session.** The most expensive thing in
   agentic work is re-learning a platform bug the team already paid for.
   So lessons are captured as playbook skills and structured claims with
   evidence and last-verified dates, and a curator agent re-verifies them
   as a side effect of real work.

## What it does

| Layer | When | What it does |
|---|---|---|
| Enforce | always on, every tool call | Two mods hook every call: secret redaction, production-write audit and confirm gates, push risk scoring, Jira story-points gate, asset URL linking, build ledger, recipe snapshots. Rules that used to live in instruction files are now code. |
| Know | every session | Playbook skills load years of confirmed platform behavior: the AIRO trap catalog and the governed delivery lifecycle. A session starts warm, not blank. |
| Watch | nightly | Scheduled agents inspect the estate: broken connections with blast radius, stalled schedulers, failed-job autopsies, platform release notes, weekly cost and zombie reviews. Each run leaves a heartbeat; the last job of the night checks the others. |
| Learn | nightly and weekly | A curator agent reviews the knowledge base for drift, conflicts, and rot, mines session transcripts for unrecorded lessons, measures the harvest rate, and files proposals as git branches. Behavioral claims get re-verified as a side effect of real work. |
| Operate | any time | The `wt` CLI wraps the Workato Developer API for what the platform tools do not expose: manifests, packages, recipe lifecycle, job reruns, connection CRUD, property upserts, plus full API self-discovery (302 endpoints across 32 groups harvested from the docs). |
| Promote | on demand | A promotion orchestrator assembles batches from the build ledger, files the deployment story with real field IDs, and stages production execution behind explicit approval, one stage at a time. |
| Model | per agent, always on | A multi-model gateway layer: every agent runs on a pinned model family chosen from a benchmarked roster (a bench script with a ledgered eval keeps the verdicts honest), and a surgical fusion command cross-checks any hard-to-reverse decision across model families before the human signs. |
| Prove & predict | nightly | An integrity mesh requires a re-fetchable receipt behind every claim and reconciles claims against live external state nightly; a denominator oracle turns "it ran" into coverage arithmetic; a precursor radar mines health history for failure precursors; a calibration ledger scores every agent's predictions (Brier) so trust is measured, not declared. |
| Dream | nightly | A backup job snapshots the whole harness (secrets redacted) so agent-made changes are reversible, and two dreamers read the record: the harness-dreamer mines recent transcripts for corrections, repeats, and recurring errors, and the project-dreamer (00:37 nightly) studies the busiest project's actual architecture and proposes what it should become. Both report and propose under a trust ladder, gated by the dissenter, and their queues are reviewed in one pass through the /proposals command. The agents talk over a race-free gossip bus; the dreamers read the whole night and synthesize it last. |

## The agents, as anatomy

| Organ | Agent | Function |
|---|---|---|
| memory consolidation | brain-gardener | curates, dedups, harvests knowledge; audits structure (size budgets, modularization); proposals as branches |
| proprioception | workato-watchdog | the body's status: connections, stalls, failures, external edits, heartbeat checks |
| surveying | estate-architect | weekly estate review: cost heatmap, zombies, environment parity, lineage, security posture |
| motor planning | promotion-orchestrator | batches dev work into governed production releases |
| imagination | harness-dreamer | mines transcripts, writes the nightly dream report, proposes under a trust ladder |
| project architect | project-dreamer | the nightly dreamer for the projects themselves: architecture debt, features, better solutions; dissenter-gated; advisory-only constitutional |
| immune system | dissenter | adversarial review: attacks every proposal before it reaches a human |
| the brain | cortex | attention, coherence, curiosity: reads everything, asks the questions nobody is asking, directs the network's focus |
| testimony | evidence | the claim hunter: finds "done/fixed/verified" statements from the last 24 hours and re-checks each against live evidence; FALSE claims get a dissenter review |
| spec distiller | spec-distiller | writes the build spec (goal, scope, verifiable acceptance criteria) BEFORE any build starts; advisory only |
| technical writer | librarian | the first producer: consolidates docs, procures external content on a beat list, writes position pieces collaboratively with the dissenter |

No agent mutates the estate or the knowledge base on its own authority.
They report, propose, corroborate, and challenge each other; a human
approves anything that touches production or the harness itself. The
escalation path is explicit: the watchdog finds, the gardener verifies,
the dissenter attacks, the dreamers propose, the cortex attends, Josh
decides, and `/proposals` is the one pass where those decisions happen.

## Why it matters

The point is not automation for its own sake. The point is what agentic
Workato development feels like when the harness is running:

- **Faster**: a session that loads the playbooks starts with years of
  confirmed platform behavior instead of rediscovering known silent
  failures the expensive way. Builds that used to spend hours on
  platform gotchas now spend that time on the actual problem.
- **Smarter**: the agents see the whole system. One agent's finding
  becomes every other agent's context through the gossip bus, and
  corroboration turns single observations into patterns worth acting on.
- **More accurate**: claims about platform behavior carry evidence and
  last-verified dates, and are re-stamped by real work. Stale knowledge
  is detected, not discovered by production incident.
- **Tighter tolerance**: the rules that matter are enforced by hooks,
  not remembered. Production writes are gated fail-closed. Every pushed
  recipe is a git snapshot. Every scheduled job leaves a heartbeat.
- **Self-improving, with a human in the loop at the right altitude**:
  the harness watches itself, learns from every session, and proposes
  its own improvements. How much it may do without asking is governed by
  a trust ladder that Josh controls, and by blast radius: knowledge
  updates can be automatic, dev fixes can be automatic at the top rung,
  and changes to the harness itself are proposal-only forever.

The harness runs agentic Workato delivery end to end: build in dev with
enforced rules, verify against live traces, assemble governed promotion
batches, smoke-test production, and learn from every step. It was built
in the open, by a human and agents working together, and the agents
improved it while building it.

## Trust model in one paragraph

The mods run with your permissions and are not sandboxed; every hook
declares the events it handles and `claude plugin validate` prints every
call before you install. The production-write confirm gate fails closed:
a dismissed dialog blocks the command. The agents are read-only against
Workato; production import steps run only on explicit approval, one
stage at a time; knowledge mutations land as proposal branches. The
dreamer's trust ladder is enforced by config, and its never_auto list
(skills, hooks, mods, agents, settings, crons, MCP config, commands)
cannot be auto-applied in any mode. Rollback for the whole kit is three
commands, and a nightly backup (secrets redacted) makes every
agent-applied change a `git revert` away.

## The child pages

1. [The agents: a nervous system of specialists] and how they validate and challenge each other
2. [Skills: knowledge that loads into every session]
3. [Enforcement mods: rules as code]
4. [Memory and the knowledge base architecture]
5. [The nightly machine: schedules and the morning brief]
6. [The gossip bus: how the agents talk]
7. [The dreamer and the trust ladder: self-improvement with a human in the loop]
8. [The Workato KB: RAG++ over all documentation, and the dreaming team]

Verdict: this is a working system, not a proposal. It runs nightly, it
documents itself, and every layer of it exists because a specific
failure taught the team why that layer was needed.
