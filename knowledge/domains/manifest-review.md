# Manifest review — tech-reviewing RLM export manifests (born BSYS-29510, 2026-10-12)

Review procedure for Deployment Request manifests, both Josh's own and external builders'
(the Super Happy Friday review was the first external one). Complements the BUILD-side
doctrine in the `manifest-hygiene` skill (dry-run before filing) — this file is the
REVIEW-side: what to check when a manifest lands in the queue for Final Tech Review.

## The two review postures

1. **Own manifest, dev workspace reachable** — verify live: recipe code closure
   (`fetch('/recipes/<id>/code.json')` in-page, or `recipe_builder_pull` for 1-2),
   target-env inventory diff, drift check (`manifest_drift_check.py`). Full hygiene
   skill applies. Verdict can be "clean". NOTE (BSYS-29510, 2026-10-12): "not in my
   project list" ≠ "not in the workspace" — projects paginate past 100 and the wt/AIRO
   project views both truncate. Locate the project by the manifest itself first:
   `wt api GET "/api/export_manifests/<id>.json"` returns `project_path` even though
   it returns NO assets; then `wt folders list` (text output) or AIRO folder_list to
   resolve the project folder id, then `/api/recipes?folder_id=<id>` (uses `items`
   key) per folder. Posture flips to live-verify the moment the folder is found.
2. **External manifest, workspace genuinely NOT reachable** — you CANNOT verify
   closure. Per hygiene rules, "unverifiable" is a FAIL, never "assumed clean".
   Review becomes: internal-consistency audit of the listing + policy checks + named
   verification asks the builder must answer. Do NOT pretend to check what you can't.

## Consistency checks that work from the listing alone

Learned on BSYS-29510 (24 recipes, 14 agentic skills, 6 connections, 1 MCP server,
1 properties file — Certinia/Salesforce timesheet MCP):

- **Connection closure (the killer check).** JOSH CORRECTION 2026-10-12: connection
  promotion rules are OURS, not global — the zero-connection-assets standing rule
  applies to OUR build-side manifests only. For external/builder manifests, shipping
  connections in the package is acceptable and the review check is CLOSURE, both
  directions: (a) every connector application in the code must have a connection in
  the package or a named target connection; (b) connections included must be the ones
  actually used. BSYS-29510 shipped 6 connections but NO Salesforce while 7 recipes
  call the salesforce connector (TL01-TL04, TL09, TL13, function_01 — verified LIVE
  via the per-recipe `applications` array). Same blocking class either way.
- **CHEAP connector-closure trick (2026-10-12):** `wt api GET
  "/api/recipes?folder_id=<id>"` returns every recipe with an `applications` array —
  the union of connector names — WITHOUT pulling any code. Diff that union against
  the manifest's connection list in seconds. Code-level pulls (flow_id/table_id
  regexes) only needed for function/table closure, and the v1 recipes API is flaky
  about which key carries code (`code` vs `recipe`, sometimes neither) — don't burn
  time on it when the listing already answers.
- **Properties file present = blocking.** `properties.project_properties.json` carries
  dev values and overwrites the target. Strip; pre-create target-side instead.
- **Type-coverage gaps that hint at closure misses.** No data tables / lookup tables /
  api endpoints / topics in a listing whose recipe names suggest them
  (`tl09_lookup_nonbillable_project` — "lookup"!). This was the BSYS-29498 bug class
  (11 recipes, zero of 4 functions / 7 tables shipped). Mark as MUST-VERIFY against
  code, not as assumed-absent.
- **Trigger URL remap.** Any `webhook_*` recipe gets a NEW URL in the target; its
  callers need a named remap in a "post-import linkage work" section. Also scan for
  env-scoped ids: `ginct-*` chat-trigger handles, hard-coded connection/account ids,
  env-bound table/function ids (the 2026-10-10 P2: 15h of lost notifications from an
  unmapped dev trigger handle).
- **MCP server surface vs skills present.** If the MCP server file exists, check the
  skill/recipe set it exposes against what shipped — and whether anything intentionally
  NOT exposed is stated in the story (otherwise reviewers read it as a gap).
- **Story pairing + package identity.** Manifest pairs with a STORY (not just a
  Deployment Request) carrying: target environment, UAT Evidence section, the FRESH
  export's package id (a new export supersedes all prior ids), and the post-import
  linkage list. An empty ticket body = blocking regardless of manifest quality.
