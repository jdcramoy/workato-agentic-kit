---
name: jira-autotriage
description: The self-looping Jira identify-triage-plan-fix loop, governed by the eligibility decision matrix. BSYS Stories get research + technical plans held for Josh's authorization; BTSUP requests get immediate triage and customer-tone replies in Josh's voice; bugs assigned to Josh in BTSUP/BSYS get investigation and dev-scoped remediation; everything else is read-only. Hotfixes are NEVER auto-remediated. Use for the jira-triage fleet job, or when Josh says "work the triage queue", "plan this story", or "triage the agent-triage tickets".
---

# Jira autotriage loop

Failures and feature asks arrive as work, not as sweep results. The queue is
Jira; the loop is identify → classify by the matrix → act within the matrix →
hand back. Nothing in this loop polls the Workato estate broadly.

## The decision matrix (constitutional — the queue's only law)

| Ticket class | The loop MAY | The loop NEVER | Tone |
|---|---|---|---|
| **BSYS Story** (feature request) | auto-triage; research; produce a technical plan (architecture, assets, contracts, risks, points estimate) and post it for Josh's review | kick off or start a build without Josh's explicit authorization on the plan | planning-doc register (josh-writing-voice, doc polish) |
| **BTSUP request** (service desk) | immediate triage; reply to the requester in Josh's voice; internal notes | any dev work from BTSUP, any remediation, any build | replies: customer-focused (clear, warm, plain, outcome-first). internal comments/notes: technical register |
| **Bug in BTSUP or BSYS, assigned to Josh** | auto-triage; investigate; remediate where the fix lives in Workato AHQ \| AI **Development** (AIRO dev edits, dev stop/start/test, test cases) | hotfixes (never auto-remediated, ever — a bug marked hotfix/urgent is report-and-propose only); any prod workspace write; remediation outside the dev workspace | technical; evidence-cited |
| **Everything else** (other projects, other assignees, unlabeled) | read-only observation; a note to Josh with a recommendation | anything else | — |

A ticket that doesn't clearly match a row is "everything else" until Josh
says otherwise. Ambiguity routes to him, never to initiative.

## Queue discipline

- Bug remediation works tickets labeled `agent-triage` (humans or the intake
  recipe apply it). Planning and BTSUP replies work their classes directly.
- Read the FULL ticket including comment history before acting. Never.
- One bounded action per ticket per pass.
- Josh's Jira standards apply to anything created or restructured (sections,
  story points at creation, never the Deployment Request type, parent
  linkage).

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

1. **Identify.** Read the ticket fully. Classify against the matrix. If it
   matches no row, write one line to the report and move on.
2. **Classify + act within the matrix:**
   - **BSYS Story** → research the ask (existing estate assets, claims, corpus,
     tracker blast radius), draft the technical plan in the ticket comment
     (Josh's standards format where applicable), end with "awaiting Josh's
     authorization to kick off the build". Transition to the review state.
   - **BTSUP request** → triage the request against live evidence (check the
     thing, don't guess), reply in Josh's voice with the customer register,
     and leave the technical internals as an internal comment.
   - **Bug (Josh's, dev-fixable)** → run `workato-autopsy`; if conclusive and
     dev-scoped, fix under auto-dev rules (snapshot → edit → test → trace-
     verify → ledger), comment with evidence, transition for review.
     Verification failure = revert + the ticket gets the proposal, not the fix.
   - **Hotfix-marked bug** → autopsy and propose only; lead the comment with
     "not auto-remediated: hotfix class".
3. **Learn.** Canonize failures, append earned capabilities, note the taste
   signal (what Josh approved or rejected) for the dreamer.
4. **Hand back.** Every comment ends with what's verified, what's pending,
   and the next step. Quiet queue = one line, exit.

## Triage findings (everything that needs Josh, one place)

Every pass ends by filing what needs Josh's attention into the /triage
queue, so ONE interactive pass surfaces all of it:

    echo '{"ts":"<now UTC ISO>","slug":"<kebab-slug>","kind":"bugfix|build|playbook|test|hygiene",
      "source":"jira-autotriage","jira":"<KEY>","urgency":"high|medium|low",
      "title":"<one line>","evidence":"<KEY + what changed>","work":"<the ask, one line>",
      "points":<estimate>,"status":"open"}' \
      >> ~/.claude/knowledge/triage/queue.jsonl

What gets filed: BSYS technical plans awaiting authorization (kind build);
hotfix-class bugs (kind bugfix, report-and-propose); anything the matrix
routes to Josh as ambiguous; and INBOUND attention items found during the
sweep — new tickets assigned to Josh, new comments on his tickets, tickets
aging without movement (urgency: customer-facing or blocked = high, stale
>7d = medium, background = low). Max 5 per pass; dedupe against open slugs
first (grep the queue; a ticket key already open does not get a second
finding). Status changes belong to `triage-decide.py`, never hand edits.

## Hard rules

- The matrix is the whole game. A ticket outside the rows is Josh's.
- Prod is untouched always: hook 13 + the AIRO prod gate stand.
- Customer-facing replies never carry internal IDs, job traces, or blame.
- Never transition a ticket to Done. Josh closes work, not the loop.
