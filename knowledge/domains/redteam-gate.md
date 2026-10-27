# Red-team gate (redteam-gate)

Standing order Josh 2026-10-12: every asset promoted to production carries a
red-team security verdict on record BEFORE the push. Hotfixes still get a
tier-appropriate review — urgency changes the tier, never the requirement.

## Components (all live 2026-10-12)

- **Skill `red-team-review`** (`~/.claude/skills/red-team-review/SKILL.md`) —
  the framework: tier classification (Tier 1 full / Tier 2 standard / Tier 3
  light self-certification for config flips), five review surfaces (secrets &
  credentials, data exposure, injection surfaces incl. prompt injection,
  identity & auth, logic abuse/idempotency), severity taxonomy
  fatal/material/cosmetic WITH remediation guidance (unlike the dissenter),
  verdict forms PASS / PASS-WITH-NOTES / FAIL.
- **Agent `red-team`** (`~/.claude/agents/red-team.md`) — independent
  reviewer dispatched by the build session at promotion prep; reads live
  config + real job traces, never edits the estate. Review-from-DSL alone is
  a fail. Verdict void if anything is pushed after the report.
- **Hook `redteam-guard.sh`** (`~/.claude/hooks/`, registered in global
  settings Stop hooks) — blocks the stop when a session performed prod-bound
  writes (wt-prod/workato-prod writes, package/manifest imports, prod MCP
  mutations) with no verdict on record. Verdict evidence = a
  `knowledge/redteam/` reference, or red-team + verdict/override prose
  (lenient side, same trade-off as manifest-guard). Dev-only and read-only
  sessions pass untouched — manifest-guard owns dev hygiene.
- **Verdict artifacts** — `~/.claude/knowledge/redteam/<BSYS-id>-<slug>.md` +
  Jira comment on the governing ticket. Filename ticket ID is what the hook
  matches.

## Integration points

- promotion-readiness scorecard row 8 **Security-reviewed**.
- promotion-orchestrator: refuses batches containing a FAIL-verdict asset
  unless Josh overrides by name (override recorded in verdict file + story).
- workato-development-playbook SKILL.md: standing-order section before the
  masking release gate (lifecycle phase 5).
- `~/.claude/CLAUDE.md`: standing-order block (2026-10-12).

## Design decisions (Josh, batched grill-gate round 2026-10-12)

1. Enforcement = skill + Stop-hook guard (not prompt-only).
2. Reviewer = independent agent (builder never grades its own work).
3. Depth = risk-tiered, not uniform.
4. Fatal findings = block unless Josh overrides by name.

## Bounds

- Dev-only work passes untouched; the estate-architect's security posture
  pass covers what already lives in prod (no retroactive sweep here).
- Prod-write permission prompts unchanged — the gate reviews the ASSET, the
  permission prompt gates the WRITE.

Spec: workbench repo `docs/superpowers/specs/2026-10-12-redteam-gate-design.md`.
Hook verified 2026-10-12 against 5 synthetic transcripts (block on prod-write
without verdict; pass with verdict, with named override, read-only, dev-only).
