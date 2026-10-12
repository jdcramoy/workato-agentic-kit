---
name: handoff
description: >-
  Write or update a resumable handoff for the current work — the artifact
  that lets a future session (or a teammate) pick up exactly where this one
  left off without re-deriving state. Use at the end of any multi-session
  Workato/Workday build, debugging session, or investigation, whenever asked
  to "write a handoff", "document this", "summarize for next time", "update
  the knowledge doc", or when a session is winding down on work that isn't
  fully finished. Produces: what was touched (with full clickable Workato
  URLs), exact current state, what's verified with evidence, what's blocked
  and on whom, and the exact next command to run — then drafts any
  Jira/Confluence artifact for approval before posting. Prefers updating an
  existing master doc over spawning another dated handoff file. Distinct
  from workato-skill-builder's Promotion Handoff (that's a narrower,
  UAT-passed-and-ready-to-promote block) — this skill covers the general
  case, including work that isn't done yet.
---

# Handoff

The deliverable in this project is usually working infrastructure *plus* its
paper trail — a recipe that runs is only half done until the next session (or
teammate) can resume without re-discovering what state it's in. This skill is
that second half, made repeatable.

## Before writing anything: check for an existing master doc

Multiple dated handoff files for the same project is a known failure mode
here — `HR-Genie-Master-Knowledge-Doc.md` exists specifically because five
earlier dated handoffs (`BSYS-26808-handoff-2026-07-16.md`,
`PTO-platform-session-handoff-2026-07-23.md`,
`HANDOFF-PTO-Notifications-BSYS-26808.md`, etc.) fragmented into overlapping,
partially-stale copies.

- If a `*-Master-Knowledge-Doc.md` or similarly-named consolidated doc already
  covers this project/epic, **update it in place** — add or revise the
  relevant section, don't create a new dated file next to it.
- Only create a new handoff file when no consolidated doc exists yet for this
  line of work. If this is the third or later handoff for the same
  project/epic, that's the signal to consolidate into one master doc now
  (as `HR-Genie-Master-Knowledge-Doc.md` did) rather than adding a sixth file.

## What goes in it

1. **Assets touched** — every recipe/skill/Genie/data table/folder, each with
   its full clickable Workato URL (`asset_url_get`), per the always-link rule
   in `CLAUDE.md`. No bare IDs.
2. **Exact current state** — running or stopped (ask the user to confirm;
   there's no stop/start tool, see `CLAUDE.md`), pushed or not. (VUA
   connection re-selection after push is retired — that bug was fixed
   2026-08-20; connections persist across pushes.)
3. **What's verified, with evidence** — pull straight from a recent
   `verify-recipe` pass/fail table if one exists this session: job IDs, trace
   lines, what passed, what's still unverified. Don't restate a claim here
   without the evidence that backed it.
4. **What's blocked, and on whom** — a permission wall, a pending admin
   response, a decision the user needs to make. Name the specific blocker,
   not "waiting on access."
5. **Exact next command** — the literal next tool call, recipe ID, or
   question to resume with. Not "continue the investigation" — the actual
   next step, ready to execute cold.
6. **Mission-control registry row (Josh, 2026-10-11, NEVER skip for build
   sessions)** — after writing the handoff, record the workstream state:

   ```
   python3 ~/.claude/knowledge/scripts/mission-control.py add \
     --event closeout --workstream <slug> --project <project> \
     --jira <KEY or ""> --jira-title "<title or "">" \
     --what "<plain English: what was done>" \
     --why "<why it was done>" --end "<to what end>" \
     --needs "<what Josh must decide/provide, or "">" \
     --state in-flight|needs-josh|blocked|done --by "josh (session)"
   ```

   The what/why/end fields are PLAIN ENGLISH — written for a smart colleague
   who knows neither the recipe IDs nor the jargon. A fragment or a jargon
   string is refused by the script. State `needs-josh` REQUIRES a concrete
   `--needs` sentence. This row is what the cortex, the morning brief, and
   /today read — it is how Josh tracks parallel sessions without reading
   their transcripts.

## Format

```markdown
# <Project/Epic> — Handoff (<date>)

## Status
<one line: what's done, what's in flight>

## Assets
- Recipe: <name> — <full Workato URL>
- Genie: <name> — <full Workato URL>
- Data table: <name> — <full Workato URL>

## Current state
- <recipe name>: running/stopped, last pushed <when>

## Verified (with evidence)
- <assertion> — job <id> (<full job URL>): "<quoted trace line>"

## Blocked
- <specific blocker> — on <who/what>, unblocked by <what>

## Next step
<the exact next command/call/question>
```

## Filing it

- **Architecture diagram (auto-step):** if Workato/repo assets changed this
  session, invoke the `arch-diagram` skill now (or confirm the project's
  `knowledge/projects/<slug>/architecture/` maps are already current) before
  closing the handoff. A handoff that leaves a stale architecture diagram
  behind is incomplete.

- Save the doc locally (update the master doc, or create the file if none
  exists yet — see above).
- If a Jira ticket or Confluence page tracks this work, **draft** the
  comment/page content in the actual markup (remembering the Atlassian
  markdown `#`-renders-as-H1 gotcha in `CLAUDE.md`) and show it for approval
  before posting — don't file it silently. Draft it through the
  `josh-writing-voice` skill: it publishes as Josh, so first person end to
  end, no fleet/process framing (Josh 2026-10-10, BTSUP-78227).
- If a Slack handoff message is warranted, draft it with
  `slack_send_message_draft` rather than sending, unless the user has already
  said to send.

## Relationship to the Promotion Handoff

If this work is a Workato skill build that has passed UAT and is ready for
prod promotion, use `workato-skill-builder`'s **Promotion Handoff** block
instead (or in addition, as the "Next step") — it's the specific,
narrower artifact for that one moment. This skill is for the general,
ongoing case, including work that's still mid-flight.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [HR Genie — Architecture Map](../../kb-corpus/confluence/extbt/2939977789-hr-genie-architecture-map.md)
- [BT: RunOps Genie Roadmap | Phase 1 and 2](../../kb-corpus/confluence/extbt/2853470244-bt-runops-genie-roadmap-phase-1-and-2.md)
- [Adding specialist Genies and MCPs to Multi-Genie Orchestration](../../kb-corpus/confluence/extbt/2872377507-adding-specialist-genies-and-mcps-to-multi-genie-orchestration.md)
- [Lead Genie V3 Implementation Audit Report](../../kb-corpus/confluence/intbt/2685468700-lead-genie-v3-implementation-audit-report.md)
<!-- kb-bridges:end -->
