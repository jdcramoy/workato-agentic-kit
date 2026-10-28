# Workato Terraform Provider

**DOCTRINE RULING (Josh, 2026-10-19):** apply where applicable, hold back
where not. APPLY: new-workspace bootstrap, new-build scaffolding (project/
folders/tables/connections), focused UAT deployments of self-contained builds,
drift preview on TF-managed assets, and the repo as API ground truth. HOLD
BACK: prod-bound anything, manifest/package promotion flow (stays on wt),
hotfix deployment (workato-hot-swap + Josh's gates), row writes/job ops.
Ambiguity → hold back. Full split in workbench memory file
`workato-terraform-provider-policy.md`.

Source: private repo `workato-devs/workato-terraform-provider` (needs the
`jcramoyWKTO` GitHub account — `<github-user>` gets NOT_FOUND). Cloned at
`~/Documents/workato-terraform-provider/`. Provider is under active development
by Workato; Go 1.25+/Terraform 1.3+ required.

## What it manages (declarative, state-tracked)

projects, folders, recipes (auto-starts when its connections are authorized;
stops before delete), data tables (+ relation columns), connections (BYO OAuth
app creds, hidden creation settings), custom OAuth profiles, MCP servers
(static + proxied/external), event stream topics, custom connectors (no delete
API — destroy warns + drops state), project properties (same), agentic skills
(same), IAM user groups, MCP server apps.

## Local setup (done 2026-10-19, working)

- `brew install go hashicorp/tap/terraform` (terraform NOT in homebrew-core)
- `go build -o terraform-provider-workato ./cmd/provider` → 35MB arm64 binary
- `go test ./...` → all green (internal/provider suite ~85s)
- `~/.terraformrc`: dev_overrides `"local/workato"` → repo dir; config uses
  `source = "local/workato"`
- API token: same keychain entry wt uses —
  `security find-generic-password -s workato-platform-cli -a josh-us -w`
  exported as `TF_VAR_workato_api_key`

## Live test results (dev ws 3535597, all verified then destroyed)

- plan → apply → plan → destroy all worked. Second plan: "No changes"
  (idempotency holds). Destroy verified via independent REST reads — zero
  residue.
- GOTCHA: relation columns must be `optional = true` or create fails
  ("relation field should be optional").
- API routes used by client: `/api/projects`, `/api/data_tables`,
  `/api/connections`, `/api/custom_connectors`, ... (NOT `/api/v2/*`).
  Data-table list view returns columns as `[]` — need detail fetch for schema.

## mcp_app resource — API notes (Jasper Madrone, 2026-10-19)

The app↔tool binding rides `PUT /api/mcp/mcp_servers/:server_handle/apps/:app_handle` with
top-level `mcp_server_tool_id` (empty string unlinks; tool must belong to the same server,
one app per tool). Full detail + gotchas in domains/workato-dev-apis.md §MCP servers.

## Cross-ENVIRONMENT deployments: adopt + remap machinery (2026-10-19, live-proven)

The provider was built to coexist with RLM package imports, not fight them:

- **ADOPT-ON-CREATE (live-proven):** apply against a target where a same-named
  recipe already exists in the same folder → provider ADOPTS it (same ID
  83194770 kept, never recreated), logs "continued managing it", corrects
  drift in place. Shared `helper_adopt.go` spans many resources (README only
  documents adopt for iam_user_group + mcp_app; recipe adopt confirmed in
  source + live test). Means pointing TF at a populated environment doesn't
  collide — it takes over.
- **Connection-ID remap solved natively:** recipe `config` (carries
  env-specific account_ids) is a separate attribute from `code`;
  `diffRewritesFromConfig`/`applyProviderRewrites` rewrite code to match —
  the source comment explicitly reasons about "the same connector
  re-exported across environments". This is import-remap.py's job, done
  inside the resource.
- **Package-awareness:** live renames/moves are adopted as canonical
  ("customers are free to reorganize their own workspace"); package-authored
  renames apply on later apply; folder moves never auto-accepted. `folder_path`
  gives env-portable placement (paths, not IDs).
- **Recipe lifecycle = workato-hot-swap as a resource:** stop-before-write
  (Workato rejects writes to running recipes), restart after,
  `start` gated on ALL connections authorized, `unauthorized_connections` +
  `last_start_error` + `blocked_trigger_fields` surfaced in state,
  `confirmed_started_once`/`force_restart` semantics.
- **LIMITS: no `terraform import` on any resource** (adoption only via the
  create-path name/folder match). Still no manifest/package story — TF is an
  ALTERNATIVE deployment vehicle for focused UAT/self-contained builds, not a
  manifest format. Config → manifest converter: doesn't exist, writeable but
  redundant if TF is the vehicle. Prod TF deploys would bypass DR/red-team/
  import-remap/post-deploy-smoke gates until doctrine extends to them.

## wt vs provider (2026-10-19 assessment)

Complementary, not a replacement. Provider = declarative provisioning + drift
detection + dev/UAT/prod parity. wt keeps the operational edge: export
manifests, package install, job rerun/cancel, lookup-table row writes,
lifecycle stop/start. Provider has NO manifest/package story — Josh's
promotion flow still needs wt. Candidate wins: workspace parity checks,
new-workspace bootstrap, connector/config drift detection.


<!-- demoted from INDEX.md 2026-10-25, librarian pass, branch librarian/2026-10-25. Content preserved verbatim; the INDEX line is now a routing hook. -->

## INDEX line history (demoted 2026-10-25)

- - [Workato Terraform provider](domains/workato-terraform-provider.md) — private repo workato-devs/workato-terraform-provider (needs jcramoyWKTO acct); cloned+built+live-tested dev ws 3535597 2026-10-19: plan/apply/plan-nochanges/destroy all verified; relation cols must be optional=true; complementary to wt (no manifest/package story); **RULING Josh 2026-10-19: apply to bootstrap/UAT scaffolding/drift-preview/API-truth, HOLD BACK prod+manifests+hotfixes, ambiguity holds**
## ⚠️ 2026-10-28 PROD DISASTER — the ruling was violated, rules hardened

An apply against AHQ AI **Production** (BSYS-29603 recovery attempt) destroyed 61+ live recipes.
The pre-existing ruling ("prod + manifests + hotfixes = no") was violated under time pressure — the
tool was aimed at prod as a workaround for the broken manifest import, with a stale plan and
-auto-approve, and 64 destroys fired unattended. Full-day restoration followed (93 recipes, 74 tools).

**Hardened rules (Josh + session, 2026-10-28):**
1. NEVER this provider against real production — no exceptions even on request; propose dev→dev rehearsal.
2. First real use requires a dev→dev rehearsal mapping plan/apply/destroy behavior on recipes, skills, MCP bindings.
3. Refuse any plan with destroy > 0 unless Josh re-confirms that exact destroy count.
4. Never -auto-approve a plan containing destroys. 5. Partial tfstate = loaded weapon.
6. Restore playbook if it ever happens anyway: google-slides-mcp.md "PROD RESTORATION COMPLETE" section (create-path API deploy, zip-name object resolution, start-as-validator).
