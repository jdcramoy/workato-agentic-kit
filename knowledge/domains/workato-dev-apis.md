---
type: reference
updated: 2026-10-15
sources: local RAG++ KB (docs.workato.com corpus); every claim cites a docs URL
scope: platform developer-facing APIs only. Connector SDK / Ruby internals covered by a sibling doc.
---

# Workato developer-facing APIs: full inventory

Index of every developer-facing API family on the Workato platform, with purpose, base URL,
auth, key endpoints, documented limits, and gotchas. Compiled from docs.workato.com as mirrored
in the local KB (2026-10-15).

There are three distinct API surfaces. Do not conflate them:

1. **Developer API** (`https://www.workato.com/api/...`): manage the workspace (recipes, connections, packages, IAM).
2. **API Platform serving surface** (`https://apim.workato.com/...`): recipes exposed AS REST endpoints for external callers.
3. **Embedded (OEM) Partner API** (`https://www.workato.com/api/managed_users/...`): same Developer API, namespace shifted under customer workspaces.

---

## 1. Authentication model (applies to Developer + Embedded APIs)

Source: https://docs.workato.com/en/workato-api (base URLs, response codes)
Source: https://docs.workato.com/en/workato-api/api-clients (API clients, roles, scoping)

- Auth = **API client token** sent as `Authorization: Bearer <api_token>`. No other header.
- Tokens are created under **Workspace admin > API clients**. Each client has a **client role**
  (which endpoint families it may touch), optionally an **environment** (DEV/TEST/PROD) and
  **project scope** (limits access to connections, recipes, folders, lookup tables, properties,
  API platform collections, API platform clients in those projects). Optional **IP allowlist** per client.
- Scoping is **workspace-level, not user-level**: the client acts with its role's permissions
  regardless of who created it.
- Legacy auth (full-access API key + email in `x-user-token`/`x-user-email` headers or query
  params) is fully deprecated: rejected as of 2025-07-14, removed from 2025-10-14 onward.
  Source: https://docs.workato.com/en/workato-api/moving-to-api-client-authentication-faq
- Client roles are edited under **Workspace admin > API clients > Client roles**; edits apply immediately.
- Tokens are view-once at creation; integrated with GitHub secret scanning.
  Source: https://docs.workato.com/en/workato-api/github-secret-scanning
- Supported content: `application/json` both ways. `x-correlation-id` header supported for
  request tracing (echoed back, plus a Workato-generated one).

---

## 2. Developer API (workspace management API)

Source index: https://docs.workato.com/en/workato-api/resources (full endpoint table)
Source overview: https://docs.workato.com/en/workato-api

**Purpose:** automate every workspace management operation: recipes, connections, jobs, folders,
projects, roles, IAM, packages, on-prem agents, data tables, and more.

**Base URLs** (data-center dependent, note trailing `/api/`):

- US: `https://www.workato.com/api/`
- EU: `https://app.eu.workato.com/api/` | JP: `https://app.jp.workato.com/api/` | SG: `https://app.sg.workato.com/api/`
- AU: `https://app.au.workato.com/api/` | IL: `https://app.il.workato.com/api/` | KR: `https://app.kr.workato.com/api/`
- UK: `https://app.uk.workato.com/api/` | CN: `https://app.workatoapp.cn/api/`
- Self-service (Free/Pro/Developer Sandbox): `https://app.trial.workato.com/api/`

**Auth:** Bearer API client token (section 1). Plan-gated: included in specific pricing plans.

**Timeout:** 40 seconds per request. Source: https://docs.workato.com/en/workato-api/limits

### Endpoint families (all under `/api/...` unless noted)

**Recipes:** GET/POST/PUT/DELETE `/api/recipes` (+ `/api/recipes/:id/start`, `/stop`,
`/reset_trigger`, `/poll_now`, `/force_run`, `/connect`, `/versions`, `/health`, `/job_counts`).
Create recipe is 1 req/s; Performance Copilot health scan is 20 req/min; the rest 60 req/min.
https://docs.workato.com/en/workato-api/recipes

