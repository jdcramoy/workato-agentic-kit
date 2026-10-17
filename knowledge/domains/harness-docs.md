# Harness documentation (repo + Confluence tree)

The architecture documentation lives in three places that must not drift:
the live harness (~/.claude/agents, ~/mods, knowledge tree), the kit repo
(docs/harness-docs/, source of truth for published docs), and the
Confluence tree in the [External] BT-Business Technology space (BTI,
8 pages, created 2026-10-08).

- Parent: "The Agentic Workato Harness: a self-improving development
  organism", page 2938830860. Children: agents 2938961981, skills
  2938929171, mods 2939060252, memory/KB 2939158533, schedules
  2939387928, gossip bus 2939191301, trust ladder 2939387948.
  Updated 2026-10-08: project-dreamer agent + /proposals review surface
  documented across overview/agents/schedules/trust-ladder pages.
  Full sync 2026-10-11 (all 8 pages republished, read-back verified): model-gateway layer + fusion, librarian/evidence/spec-distiller agents (11 total), integrity mesh + calibration ledger + denominator oracle + estate twin + skill league + standing orders + chaos canary + shadow estate (the frontier economy layer), frontier-nightly zero-LLM job, decision inbox, Jira autonomy grant, KB canon expansion (24.6k docs). Repo committed 5cca882; manifest date bumped.
  Full sync 2026-10-13 (all 9 pages republished incl. 08-workato-kb, read-back verified): red-team gate + agent + guard hook, living-manifest standing order + manifest-guard, authority-non-delegation rule, measurement layer (A/B bench + hallucination discriminator + retrieval map), context economy (server tiering + diet, 128k→58k cold), session-budget mod, session-level guard hooks (manifest/redteam/drop-guard/dead-man/error-guide), turn-audit fleet job, skills parking lot (13 parked, 61 total/48 live), morning-brief dropped-sessions digest. Kit repo committed 76eacf6; manifest bumped to docs-sync-2026-10-13.
  Check-in 2026-10-14 (4 pages republished, read-back verified): bus actuator (gossip-actuate.py, corroboration tally now files triage cards; live, 2 threads actuated), harness Dashboards MCP outward window (read-only remote MCP → claude.ai Dashboards, Josh-gated remainder), living-manifest test-probe exemption (2026-10-13), jira-slack-formatting skill. Also confirmed the 10-13 second sync (0e3ccf5) pushed the dreamer mood gate + traps-ledger check to 01-agents (v8 repair). Manifest bumped to docs-sync-2026-10-14.
  The authoritative ID map is the repo manifest:
  ~/Documents/agentic-workato-kit/docs/harness-docs/manifest.json —
  re-read it, never quote IDs from memory.
- Sync job: weekly session-cron Tue 06:57 (durable, self-rearming,
  first created 2026-10-08 id 2629873e), SOP at
  kit repo schedules/harness-docs-sync.txt. Direction per edge: live
  harness -> repo (agent SOPs), repo -> Confluence (published pages).
- Publish policy: existing-page updates autonomous WITH the sanitizer
  (no workspace IDs, cloudIds, tokens, epic keys, internal identifiers)
  and a getConfluencePage read-back to verify rendering; new pages,
  reparenting, deletion are Josh-gated. Pass contentFormat "markdown"
  EXPLICITLY on every Confluence write (omitting it saves literal
  markdown — trap confirmed twice).
- When the architecture changes (new agent, renamed command, changed
  hook count, new ladder mode), update the repo doc page files in the
  same session when practical, or expect Tuesday's sync to catch it.
  The sync job posts drift counts to the bus; a skipped sync surfaces
  in the watchdog heartbeat check like any other fleet job.

## Inventory 2026-10-08 (where everything lives)

Repos with remotes: kit (github.com/Workato-All/workato-agentic-kit) +
josh-orca (nightly backup). Git repos WITHOUT remote:
~/.claude/knowledge (RESOLVED 2026-10-08: origin =
github.com/Workato-All/josh-knowledge, private, baseline dfc7216
pushed; repo created by Josh) and ~/.claude/recipe-history (NOW covered
by harness-backup: 59 snapshots verified in josh-orca 2026-10-08).
~/mods = deployed runtime marketplace, untracked; kit mods/ = source;
deploy direction: bin/mods-deploy (kit -> ~/mods, --check mode,
symlink-safe); the weekly sync job reverses hot-edit drift via
--check -> copy into kit -> redeploy. Transcripts (1.8GB) + keychain
remain never-copied by design.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [The Agentic Workato Harness: a self-improving development organism](../../kb-corpus/confluence/extbt/2938830860-the-agentic-workato-harness-a-self-improving-development-organism.md)
- [The agents: a nervous system of specialists](../../kb-corpus/confluence/extbt/2938961981-the-agents-a-nervous-system-of-specialists.md)
<!-- kb-bridges:end -->
