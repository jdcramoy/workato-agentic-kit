# VUA revert on push

Motif: `vua-revert-on-push` (canonical slug; first witness: airo-mcp-playbook trap table, 2026-09-11).

One failure, many names. The harness has recorded this same trap as "push wipes
personalization", "stale runtime after push", "VUA revert", "personalization
reverts to the base identity", and "recipe push reverts VUA connection". This
file is the single canonical reference; the scattered originals should carry
pointers here (pointer-rewrite diff on branch `librarian/2026-10-11`).

## The mechanism

`recipe_builder_push` (AIRO MCP) can silently revert an end-user-authenticated
(VUA) skill recipe's connection personalization back to the base identity. The
push reports success, the job runs, and the skill is now serving on the wrong
connection. Detection by eye or by job success is impossible: nothing errors.

Known instances, all dated:
- 2026-09-11: first canonization in the airo-mcp-playbook trap table.
- 2026-10-01 (two regressions): BSYS-26815 benefits skill; recipe 82759555.
- 2026-10-06: Josh ruling "VERIFY, DON'T ASSUME" recorded in ~/Documents/CLAUDE.md.

A second, related silent-revert class on the same push path: push can persist
an empty trigger or drop steps entirely (correlator build, recorded in
projects/hr-genie.md, 2026-10). Same detection law applies.

## Detection: read-back, never trust the push

After ANY push touching a VUA or end-user-connection skill:

1. Verify connection mode via read-back: `mcp_server_get` on the serving MCP
   server ("VUA Required: Yes", end user's connection) or the recipe UI.
2. For the workday_rest config class specifically: the trap strips
   `personalization:true`. Detect via API read-back of the recipe config.
3. Re-select or repair ONLY if verification shows drift. Do not
   preemptively re-select (the old stop, push, re-select cycle was retired
   2026-08-20 and re-proven unnecessary 2026-10-09's live probe).

## Repair (verified sequence, BSYS-26815)

Direct PUT bypasses the revert: `PUT /api/recipes/:id` with
`{name, description, code, config}` as JSON string. Confirmed working on
recipe 82759555 (2026-10-01).

## Standing law

Josh ruling 2026-10-06: the old "fixed 2026-08-20" declaration is NOT trust.
The revert has recurred after being declared fixed. Current law: after any
push touching an identity-sensitive skill, verify the connection mode by
read-back; re-select only on observed drift; never skip the verify.

Claim of record: `clm-001` (vua-persistence-after-push), confidence high,
last verified 2026-10-09 (live probe, confirmed).

## Sources (all fetched 2026-10-11)

- claims/claims.jsonl clm-001, evidence chain and verification result.
- projects/hr-genie.md lines ~580: repair sequence + empty-trigger class.
- airo-mcp-playbook SKILL.md trap table (2026-09-11 first canonization).
- ~/Documents/CLAUDE.md VUA verify bullet (Josh ruling 2026-10-06).
- Memory: bsys-26815-benefits-skill-state.md (regression history + fix sequence).

## Detection rule (Josh, 2026-10-30 — visually check, never trust a read claim)

Session 86126802 (google-slides project, 2026-10-29/30): the agent read the
recipe's connection setting and claimed it was on the wrong state; Josh, looking
at the same UI: "the UI literally was on 'Use this Recipe's Connection'. You're
making shit up. You need to start visually checking VUA connection if there is
ANY question." Two rules now attach to this trap:

1. **Verify the connection setting VISUALLY** (orca snapshot/screenshot of the
   recipe's Connection panel) whenever there is any question about which
   connection a skill recipe is serving on — never from memory of an earlier
   read, never from DSL inference alone.
2. **The fix is one flip**: if a push reverted the end-user connection
   personalization, the repair is flipping the recipe's connection back to the
   end user's connection — do not spiral into build-side theories first. Josh:
   "You're running in circles for a simple fix that you need to record."