**Jobs:** GET `/api/recipes/:recipe_id/jobs`, GET `/api/recipes/:recipe_id/jobs/:job_handle`,
POST `/api/job/resume` (SDK wait-for-resume callback), POST `/api/recipes/:recipe_id/repeat_jobs`
and `/cancel_jobs` (max 25 job IDs per request, 1 req/s each).
https://docs.workato.com/en/workato-api/jobs

**Connections:** GET `/api/connections`, POST `/api/connections`, PUT/DELETE
`/api/connections/:connection_id`, POST `/disconnect`, POST `/pick_list`. List is 60 req/min,
all other connection ops 1 req/s. Connection create/update takes provider-specific input
schemas; see parameter reference: https://docs.workato.com/en/workato-api/connections-parameters-dev
https://docs.workato.com/en/workato-api/connections

**Folders/projects:** `/api/folders`, `/api/projects` (CRUD). https://docs.workato.com/en/workato-api/folders

**Lookup tables:** full CRUD on `/api/lookup_tables` incl. row ops and `batch_delete`.
https://docs.workato.com/en/workato-api/lookup-tables

**Data tables:** see section 5 (split across two hosts).

**On-prem:** `/api/on_prem_groups` and `/api/on_prem_agents` CRUD, plus `/status` probes,
agent search by common name, and `GET /api/on_prem_agents/:id/activation_code`.
https://docs.workato.com/en/workato-api/on-prem

**Project/environment properties:** GET/POST `/api/properties` with prefix filters.
The same path serves project-level properties when a project ID is supplied.
https://docs.workato.com/en/workato-api/account-properties and
https://docs.workato.com/en/workato-api/project-properties

**Environment management:** `/api/secrets_management/clear_cache`, `/api/activity_logs`
(audit log read), `/api/tags` CRUD. https://docs.workato.com/en/workato-api/environment-management

**Workspace collaborators:** `/api/members` CRUD, `/api/member_invitations` (invite is
rate-limited additionally to one request per user+workspace per 20 minutes).
https://docs.workato.com/en/workato-api/team

**Workato Identity IAM:** `/api/iam/users`, `/api/iam/user_groups`, `/api/iam/app_links`
(CRUD + group membership + app links). https://docs.workato.com/en/workato-api/workato-identity-iam

**Legacy roles / environment roles / project roles / role migration / project grants /
collaborator groups / tag assignments:** `/api/roles`, `/api/environment_roles`,
`/api/project_roles`, `/api/roles_migration/*`, `/api/project_grants`, `/api/user_groups`,
`/api/tags_assignments`. All 60 req/min. Indexed at
https://docs.workato.com/en/workato-api/resources

**Developer API clients management:** `/api/developer_api_clients` (CRUD + `/regenerate`
token) and `/api/developer_api_client_roles`. https://docs.workato.com/en/workato-api/api-client-apis

**Custom connectors helpers:** `/api/custom_connectors` search, `/api/sdk/validate_code`,
`/api/sdk/generate_schema/json`, `/api/sdk/generate_schema/csv`. 1 req/s for most,
60 req/min for schema generation. (SDK internals are out of scope here.)
https://docs.workato.com/en/workato-api/custom_connectors

**Cross-workspace sharing:** `/api/cross_workspace/grants` (outgoing CRUD), `/incoming_grants`,
`/source_environments`, `/target_environments`. Reads 600 req/min, writes 60 req/min.
https://docs.workato.com/en/workato-api/cross-workspace-sharing

**Static assets:** `/api/static_assets/files` (list/upload/download/delete).
https://docs.workato.com/en/workato-api/static-assets

**Event streams (developer side):** `/api/event_streams/topics` CRUD + purge.
https://docs.workato.com/en/workato-api/event-streams

**Test Automation:** POST `/api/test_cases/run_requests`, GET
`/api/test_cases/run_requests/{id}`, GET `/api/recipes/{recipe_id}/test_cases`.
https://docs.workato.com/en/workato-api/test-automation

