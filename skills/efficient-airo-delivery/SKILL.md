---
name: efficient-airo-delivery
description: Use when planning, investigating, building, testing, or documenting AIRO/Workato recipes, Genie skills, MCP servers, snapshot-ledger workflows, or related Jira work. Enforces low-token evidence gathering, economical multi-agent delegation, deliberate mutation controls, saved execution plans, and milestone-only Jira updates.
---

# Efficient AIRO Delivery

## Authority

- Default to read-only discovery and planning. Do not mutate Workato, AIRO,
  MCP configuration, production data, or Jira until the user authorizes that
  phase.
- Keep the root agent responsible for architecture, security, mutations,
  acceptance criteria, and final synthesis.
- Save an approved phase plan and compact evidence log locally. Execute the
  saved plan tightly; update it before changing direction.

## Cost-aware delegation

- Always fan out independent bounded work when it reduces cost or elapsed time.
- Delegate mechanical and read-only tasks to the least-expensive capable model:
  file inventory, targeted searches, schema extraction, job-log summarization,
  latency/count tabulation, test drafting, and evidence comparison.
- Give each delegate an exact question, narrow artifact scope, concise output
  expectation, and no mutation authority.
- Reserve frontier/high-reasoning work for architecture, ambiguous diagnosis,
  security and access decisions, mutation review, and acceptance.
- Do not delegate duplicate investigations or open-ended exploration.

## Low-token AIRO workflow

- Prefer explicit asset IDs and URLs; do not rediscover known assets.
- Start with the smallest evidence set: relevant jobs, exact action timings,
  selected fields, counts, payload bytes, and snapshot version.
- Filter server-side and request compact output. Do not dump complete recipes,
  job traces, tables, or orgs into the root context when a targeted extraction
  answers the question.
- Batch independent reads. Fetch schemas or datapills once per step and reuse
  them. Reuse builder sessions until push; independently verify once after push.
- Summarize verbose results immediately into durable facts and avoid repeating
  raw payloads in user responses.
- Read [references/airo-token-patterns.md](references/airo-token-patterns.md)
  when a task needs more than a few AIRO calls or a build-test-fix loop.

## Plan and execution gates

- Every phase plan must state objective, non-goals, evidence baseline, assets,
  ordered changes, model allocation, rollback, validation, success metrics, and
  stop conditions.
- Measure the bottleneck before changing architecture. Prefer the smallest
  reversible change that removes the measured constraint.
- Preserve snapshot atomicity, current-version isolation, rollback retention,
  field completeness, and the no-request-time-Workday boundary.
- Re-read deployed state immediately before mutation.
- Run targeted comparison first, then the full regression/security/pressure
  suite only after the targeted gate passes.

## Jira

- Do not update Jira for exploration, intermediate hypotheses, each subtask, or
  routine progress.
- Honor established project issue-type conventions. Do not infer that a
  "deployment ticket" requires Jira's `Deployment Request` issue type. For
  Slack by Workato MCP, create a **Story** under the active Slack
  performance/enhancements Epic unless the user explicitly requests a
  Deployment Request or the governing workflow mandates it.
- Update only at a decision-quality milestone: approved plan, verified baseline,
  implemented-and-validated phase, material blocker, or release handoff.
- Accumulate evidence in memory/local files and publish one concise comment with
  verified facts, metrics, affected assets, rollback state, and next decision.
- All comments are Josh's prose: draft through the `josh-writing-voice` skill
  (first person end to end, no fleet/process framing, hypotheses labeled as
  guesses; Josh correction 2026-10-10, BTSUP-78227).

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [MCP](../../kb-corpus/docs/en/mcp.md)
- [AIRO -  Create your first blueprint](../../kb-corpus/docs/en/airo/blueprints/create.md)
- [AIRO - Find unused assets](../../kb-corpus/docs/en/airo/usage-inspiration/find-unused-assets.md)
- [Building a Better Gmail MCP Server with Workato](../../kb-corpus/blog/building-a-better-gmail-mcp.md)
<!-- kb-bridges:end -->
