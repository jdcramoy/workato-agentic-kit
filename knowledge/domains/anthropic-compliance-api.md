# Anthropic Compliance API — proven path for claude.ai org data

Status: PROVEN, live-verified 2026-10-15. This is not a "path exists, pending
prerequisites" surface — the key is stashed and both endpoints answer 200.
First proven use: Google Semantic MCP conversation mining (2026-10-11);
re-verified for BTSUP-78827 (Claude Projects extract).

## The ready path

- **Auth**: macOS keychain, never re-request from an org owner.
      security find-generic-password -s anthropic-compliance-key -a josh -w
  Key shape `sk-ant-api01-...` (Compliance Access Key, scope
  `read:compliance_user_data`). Stashed 2026-10-11.
- **Headers**: `x-api-key: <key>` + `anthropic-version: 2023-06-01`.
  NOT `Authorization: Bearer` — Bearer appears in a docs example and is wrong
  for this surface (cost a dissent round on BTSUP-78827).
- **Base URL**: `https://api.anthropic.com` directly. Do NOT route through
  `ANTHROPIC_BASE_URL` proxies/gateways — they don't host the compliance API
  and 404 silently (trap encoded in mine.mjs).
- **Org**: single org `Workato, Inc.`, uuid `89dcd16e…` — no multi-org
  scoping ambiguity to resolve.

## Endpoint surface (all verified 200)

| Endpoint | Returns |
|---|---|
| `GET /v1/compliance/organizations` | org list (1 page here) |
| `GET /v1/compliance/apps/projects` | projects, paginated (`limit` ≤100, `next_page`) |
| `GET /v1/compliance/apps/sessions/local[/messages]` | org conversation sessions/messages (mine.mjs) |
| `GET /v1/compliance/organizations/{org_uuid}/users` | org users |

Project fields: `id` (tagged `claude_proj_…`), `name`, `created_at`,
`updated_at`, `deleted_at`, `is_private` (false = visible to all org members),
`organization_uuid`, `user: {id, email_address}`.

## Known gotchas

1. **Bearer header is wrong** — use `x-api-key`.
2. **Tagged ID ≠ URL**: claude.ai project URLs use a UUID; the API returns
   `claude_proj_...`. Mapping not documented — confirm before promising a
   project-URL column.
3. **Departed creators**: `user` is null — rows ship with empty creator
   fields (API reports current members only).
4. **Don't route via proxy base URLs** (silent 404).
5. Workato-side joins are the real work: Workday for display names and for
   reporting-tree filters (e.g. Dan Kennedy's CS org).

## Where this applies

Any ask for claude.ai org-level inventory: projects, conversation content,
org users. Check THIS doc + keychain before routing an ask to org owners —
see memory `kb-search-before-triage` (born from overstating this exact
prerequisite in the BTSUP-78827 customer reply).

## NEVER frame the key as an external prerequisite (Josh, 2026-10-15)

Bit TWICE on the same ticket (BTSUP-78827): after the stash was already on
record here, an agent comment still told the ticket "the key needs a Claude
org owner to generate it; routing to whoever holds the owner seat." Josh's
correction (ticket comment 1140105, 2026-10-15 17:11Z): **"I actually have
access to create the admin key, so no blocker here."**

- The key is stashed (top of this doc) — the extract is executable NOW.
- Even if a fresh key were ever needed, Josh himself can create it in
  claude.ai org settings. There is NO owner-seat routing step, NO external
  blocker, NO "waiting on" state on this surface. Ever.
- A triage verdict that lists this key as a pending prerequisite is wrong on
  its face — treat it like any other stale-claim defect.

Consumer session: `~/orca/workspaces/workbench/Google-Semantic-MCP/scripts/phrase-miner/mine.mjs`
(keys docs in its header comments). Ticket doc:
`projects/btsup-customer-replies/BTSUP-78827-claude-projects-extract.md`.


<!-- demoted from INDEX.md 2026-10-25, librarian pass, branch librarian/2026-10-25. Content preserved verbatim; the INDEX line is now a routing hook. -->

## INDEX line history (demoted 2026-10-25)

- - [Anthropic Compliance API](domains/anthropic-compliance-api.md) — PROVEN path for claude.ai org-data pulls (projects/sessions/users): keychain token `anthropic-compliance-key`/josh stashed 2026-10-11, feature enabled, orgs+projects endpoints live-verified 200 on 2026-10-15; gotchas: x-api-key not Bearer, tagged IDs ≠ claude.ai URLs, null creators for departed members, no proxy base-URL routing (silent 404). Check here BEFORE routing org-data asks to org owners (born: BTSUP-78827 reply overstated known territory as pending prerequisites)