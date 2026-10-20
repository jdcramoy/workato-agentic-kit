# Managed Agents permission-policy watch (GA-watch + liability register)

Status: watch armed 2026-10-16, from dreamer proposal 2026-10-08-managed-agents-policy-mapping
(ga-watched in the narrowed two-re-look form: glm-5.3-flash + deepseek-4.1-flash, both survived).

## The trigger (what fires the migration)

When BOTH are true, Josh ports the prod-write gate first, not the taxonomy:

1. Anthropic's Managed Agents permission policies exit beta
   (https://platform.claude.com/docs/en/managed-agents/permission-policies).
2. Policy governance covers MCP-tool custom surfaces (tools executed via MCP
   servers, not just built-in application tools). The beta carve-out that
   "custom tools executed by the application are NOT governed" is what
   disqualifies most of our surface today; that carve-out disappearing is
   the real GA signal for us.

Until the trigger fires: our client-side hooks ARE the enforcement layer and
remain the asset the two incidents paid for. A client hook patches in hours;
a server policy does not.

## Liability register (ours -> theirs, what to deprecate at GA)

| Our enforcement (client-side, hook-enforced) | Managed Agents policy object | Deprecate at GA? |
|---|---|---|
| `never_auto` list in dream-config.json (skills/hooks/mods/settings/crons/mcp/commands) | equivalent: never-grant `always_allow` / disabled tool | NO. Constitutional since 2026-10-07. Re-host the LIST server-side; never delete it. |
| Hook 13 prod-write confirm gate, fail-closed, prompts Josh (mods/workato-guardrails v1.0.0; ported 2026-10-16 to `~/.claude/hooks/prod-mcp-write-gate.py`) | `always_ask`: session pauses for approval | PORT FIRST (this gate), then deprecate the hook only after the server-side ask is live-probed on a real prod call. |
| `auto_safe_allow` (knowledge-appends, index lines, claim verification) | `always_allow` | YES, once the server list is proven on a week of real sessions. |
| Dissenter agent + dream_math judgment | `auto`: the server evaluates each call and runs, denies, or pauses it | NO as a replacement (dissenter ruled AI-judge-as-prod-gate FATAL for bypassing constitutional enforcement); maybe YES as a belt-and-suspenders second layer. Trust-model note: `auto` moves the judgment to the vendor's server, a different party than our own dissenter. |

The register is the point even before GA: it documents exactly which
client-side rules to deprecate, in what order, and which never move.

## Watch mechanism

- The librarian's weekly procurement pass carries this as a standing beat
  (see `~/.claude/agents/librarian.md` Phase 4): fetch the permission-policies
  doc URL, diff against the two trigger conditions above, and if either
  flipped, file a claim row and route to Josh as a decision (never auto-port).
- Non-librarian sessions that happen to read this doc should treat any
  observed beta-exit or MCP-coverage change as a claim-worthy finding.

## Rollback

Documentation-only. Nothing to revert.