**XChange (internal package exchange):** `/api/xchange/packages` with versions, import,
approve/reject/reset review, publish/unpublish, sharing links, distribution batches,
installation stats. 60 req/SECOND (highest quota on the platform).
https://docs.workato.com/en/workato-api/xchange

### Rate limit summary (Developer API)

Source: https://docs.workato.com/en/workato-api/limits (defaults; Enterprise can request extensions)

- Default: 60 req/min per collection. Exceptions: agent studio GET lists 1,000 req/min and
  conversations 10 req/s; XChange 60 req/s; package import 500 req/hour per user ID;
  recipe create / job repeat-cancel / force-run / connection writes 1 req/s; cross-workspace
  reads 600 req/min; event streams payloads max 1 MB (public pubsub API max 10 MB).

### Gotchas (Developer API)

- Legacy `x-user-email`/`x-user-token` auth is dead. Any old script still carrying it fails 401.
- Project-scoped API clients silently cannot see assets outside their projects; Embedded partner
  clients ignore project scoping and see ALL customer workspaces (documented warning).
  https://docs.workato.com/en/workato-api/api-clients
- Package import must pass `restart_recipes=true` as a URL parameter or imported recipes that
  were running stay stopped. https://docs.workato.com/en/workato-api/recipe-lifecycle-management
- Timeout is 40 s; long operations (package export/import, project build) are asynchronous and
  require polling the package/build resource.

---

## 3. Recipe Lifecycle Management (RLM) API

Source: https://docs.workato.com/en/workato-api/recipe-lifecycle-management
Docs guides: https://docs.workato.com/en/recipe-development-lifecycle/export and
https://docs.workato.com/en/recipe-development-lifecycle/import

**Purpose:** manifest-driven export and import of assets (the classic dev-to-prod promotion path).

**Auth:** Bearer API client token; rate limits below.

**Key endpoints:**

- `GET /api/export_manifests/folder_assets` - view assets in a folder (manifest building input)
- `POST /api/export_manifests` / `GET|PUT|DELETE /api/export_manifests/:id` - manifest CRUD.
  Set `include_tags=true` at manifest creation or tags are not exported.
- `POST /api/packages/export/:manifest_id` - **asynchronous**; poll `GET /api/packages/:id`.
- `POST /api/packages/import/:folder_id` - **asynchronous**; zip as `application/octet-stream`;
  poll `GET /api/packages/:id`; pass `restart_recipes=true` to restart running recipes.
- `GET /api/packages/:id` and `/api/packages/:id/download`.

**Rate limits:** package import is 500 requests/hour per user ID (hard hourly reset); all other
RLM endpoints 60 req/min. https://docs.workato.com/en/workato-api/limits

**Gotchas:**

- Export and import are both async; a 200 on the POST is a receipt, not a finished package.
- Manifests are the only way to get dependency-complete exports; folder_assets helps crawl the
  tree top-down before building the manifest.
- UI guide path: https://docs.workato.com/en/recipe-development-lifecycle

### Projects build/deploy API (newer deployment flow)

Source: https://docs.workato.com/en/workato-api/projects

`POST /api/projects/:id/build` (build a project), `POST /api/project_builds/:id/deploy`
(deploy build to an environment), `POST /api/projects/:id/deploy` (combined), plus a full
review workflow: `GET /api/deployments/:id`, `POST /api/deployments/:id/submit_for_review`,
`/assign_reviewers`, `/approve`, `/reject`, `/reopen`, `/update_review_comment`, `/deploy`.
This is the environment-aware, review-gated successor path to raw package import.

---

## 4. Embedded (OEM) Partner API

Sources: https://docs.workato.com/en/oem/oem-api (index),
https://docs.workato.com/en/oem/oem-api/managed-users (customers),
https://docs.workato.com/en/oem/embedded-environments/embedded-environments-api (environments)

**Purpose:** Embedded partners programmatically provision and manage customer workspaces and
every asset inside them. Requires an Embedded account.

**Base URL:** same data-center hosts as Developer API (`https://www.workato.com/api/` etc.).
**Auth:** Bearer token from an API client in the Embedded ADMIN workspace (tokens created in
customer workspaces cannot drive these APIs).

