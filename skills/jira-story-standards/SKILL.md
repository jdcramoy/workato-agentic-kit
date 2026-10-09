---
name: jira-story-standards
description: "Josh's Jira standards for Epics and user Stories: required sections (Background, Business Requirements, Technical Requirements, Acceptance Criteria, UAT Evidence), story-point rules, project conventions, and the writing spirit expected"
metadata:
  type: user
---

# Josh's Jira Story Standards

Apply to EVERY Epic and Story created for Josh. Load before creating or
updating Jira work.

## Every user story MUST contain

1. **Accurate content** — the ticket describes what was actually built (or
   what is actually scoped); never aspirational filler. Cite real asset IDs,
   real evidence file paths, real job/trace identifiers where they exist.
2. **## Business Requirements** — the user-facing/business outcome bullets:
   what becomes possible, what risk it retires, what it costs less.
3. **## Technical Requirements** — the implementation substance: assets
   (with IDs/URLs), contracts, gates, rollback posture.
4. **## Acceptance Criteria** — a `- [ ]` checkbox list, each criterion
   objectively verifiable.
5. **## UAT Evidence** — an explicit place that records or links the UAT
   proof: evidence-file path, job IDs, pass/fail rows. Written even when
   UAT is pending (then it says what evidence WILL be recorded).

## Epic format (house style, matching BSYS Track-B epics)

`## Background` (why this exists, the story of the need) → `## Objective` →
`## Scope` (subsections per workstream) → `## Out of Scope` (explicit) →
`## Success Measures` (measurable) → `## Acceptance Criteria` (checkboxes).

## Story points (standing rule)

- ALWAYS set points at creation — never leave empty. On the `workato` site
  (cloudId `99bd32a1-58a6-41d6-8e61-c98194c68259`) the field is
  `customfield_10057` (number), via `additional_fields` on createJiraIssue
  or `editJiraIssue` if missed.
- Scale (1 point ≈ 1 dev day): 1 trivial config/deploy (<2h), 2 small fix
  (~half day), 3 real investigation or single skill/tool build (~1 day),
  5 = 2–3 day build with UAT (most common), 8 ≈ 1-week complex build,
  13 epic-scale, 21 program-scale. Service-desk triage: 1–2 routine, 3 real
  investigations.
- Epics get points too (13 = epic-scale typical).
- Known blocked projects — BTSUP, HROPS, PSM, MCP: the Story Points field is
  NOT on their issue-type screens; do not retry or flag as failure; note
  once and move on. BSYS, AAI, CT support the field.

## Project conventions

- **Deployment requests are NEVER the "Deployment Request" issue type**
  (Josh, 2026-10-05). Always file deployments as a **Story** (or a **Bug**
  if the deployment fixes a defect), under the governing Epic. Even when
  other tickets in BSYS use the "Deployment Request" type (10189), do not
  follow them — that type carries extra required fields (Reason for
  Change, Workato/Salesforce component) and is not our convention.
- MCP/AI-enablement build work lives in **BSYS** (supports points); Epics
  there follow the "… [Track B] — …" naming pattern for related tracks.
- Labels: reuse the epic's label set (e.g. `BT-Business-Intelligence`,
  `Data-Genie`, `V2MOM-FY27` style) on stories.
- Link each Story to its Epic (parent field); attach the milestone comment
  with verified facts only (efficient-airo-delivery's milestone-only rule).

## Status workflow (standing rule, Josh 2026-10-08)

- The moment a dev build is complete AND unit/regression tested, move the
  ticket to **UAT** — always, without being asked. Do not leave tested work
  in Backlog or In Progress.
- The BSYS workflow has no direct Backlog → UAT transition: step through
  **In Progress** first (transition id 71), then **In UAT** (transition id
  301). Verify the final status on read-back.
- Later statuses (Closed after UAT sign-off, Change Review) stay
  human-gated with Josh; only the dev-tested → UAT move is autonomous.

## Comment markup (standing rule, Josh 2026-10-09)

- ALL comments (milestone, plan, evidence, status) post via the Atlassian
  MCP with `contentFormat=markdown`, and the CLOUD renderer is standard
  markdown — Jira SERVER wiki notation renders as literal text.
- Conversions: `h2.`→`## `, `h3.`→`### `, `h4.`→`#### ` (never `h2.`-style
  headings), `{{code}}`→`` `code` ``, `[text|url]`→`[text](url)`, wiki
  `# item` numbered lists→`1.` (a bare `#` line becomes an H1 under
  markdown). Bold `**bold**`, italic `*italic*`, lists `-`.
- This defect class shipped broken comments on 6 tickets (BSYS-28296 et al)
  before the 2026-10-09 repair sweep. If a legacy comment contains wiki
  notation, fix it in place with `addCommentToJiraIssue` + `commentId`
  rather than posting a new comment.

## Writing spirit

- Write with the weight of the work: these tickets document systems meant
  to outlive the project. Prefer precise, dignified, plain statements over
  hype; capture investment and journey in the QUALITY and completeness of
  the writing, not in dollar figures or sentiment. Background sections may
  name the journey (prototypes, pivots, multi-tool development) when it
  aids the reader's understanding of scope.

## Efficiency

- Create the Epic first, capture its key, then create Stories with
  `parent` = epic key. Batch story creation; don't ask per-story.
- After creation, return one summary table (key, points, one-line).
