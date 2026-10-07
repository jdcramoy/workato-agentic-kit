---
name: manifest-hygiene
description: Dry-run a Recipe Lifecycle Management manifest before filing the story — catch missing dependencies, stale references, wrong-folder assets, and unused extras before the import discovers them at 2am. Use whenever assembling or editing a promotion manifest, or when Josh asks "is this manifest clean", "check the manifest".
---

# Manifest hygiene

A manifest that fails at import is a planning failure. Dry-run the shape
before the story is filed.

## Checks (all of them, every time)

1. **Dependency closure.** For each asset in the manifest: every called
   function, referenced table, connection, and child recipe it uses must
   either be IN the manifest or already exist (and be healthy) in the target
   environment. A recipe referencing a missing function is the classic
   2am failure.
2. **No passengers.** Nothing unchanged or unrelated enters because it
   shares a folder. Every asset in the manifest must have a ledgered change
   (build-ledger evidence) or an explicit reason.
3. **Freshness.** Asset versions in the manifest match the current dev
   versions (recipe_get each — a stale snapshot imports old bugs).
4. **Connection bindings.** Every connection reference resolves in the
   target environment; VUA-marked assets are flagged for post-import
   verification.
5. **Completeness of the story.** The manifest pairs with a Story (never
   Deployment Request type), points set, governing epic parented.

## Output

A pass/fail table per asset: what was checked, what was found, what must
change. A dirty manifest blocks filing — the orchestrator does not file a
story over a failing hygiene report.

## Rules

- `wt manifests assets <folder>` and tracker/AIRO reads only; this skill
  never writes.
- Every "missing dependency" claim cites the referencing step.
- If the target environment can't be read, the hygiene verdict is
  "unverifiable" — never "assumed clean".