**Environment targeting convention** (the OEM namespace trick): customer-scoped endpoints come
in three suffix variants:

- No environments: `/api/managed_users/:managed_user_id/...`
- Dev: `/api/managed_users/:managed_user_id_dev/...`
- Test: `/api/managed_users/:managed_user_id_test/...`
- Prod: `/api/managed_users/:managed_user_id_prod/...`

**Managed customers endpoints:**

- `POST /api/managed_users` (create customer; rich body: plan_id, custom_credit_limit,
  whitelisted_apps, auth_settings for SAML/JIT, frame_ancestors, origin_url for embedding)
- `GET|PUT|DELETE /api/managed_users/:managed_user_id`
- Members: `/api/managed_users/:id/members` CRUD + `/privileges`, `/projects_privileges`, `/project_grants`
- Usage: `GET /api/managed_users/usage` (monthly tasks), `POST /api/v2/managed_users/statistics/usage`
  (granular), `POST /api/v2/managed_users/statistics/connection_usage`
- Environments provisioning: `POST /api/managed_users/:id/environments` (v1: existing assets land
  in DEV; v2 `/api/v2/managed_users/:managed_user_id/environments` lands them in PROD; async,
  poll `GET /api/v2/managed_users/environments_provision_tasks/:id`)
- Deprecated: `/upgrade`, `/downgrade`, and singular `/member` endpoints.

**Rate limits:** 40 s timeout; most endpoints 60 req/min; heavy reads (list customers, list
connections, usage, connectors metadata, API platform lists) 1,000 req/min. Quotas apply at the
Embed admin workspace level, shared across ALL customer workspace calls from that workspace.
https://docs.workato.com/en/oem/oem-api/limits

**Customer-scoped mirror surface:** nearly every Developer API family exists in OEM form under
`/api/managed_users/:managed_user_id(_dev|_test|_prod)/...`: recipes, jobs, connections,
folders, data tables, lookup tables, on-prem, properties, environment roles, API platform,
custom OAuth profiles, MCP servers, test automation, activity logs.
https://docs.workato.com/en/oem/oem-api/recipe-lifecycle-management (RLM in OEM),
https://docs.workato.com/en/oem/oem-api/connections, https://docs.workato.com/en/oem/oem-api/data-tables

**Custom OAuth profiles** (partner-held OAuth apps applied into customer connections):
https://docs.workato.com/en/oem/oem-api/custom-oauth-profiles

**Gotchas:**

- v1 vs v2 environment provisioning place existing assets in DIFFERENT environments (DEV vs
  PROD). Choosing the wrong one relocates a customer's whole workspace.
- Rate limits are workspace-pool, not per-customer: a loop over 500 customers shares one quota.
- API clients need DEV environment access to manage collaborators in customer workspaces.
  https://docs.workato.com/en/oem/oem-api/managed-users

---

## 5. Data tables API (two hosts)

Source: https://docs.workato.com/en/workato-api/data-tables

- **Table management** (schema CRUD, truncate): host `https://www.workato.com`, paths
  `/api/data_tables` (+`/:id`, `/:id/truncate`). 60 req/min.
- **Record manipulation**: host `https://data-tables.workato.com`, paths
  `/api/v1/tables/:data_table_id/query` (POST, filter query), `/records` (POST create),
  `/records/:record_id` (PUT/DELETE), file field upload/download link endpoints.
- **Record import**: also `data-tables.workato.com`: `/records/import/file/upload_link`,
  `/records/import/start`, plus `/sharing/files` for the signed upload and dismiss endpoint.
  https://docs.workato.com/en/workato-api/data-tables

**Gotcha:** three different base hosts in one feature area (workato.com, data-tables.workato.com,
and a signed URL for uploads). Clients that assume one host break on record APIs.

---

## 6. Event streams public pubsub API

Source: https://docs.workato.com/en/workato-api/pubsub (public APIs);
https://docs.workato.com/en/workato-api/event-streams (topic management)

