# Cortex coordinator — domain knowledge

The cortex is the fleet's COORDINATOR (promoted from advisory attention
agent, Josh: "Build it" 2026-10-08).

## The three parts

1. **Model routing table** — `knowledge/config/model-routing.json`:
   per job-class model choice (headless `--model` + Agent-tool alias) and
   dispatch budgets. Sweeps/lanes/briefs = glm-5.3-flash; autopsies, builds,
   reviews, judgment = kimi-k3. The pulse itself runs flash. Table changes
   are cortex proposals; Josh approves.
2. **Dispatch authority** — fleet job `cortex` (launchd com.josh.fleet.cortex,
   hourly, run-job.sh validated): up to 2 headless READ-ONLY investigations
   per pulse (`--permission-mode default`, findings to
   knowledge/cortex/investigations/<slug>.md), logged to
   knowledge/cortex/dispatches.jsonl. Actions = proposals (triage queue or
   bus), never dispatches. Cost guard: 2 empty pulses → 3rd pulse attend-only.
3. **The existing attention/coherence/curiosity jobs** — unchanged, in the
   agent SOP (~/.claude/agents/cortex.md), which is authoritative.

## Design constraints (classifier-mandated, kept by design)

- Dispatched agents NEVER run bypassPermissions: headless + default mode
  denies anything needing approval, so a bad dispatch fails safe instead of
  acting. Prompt bounds are not a sandbox; permission mode is.
- Dispatch classes are allowlisted in the routing table; anything outside is
  Josh's.
- The pulse is a thin executor over infra that already fires — the ROUTING
  TABLE is the asset.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [AI-Powered Workflows: How Enterprise Orchestration Works](../../kb-corpus/blog/orchestrate-ai-workflows.md)
- [The Workato KB: RAG++ over all documentation, and the dreaming team](../../kb-corpus/confluence/extbt/2938929237-the-workato-kb-rag-over-all-documentation-and-the-dreaming-team.md)
- [Cortex Analyst](../../kb-corpus/confluence/intbt/779911272-cortex-analyst.md)
- [The agents: a nervous system of specialists](../../kb-corpus/confluence/extbt/2938961981-the-agents-a-nervous-system-of-specialists.md)
<!-- kb-bridges:end -->

## Sanctioned persistence channel for investigations (2026-10-12, Josh-approved)

The write gate denies headless/pulse writes to knowledge/cortex/investigations/ (by design, fail-closed — never bypass). Sanctioned path instead: post the investigation summary through the bus — `bus_post.py post --agent cortex --type investigation --subject "<task>" --claim "<finding>"` — cost-governor now recognizes bus-posted investigations as persisted (scores pass, not gated). The main session harvests bus rows into knowledge/cortex/investigations/ when writing is available.
