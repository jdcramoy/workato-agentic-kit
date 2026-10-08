# Skills: knowledge that loads into every session

Parent page: The Agentic Workato Harness

A skill is a procedure file that loads into a session on demand. The design
goal: a session that needs to do governed Workato work should start with
years of confirmed platform behavior instead of a blank slate. Skills are
how the harness compounds; every confirmed trap becomes a line in a skill,
and every future session gets it for free.

## The two playbook skills

**airo-mcp-playbook** is the trap catalog for Workato's platform MCP. It
carries confirmed silent-failure bugs (data table column updates that wipe
rows, dynamic table IDs that drop payloads, datapill exports that render
mapped values as if they were hardcoded, session ID collisions, connection
reverts after pushes), Ruby restrictions inside recipes, Jira formatting
traps, and token-efficiency practices. The catalog exists because each of
those bugs cost a real debugging session before it was understood; the
skill-load is what keeps an AI-assisted build from rediscovering them the
expensive way.

**workato-development-playbook** is the delivery lifecycle for governed
Workato work: the actor model (human authority, agent coordination,
execution surfaces), the orient-and-contract phase, implementation and
whole-graph audit, acceptance and regression, evidence standards, and
promotion readiness. This is the process the watchdog and the promotion
orchestrator assume.

Both skills use progressive disclosure: the main file stays lean and
readable in one pass, and deep reference material lives in reference files
loaded only when the work calls for it. A skill's description field is its
routing surface: it says when to use the skill, so the right playbook loads
at the right moment without anyone remembering to load it.

## The supporting cast

Around the two playbooks sits a layer of procedural skills, each a
repeatable SOP extracted from real work:

- **verify-recipe**: prove a recipe works from a live job trace, with a
  pass/fail table where every row cites its evidence. No claim of "fixed"
  without a citation.
- **workato-hot-swap**: edit and redeploy a running recipe with proof at
  every step (stop via API, edit, start, verify the start actually took,
  prove with a live run).
- **uat-evidence** and **manifest-hygiene**: assemble the acceptance
  evidence block and dry-run a promotion manifest before filing it.
- **workato-autopsy**: root-cause a failed job by walking the trace to the
  origin step, not the reported error step.
- **jira-story-standards**: the story format the promotion pipeline and the
  story-points gate enforce.
- **blast-radius**: compute what breaks if an asset fails or changes,
  before touching it.
- **platform-onboarding**: cold-start the harness on a platform it has
  never seen, from API reference to first working integration with test
  cases in one sitting.
- **triage**: the interactive approval queue for discovered work. The
  watchers file evidence-backed findings (a broken thing worth fixing, a
  playbook entry worth writing, a cleanup worth doing) to a shared queue;
  this skill renders them as decision cards, collects verdicts in one
  batched pass, creates the Jira Story or Bug for approved work under the
  governing epic, and dispatches approved dev-scoped fixes with the full
  snapshot-verify-ledger cycle.

## Why skills rather than documentation

Documentation describes; skills change behavior. A skill is loaded at the
moment of need, sits in the model's context while the work happens, and
carries the traps inline next to the procedure they protect. The enforced
rules (the mods) and the playbooks say the same thing: the mods make the
rule mechanical where code can reach, and the skill teaches the reasoning
where judgment is needed.

The team knowledge angle matters most: skills are installed from the kit
repo, so every teammate's sessions load the same accumulated experience.
When one person's session discovers a new platform bug, the fix ships to
everyone as a skill update.

Verdict: skills are the difference between an assistant that is smart and
a harness that is experienced.
