---
name: jira-autotriage
description: The self-looping Jira identify-triage-investigate-plan loop. Agents AUTONOMOUSLY triage, investigate/autopsy, and technical-plan EVERY ticket in Josh's queue — Stories, bugs, BTSUP requests, anything Workato-related — in bulk. That is a standing grant: no permission asked, no cap, no Josh-decision filed for those steps. Development is Josh's gate: the loop produces a finished, build-ready plan and he approves kickoff in one word; the loop NEVER edits a recipe or remediates. Only authority items go to Josh: build kickoff on a finished plan, hotfix handling, any prod write, outward messages beyond the standing BTSUP reply, and genuine row ambiguity. Hotfixes are NEVER auto-remediated. Use for the jira-triage fleet job, or when Josh says "work the triage queue", "plan this story", or "triage the agent-triage tickets".
---

# Jira autotriage loop

Failures and feature asks arrive as work, not as sweep results. The queue is
Jira; the loop is identify → triage → investigate/autopsy → plan → hand back.
Nothing in this loop polls the Workato estate broadly without a ticket to anchor it.

## Autonomy (the standing grant — read first)

Triage, investigation/autopsy, and technical planning are **standing grants**
for **every** ticket class, at **any volume**. Josh's queue hovers around 60;
the loop grinds it down. You do not ask permission to triage a ticket,
investigate it, autopsy a failure, or write its technical plan, and you do
**not** file those steps as decisions for Josh. Do them, post the result as a
work product, and move on. Josh is not in the triage loop and does not want to
be. Asking him whether you may triage, investigate, or plan is itself a defect.

You have **all** the tools and resources for everything Workato-related: read
the estate (`wt` CLI, AIRO reads), pull job traces, run `workato-autopsy`,
search the KB (`kb`), query the WSDL/WQL indexes, read the build ledger and
corpus, read Jira in full. Use them without asking.

**Development is Josh's gate.** You do NOT write, edit, or remediate recipes —
not even in dev — until he approves a plan. Your job ends at a finished,
build-ready plan he can approve in one word. This holds until he says otherwise.

## What goes to Josh (authority, not triage)

- authorization to **kick off a build** from a finished plan (the one gate);
- any **hotfix-class** item (report and propose only, ever);
- any **production workspace write**;
- any **outward-facing message** beyond the standing BTSUP reply;
- genuine **ambiguity** about which class a ticket is (never ambiguity about the
  work — investigate and plan through that).

Everything else — classify, research, autopsy, root-cause, plan, draft,
reply — happens without him.

## The decision matrix (constitutional — the queue's only law)

| Ticket class | The loop MAY (autonomously, in bulk) | Josh's gate | The loop NEVER |
|---|---|---|---|
| **BSYS Story** (feature request) | triage; investigate; produce a technical plan (architecture, assets, contracts, risks, points estimate); post it under its epic; mark "plan ready — awaiting build authorization" | kick off the build | edit a recipe; build; treat triage/plan as a Josh-decision |
| **Bug** (any project) | triage; autopsy; produce a plan with a proposed diff and the test that would catch it; post it; mark ready | kick off the fix | auto-fix a hotfix-class bug; any dev edit without approval; any prod write |
| **BTSUP request** (service desk) | immediate triage; reply to the requester in Josh's voice; internal notes; plan if the fix is real | any dev work | dev work from BTSUP |
| **Everything else Workato** | triage; investigate; plan | kick off the build | anything outside the rows above |

A ticket that clearly belongs to no row is still triaged, investigated, and
planned — the only thing that routes to Josh is which ROW it is, and only when
that genuinely changes what happens.

## Queue discipline

- Work the **whole** open queue, not just the `agent-triage` label — but the
  queue is strictly tickets **ASSIGNED TO JOSH** (Josh ruling 2026-10-09,
  BSYS-29438: never pull in work that isn't assigned to him specifically;
  creator/watcher/mentioned/reporter tickets are read-only context, never
  queued). Query definitions with the exact assignee filter live in
  `QUEUE-DEFINITIONS.md`.
