---
name: grill-gate
description: Use when starting the planning or brainstorming phase of any build or design task. If requirements are clear, bypass and proceed. If anything is directionally unclear (goal, scope, approach, audience, priority, done-criteria), grill first before designing.
---

# Grill Gate

## Overview

The grill is one focused interrogation pass before planning work starts. Its two rules:

1. **Self-answer first.** Any question answerable from the repo, docs, ticket, knowledge tree, prior session artifacts, or a tool call gets ANSWERED, never asked. Cite the source (file:line, doc, tool response). For Workato platform questions, self-answer from the `workato-kb` skill (local RAG++ over all Workato docs + BT Confluence) before asking Josh — a KB query with a cited URL is an answer, not a question.
2. **Ask only what is genuinely Josh's call** — business decisions, priorities, taste, external facts, sign-offs. Every question ships with a recommended answer so a one-word reply moves the session forward.

## The Gate

Before planning, state the requirement in one sentence: goal, scope, done-criteria.

- **Can state it cleanly and no directional choice is open** → requirements are clear. Say "requirements clear, bypassing the grill" and proceed. Do NOT grill to seem thorough.
- **Any part is directionally unclear** (the goal could reasonably mean two different things, scope is undefined, approach changes the answer) → run the grill. "Clear enough" without the one-sentence statement is a rationalization, not clarity.

## Prior-art sweep (required before designing anything new)

Before proposing a NEW mechanism (script, ledger, hook, skill, suppression
logic, state store), search for existing prior art and propose reuse first
(Josh ruling 2026-10-08): the knowledge tree (`INDEX.md` + relevant domain
files), installed skills, existing ledgers under `~/.claude/knowledge/`,
and live recipes. If something covers 60%+ of the need, the design is
"extend it" with the delta named — never a parallel rebuild. Name what you
searched and what you found (or "no prior art") in the plan.

## Running the Grill

- First mine every answerable question yourself (context exploration, docs, the workato-kb KB, tickets). Track what you found and where.
- **Test each self-answer before trusting it** (deep-grill's move): face it with the strongest objection and one concrete failure scenario; revise or reject weak answers rather than shipping them as facts.
- Ask the remainder in ONE batched round, not a drip feed — each question with your recommended answer and the reason. Josh corrects or says "yes" once.
- **Reopen on answers** (deep-grill's iterate-to-alignment): after each round, revisit the affected and newly-exposed questions the answers create; issue another batch if material choices remain, until the review converges.
- Cap the batch at the questions that change the design. If nothing survives mining, there is no batch — proceed.
- Never ask what the ticket/spec already states. Never invent business rules to fill a gap (that is a stop-and-ask, not a guess).

## Common Mistakes

| Excuse | Reality |
|--------|---------|
| "I'll ask questions as I go" | Drip-feed questions burn turns and fragment the design. Batch the grill. |
| "I should confirm to be safe" | Confirming what the repo already answers wastes Josh. Self-answer it. |
| "Requirements seem clear enough" | Clear means you can state goal/scope/done-criteria in one sentence. If you can't, grill. |
| "I'll pick the sensible default silently" | Silent directional picks are the failure this skill exists to stop. Surface the choice with a recommendation. |
| "Every question deserves asking" | Questions that don't change the design are noise. Cut them. |