- Host: `https://event-streams.workato.com`
- `POST /api/v1/topics/:topic_id/consume` - consume messages
- `POST /api/v1/topics/:topic_id/publish` - publish single message
- `POST /api/v1/batch/topics/:topic_id/publish` - publish batch
- Limits: 60 req/min; payload max 10 MB (vs 1 MB through the developer topic APIs).
  https://docs.workato.com/en/workato-api/limits

---

## 7. Agent Studio (Genies, Knowledge bases, Skills) API

Source: https://docs.workato.com/en/workato-api/agent-studio; index:
https://docs.workato.com/en/workato-api/resources

**Purpose:** manage Genies, skills, and knowledge bases programmatically.

- Genies: `/api/agentic/genies` CRUD, `/start`, `/stop`, `/assign_skills`, `/remove_skills`,
  `/assign_knowledge_bases`, `/remove_knowledge_bases`, `/assign_user_groups`, `/remove_user_groups`
- Conversations (read-only): `GET /api/agentic/genies/:genie_id/conversations`,
  `/conversations/:conversation_id`, `/conversations/:conversation_id/events`
- Guardrails: `GET .../guardrails`, `PUT .../guardrails/policies/:policy_type`,
  `GET /api/agentic/genies/guardrails/policies/pii_entities`
- Knowledge bases: `/api/agentic/knowledge_bases` CRUD, plus `/data_sources` and `/recipes`
- Skills: `GET|POST /api/agentic/skills`, `GET /api/agentic/skills/:id`

**Rate limits:** GET lists and single-gets 1,000 req/min; conversations 10 req/s; all other
writes 60 req/min. https://docs.workato.com/en/workato-api/limits

**Gotchas:** Skills surface is read/create only (no update/delete documented in the endpoint
index); conversation reads exclude event-level detail unless you call `/events`. There is no
documented endpoint to SEND a message to a genie; conversations are inspect-only.
(Comparison: the AIRO MCP exposes genie conversation capabilities that the REST API does not.)

---

## 8. MCP servers API and the MCP surface

Sources: https://docs.workato.com/en/workato-api/mcp-servers (REST management);
https://docs.workato.com/en/mcp/developer-api-mcp (Developer/Embedded API as MCP server);
https://docs.workato.com/en/mcp (MCP index)

**Two directions, do not confuse:**

1. **Manage MCP server assets via REST:** `/api/mcp/mcp_servers` CRUD by handle, token renewal,
   hashed tokens (create/delete/refresh), `/assign_tools`, user group assignment, folder move,
   `/server_policies`, tool list/update/delete, access assignments. 60 req/min family.
2. **Workato exposes the Developer + Embedded APIs themselves as a remote MCP server** at
   `https://app.workato.com/mcp` (Bearer API client token). Tools mirror the client role's
   enabled endpoints, so AI tools (Claude Desktop, Cursor) manage the workspace directly.
   Not available in CN data center.

**Gotchas:** token renew vs hashed tokens are different mechanisms; the remote MCP honors
project scopes of the client role, so a narrow role yields a narrow tool surface.

**MCP server APPS — update/link API (Jasper Madrone, 2026-10-19):**
`PUT /api/mcp/mcp_servers/:server_handle/apps/:app_handle` links/relinks an app bundle to a
tool via top-level `mcp_server_tool_id` (integer or numeric string; **empty string unlinks**).
JSON or multipart both work. Guards: (1) the tool must belong to the SAME server, else
400 "Tool not found"; (2) a tool takes at most ONE app, else 400 on the uniqueness validation.
Deployment-date trap: deployments before Oct 3 (2025) don't have the route at all and 404
through a catch-all — a 404 there means "stale deployment", not "no such API" (route shipped
Oct 3, 2026). The console's
Edit dialog is the same stack, same param name — there is no second/hidden path. Create-side
companion: the Terraform provider's `workato_mcp_app` resource adopts an existing same-named
app under the same server instead of colliding (see domains/workato-terraform-provider.md).

---

## 9. The API Platform (management API and the serving surface)

### 9a. Management API (managing the platform, `https://www.workato.com/api/...`)