- Priority order: customer-facing and high first, then aging, then background.
- No artificial cap. Work as many tickets as the pass budget allows, ticket by
  ticket, one at a time.
- Read the FULL ticket including comment history before acting.
- Josh's Jira standards apply to anything created or restructured (sections,
  story points at creation, never the Deployment Request type, parent linkage).

## Project grouping (Josh rule)

Work products cluster under their governing project/epic, not loose:
- Plans, investigation notes, and evidence live in
  `knowledge/projects/<epic-or-project>/` (create the folder if the ticket
  doesn't map to an existing grouping — do not invent a flat home).
- Jira-side: stories link to their governing Epic via parent; if a Story has
  no plausible Epic and one is genuinely needed, propose it, don't file it.
- Sessions/agents working a project read from and write to that folder, so
  context compounds where the work lives.

## The loop (per ticket, in queue order)

1. **Identify.** Read the ticket fully. Classify. If it matches no row, one line
   to the report and move on.
2. **Act within the matrix — no permission needed:**
   - **Story / bug / other** → research the ask (estate assets, claims, corpus,
     blast radius), autopsy if it's a failure, and draft the technical plan
     autonomously; post it in the ticket comment and under
     `knowledge/projects/<epic>/`, in Josh's standards format. End the comment
     with "plan ready — awaiting Josh's authorization to kick off the build".
     The plan is a finished work product; the triage and the plan are not his to
     approve.
   - **BTSUP request** → triage against live evidence (check the thing, don't
     guess), reply in Josh's voice with the customer register, leave internals as
     an internal comment. Still no dev work.
   - **Hotfix-marked bug** → autopsy and propose only; lead the comment with
     "not auto-remediated: hotfix class".
3. **Learn.** Canonize failures, append earned capabilities, note the taste
   signal (what Josh approved or rejected) for the dreamer.
4. **Comment markup is MARKDOWN, never Jira wiki notation.** Comments post
   via the Atlassian MCP with contentFormat=markdown: headings are `## Text`
   / `### Text` (never `h2.` / `h3.` — that renders as literal text), lists
   use `-`, bold is `**bold**`. h2./h3. notation is Jira SERVER wiki style
   and is wrong here — it has shipped broken comments (BSYS-28296, 2026-10-09).
4. **Hand back.** Every comment ends with what's verified, what's pending, and
   the next step. Quiet queue = one line, exit.

## Triage findings (only AUTHORITY items, one place)

Most passes file nothing. File a finding only for the authority items above —
a plan ready for kickoff (low urgency; Josh batch-approves), hotfix class, a
prod write request, outward messages beyond the standing reply, and inbound
attention (new comments or aging on tickets ASSIGNED to Josh; new tickets
assigned to Josh — the assignee filter is a hard gate, see
`QUEUE-DEFINITIONS.md`). A triage or a plan is NOT itself a finding.

    echo '{"ts":"<now UTC ISO>","slug":"<kebab-slug>","kind":"bugfix|build|playbook|test|hygiene",
      "source":"jira-autotriage","jira":"<KEY>","urgency":"high|medium|low",
      "title":"<one line>","evidence":"<KEY + what changed>","work":"<the ask, one line>",
      "points":<estimate>,"status":"open"}' \
      >> ~/.claude/knowledge/triage/queue.jsonl

Dedupe against open slugs first (a ticket key already open does not get a second
finding). Status changes belong to `triage-decide.py`, never hand edits.

## Hard rules

- The matrix is the whole game. Triage/investigate/plan is autonomous for every
  class; asking permission for it is a defect.
- Development is Josh's gate — never a recipe edit, build, or remediation
  without his approval on a finished plan.
- Prod is untouched always: hook 13 + the AIRO prod gate stand.
- Customer-facing replies never carry internal IDs, job traces, or blame.
- Never transition a ticket to Done. Josh closes work, not the loop.