- **Structure/naming (non-blocking).** Doubled nesting ("X/X/Functions"), mixed naming
  schemes (tl01–tl14 vs function_01/rec_00), root vs nested Functions folders —
  cosmetic, batch into one revision ask.

## Comment format (Josh standard)

Itemized comment on the ticket: **Blocking** (numbered, each with the exact asset/
recipe names and the failure mode if imported) then **Non-blocking** (numbered,
cosmetic/confirmatory). Close with a one-line bottom line naming what unblocks.
Cite the docs (https://docs.workato.com/en/recipe-development-lifecycle/import.md)
and the precedent ticket (BSYS-29498) where they carry the argument.

## Re-review round (BSYS-29510 resubmission, 2026-10-12)

- **Diff the re-post against the prior blocking items FIRST.** A resubmitted
  manifest can be asset-identical to the rejected one (SHF's was). If unchanged,
  the re-review is a short verdict comment ("unchanged, items 1–4 still open"),
  not a fresh full checklist run — and "fresh export" means the ASSETS changed,
  not just a new bot comment.
- **Watch the deploy trail.** Auto-deploy pipelines can fire while blocking
  findings are open (bot: "Auto-Deploy ... succeeded" at 17:49, after the 17:43
  blocking review). Scan bot comments for deploy events; if one fired against a
  package with closure failures, make confirming what deployed + gating
  auto-deploy on reviewer sign-off a blocking item.
- **Which connection a recipe uses lives in `config`, not `applications`.**
  `/api/recipes/<id>` `applications` names only the connector; the hard-bound
  connection is `config[].account_id` (e.g. TL02 salesforce → 19648924, a
  connection living OUTSIDE the source project). Resolve those ids for the
  post-import linkage list even when the project has no connection of that type.
- **Tooling:** mcp addCommentToJiraIssue can inherit a stuck/stale parameter
  across calls in a session (commentVisibility "Developers" doesn't exist on all
  projects). If the tool errors on commentLevel, retry once, then delegate the
  single post to a fresh subagent — don't loop.

## Skill

The invokable procedure lives at `~/.claude/skills/manifest-review/SKILL.md` —
invoke it when a Deployment Request/manifest lands for review.

## Finding the manifest from a DR ticket (2026-10-13, BSYS-29108)

- The **Workato Manifest Link lives in Jira custom field `customfield_10494`** (Source/Dest
  workspaces in `customfield_10588`/`customfield_10446`, format "Name [workspace-id]"). Fetch
  with fields `["*all"]` — the default field set omits it.
- `GET /api/export_manifests/<id>.json` returns **metadata only** (id, name, status,
  `project_path`, `last_exported_at`) — NO asset listing. Asset list comes from the bot
  comment on the ticket ("Source Components of the Workato Manifest").
- The bot comment's asset list alone is NOT closure evidence. Verify live in the source
  workspace: `wt api GET "/api/recipes?folder_id=<id>"` gives each recipe's `applications`
  array (connector closure, no code pull), then pull code per shipped recipe and grep
  `table_id` / `call_recipe` flow_id / `genie_handle` for deep closure.
- Freshness check: compare `last_exported_at` (UTC) against the bot comment timestamp.
- Recipe code greps that work: `"table_id":"(\d+)"`, `call_recipe..."flow_id"`,
  `genie_handle":"gin-..."`, `webhooks.workato.com` (hard-coded source-WS webhook URLs =
  post-import remap item).


<!-- demoted from INDEX.md 2026-10-25, librarian pass, branch librarian/2026-10-25. Content preserved verbatim; the INDEX line is now a routing hook. -->

## INDEX line history (demoted 2026-10-25)

- - [Manifest review](domains/manifest-review.md) — REVIEW-side RLM manifest audit (complement to the manifest-hygiene build-side dry-run) + skill: born BSYS-29510 (Super Happy Friday, 2026-10-12). Two postures (live-verify vs unverifiable=FAIL); locate-by-manifest-id first (`wt api GET /api/export_manifests/<id>.json` → project_path — projects paginate past 100, absence from a project list ≠ absence from workspace); CHEAP connector-closure via per-recipe `applications` array (no code pulls); JOSH RULING: connection-promotion rules are OURS not global — zero-connection-assets binds OUR manifests only, external reviews check connection CLOSURE both directions (BSYS-29510 shipped 6 connections, missing the Salesforce one 7 recipes call); properties-file travel + suspicious-absence scan (lookup/table names) + webhook remap + story/package-id pairing; comment format Blocking/Non-Blocking