Source: https://docs.workato.com/en/workato-api/api-platform; index:
https://docs.workato.com/en/workato-api/resources

- API collections: `/api/api_collections` CRUD + `GET /:id/openapi` (OpenAPI spec download)
- Endpoints: `/api/api_endpoints`, create/update/enable/disable, per-endpoint OpenAPI
- API clients (consumers): v1 `/api/api_clients` + `/api/api_access_profiles` (DEPRECATION
  FLAGGED in docs), v2 `/api/v2/api_clients` + `/api/v2/api_clients/:id/api_keys` (project-aware;
  keys create/update/enable/disable/refresh_secret/delete)
- Portals: `GET /api/v2/api_portals`
- Certificate bundles (mTLS): `/api/cert_bundles` CRUD + download
- Quota: all API platform management endpoints 60 req/min.

### 9b. The serving surface (recipes exposed as REST)

Sources: https://docs.workato.com/en/api-mgmt/api-recipes (API recipes),
https://docs.workato.com/en/api-mgmt/calling-apis (calling + error codes),
https://docs.workato.com/en/api-mgmt/limits (quotas),
https://docs.workato.com/en/api-mgmt/custom-domain (URL shape)

- **API recipes** replace the API-endpoint functionality of callable recipes
  (https://docs.workato.com/en/api-mgmt/api-recipes/api-recipes-faq). An API recipe = the
  "API platform by Workato" connector's **New API request** trigger + **Response to API request**
  action. Requires API platform access.
- **Endpoint URL shape:** `https://apim.workato.com/<org>/<collection>/<endpoint>`; replaceable
  with a CNAME-verified custom domain (e.g. `https://api.boltcompany.com/sales-api/get-invoice`).
  Not case sensitive; unsupported in CN.
- **Collections** group endpoints for access control; Postman sync supported.
  https://docs.workato.com/en/api-mgmt/api-collections
- **Auth models for callers** (per collection): Auth token (`api-token: <token>` header),
  OAuth 2.0 client credentials (`Authorization: Bearer`), JWT (RSA or HMAC, client-signed),
  OpenID Connect (IdP-issued JWTs). Sources:
  https://docs.workato.com/en/api-mgmt/auth-token, /oauth2, /jwt-token, /oidc
- **Serving quotas** (https://docs.workato.com/en/api-mgmt/limits): job timeout 30 s default,
  240 s max (per-endpoint configurable); payload 5 MB; attachments 5 GB multipart; header 16 KB
  single / 64 KB combined; max 20 API keys per API client; cache entry 10 kB value, 10k entries
  per user ID; tracer payload 1 MB.
- **Caller error semantics** (https://docs.workato.com/en/api-mgmt/calling-apis): 401 with
  diagnostic codes 4011-4014 (unrecognized/missing token, invalid credentials, endpoint not
  found); 4040 recipe inactive surfaces as 404; 429 for concurrency and rate/quota limits;
  422 when the recipe job failed; 504 when the job exceeded the endpoint timeout. Note: some
  bad URLs return 401 instead of 404 by security design. Response header
  `X-Workato-Recipe-Id` identifies the serving recipe.
- Access policies, concurrency, caching, per-endpoint logs: https://docs.workato.com/en/api-mgmt/api-access-policies,
  /api-concurrency, /api-caching, /api-logs

---

## 10. Callable recipes and recipe functions (inbound recipe-to-recipe)

Sources: https://docs.workato.com/en/features/callable-recipes/new-call-trigger,
/return-response-action, /call-recipe-action, /migrating-to-recipe-functions-api-recipes

- Called via the "Call recipe" connector action or a webhook-style **New Call for Recipe**
  trigger, not via raw HTTP; API recipes have replaced their public-endpoint role.
- Support synchronous response and wait-for-async-callback patterns (wait-for-resume).
- Recipe functions: workspace-internal callable logic; migration guide covers the split.
- Jobs can be resumed externally via `POST /api/job/resume` with a resume token.
  https://docs.workato.com/en/workato-api/jobs

---

## 11. Webhooks and trigger callbacks INTO Workato

Sources: https://docs.workato.com/en/workato-api/recipes (webhook_url field),
https://docs.workato.com/en/connectors/opa-webhook, https://docs.workato.com/en/recipes

- Every real-time (webhook) trigger recipe exposes a **webhook URL** of shape
  `https://www.workato.com/webhooks/rest/<token>/<recipe-slug>` (returned as `webhook_url` in
  recipe details). External systems POST to it to start a job.
- No documented API to create/retrieve webhook URLs except reading recipe details; rotating a
  token means recreating the trigger (docs do not document rotation, observation from field).
- On-prem groups can receive webhooks through the OPA webhook connector.
- Outbound callback pattern: recipes can call back out via HTTP connector; the API platform
  adds structured request/response with schema validation instead.

---

## 12. Other surfaces

- **Developer/Embedded API MCP server:** see section 8.
- **Workflow apps:** no dedicated developer REST API found in the docs corpus; workflow app
  pages live under product/marketing docs only. https://docs.workato.com/en/tools
- **Data pipelines (ELT accelerator):** docs exist as an installed accelerator
  (https://docs.workato.com/en/accelerator-elt-pipeline-create); no developer API found for
  pipeline CRUD. (Speculation: pipelines are recipe-based under the hood, so RLM packages may
  carry them, but nothing documents a pipeline-specific endpoint.)
- **API platform for Embedded partners:** full API platform management mirrored into OEM APIs
  including portals. https://docs.workato.com/en/oem/oem-api/api-platform and
  https://docs.workato.com/en/oem/apip-enablement

---

## Gaps and feedback items for the product team

Honest raw material. Items marked (speculation) are inference, not documented fact.

1. **No REST API to send a prompt to a Genie.** Agent Studio API exposes genie CRUD, skills/KB
   assignment, and read-only conversation history, but nothing to START a conversation or run a
   genie on demand. Teams that want "trigger genie from an external system" must go through
   recipes or the MCP server. Speculation: this may be deliberate (conversations are
   workspace-scoped UI objects), but the asymmetric read-only conversation surface looks like a
   gap, not a decision. https://docs.workato.com/en/workato-api/agent-studio

2. **Skills REST surface is create/read only.** No update, delete, or recipe-to-skill wiring
   endpoint documented at the REST level, while the AIRO MCP server exposes update and
   assign/unassign. Parity between MCP tools and REST is undocumented and unclear.

3. **Two parallel promotion APIs with no documented relationship.** Package import
   (`/api/packages/import`) and Projects build/deploy (`/api/projects/:id/build`, deployments
   with reviewers) overlap in purpose. No doc says which one is the strategic path, whether
   deployments supersede manifests, or how they interoperate (can a deployment consume an
   export manifest?). https://docs.workato.com/en/workato-api/projects vs
   https://docs.workato.com/en/workato-api/recipe-lifecycle-management

4. **Package import is one silent kill-switch away from downtime.** `restart_recipes` defaults
   to false, and imported recipes that were running stay stopped if you forget it. A safer
   default or a dry-run/diff endpoint would remove a whole class of promotion incidents.

5. **Webhook URL management is under-served.** No documented endpoint to list, regenerate, or
   rotate webhook trigger URLs, or to inspect recent webhook deliveries that failed schema or
   auth. Secret rotation is effectively a rebuild. https://docs.workato.com/en/workato-api/recipes

6. **Data tables split across three hosts.** Management on `workato.com`, records on
   `data-tables.workato.com`, uploads via a third signed URL. Every client must special-case
   host routing; a single gateway would remove it. https://docs.workato.com/en/workato-api/data-tables

7. **No Workflow Apps API.** A flagship product area with no documented programmatic surface
   (no create/read of app records, users, or pages). Everything must go through its recipe-side
   webhook endpoints. https://docs.workato.com/en/tools

8. **V1 endpoints being deprecated are interleaved in the same index as v2 with no sunset
   dates.** API platform v1 clients/access profiles carry only "prepare for future deprecation."
   Docs give deprecation dates for legacy API keys but not for v1 API platform endpoints.

9. **Rate limit headers undocumented.** The limits page states quotas but no doc describes
   response headers for remaining quota or retry-after behavior. Clients must discover 429
   handling by trial. (Speculation: headers may exist but are undocumented.)
   https://docs.workato.com/en/workato-api/limits

10. **401-masquerading-as-404 by design needs better surfacing.** Returning 401 for bad URLs
    (security measure) is documented once, deep in calling-apis; the diagnostic codes table
    (4011-4014) exists only in exported logs, not in the live response body.
    https://docs.workato.com/en/api-mgmt/calling-apis

11. **Genie conversation events and job traces are separate worlds.** There is a conversation
    events API for genies, but no dedicated streaming/diff endpoint for recipe job traces.
    LIVE-PROBED CORRECTION 2026-10-16: GET /api/recipes/{id}/jobs/{job_id} DOES return
    step-level data in its `lines` array (per-step adapter_name, adapter_operation, input,
    output, recipe_line_number, line_stat, mask_data) — the earlier "no step-level data"
    claim was wrong; what's missing is a steps SUBRESOURCE (GET .../jobs/{job_id}/steps → 404)
    and any streaming/diff surface. Step data exists; it is per-request and unstreamable.

12. **Connection creation requires out-of-band schema knowledge.** Connection create/update
    need provider-specific input fields documented in a separate parameter reference per
    adapter; no machine-readable schema endpoint (the SDK `generate_schema` helpers cover
    custom connector field schemas, not connection auth fields).
    https://docs.workato.com/en/workato-api/connections-parameters-dev

13. **Embedded v1 vs v2 environment provisioning semantics differ silently** (existing assets
    land in DEV under v1, PROD under v2). Nothing at the endpoint names signals this; easy to
    mis-provision a customer workspace. https://docs.workato.com/en/oem/oem-api/managed-users

## Raw recipe-code PUT: unmapped step inputs are silently dropped (2026-10-16, BSYS-29757)

When updating a recipe via `PUT /api/recipes/<id>.json` with hand-built step JSON
(the code-as-JSON-string body), **any step input mapping whose fields are not
declared in the step's `extended_input_schema` is silently dropped on save** —
the PUT returns `success: true`, and `start` then fails validation with
`Unknown data field "X" used in ...` (or worse, saves a step that runs with
empty inputs). Observed on a `workato_recipe_function.call_recipe` step: the
hand-authored `input.parameters` mappings vanished because
`extended_input_schema` was omitted; a `return_result` step's `input.result`
mapping vanished the same way. **Rule:** hand-built steps must carry BOTH
`extended_input_schema` (declaring every input field the mappings use) AND
`extended_output_schema` (declaring every output field downstream datapills
reference) — then verify by reading the recipe back and diffing the step trees,
never by trusting the PUT success. Also: `start` can silently no-op after a
push — always re-fetch and assert `running: true` (caught live: v2 saved,
start returned success but `running` stayed false due to the schema error).

## Multipart-first writes (2026-10-31, Jasper-confirmed)

Several Workato write endpoints accept structured fields ONLY as top-level multipart
fields carrying JSON-encoded strings — a JSON body wrapper (or a `meta`-nested object)
is rejected or silently ignored. Proven on the MCP Apps surface: `csp` on
`PUT /api/mcp/mcp_servers/:handle/apps/:app_id` works as `-F 'csp={...}'` (prod
>= v1.1278.0) and is unwritable any other way (JSON-body object 400s "Must be a
String"; meta-wrapped ignored; create-time meta fields dropped).

**Law:** when a Workato write endpoint rejects or silently drops a structured field in
a JSON body, try the multipart form with the field as a top-level JSON-encoded string
before concluding the field is UI-only. Verify against the SERVED artifact (the
downstream projection), not the listing endpoint's summary (which can diverge from the
store). The MCP Apps surface's `wt --csp` flag encodes this.

**Tool hierarchy for Workato ops (Josh 2026-10-31):** devapi-workato MCP first (semantic,
Atlassian-MCP shape), wt CLI second (mandatory for prod writes), AIRO last resort.
