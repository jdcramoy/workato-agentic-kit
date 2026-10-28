# HR Genie auth-fix playbook — end-user "cannot reauthenticate" / OAuth failures

Canonical SOP for BTSUP-class tickets where an end user reports the HR Self
Service Genie failing auth, "it says it can't reauthenticate", auth failed on
reconnect, or MCP tools returning auth errors. Proven on BTSUP-76177 (2026-09)
and BTSUP-77184 (2026-10-10). Work top to bottom — each check eliminates a
hypothesis; do not skip to the reset without the checks.

## Step 0 — scope the symptom

- Pull the ticket + Slack thread. Note: reporter, first-failure date, whether
  OTHER users are affected (one user = per-user token; many = platform).
- Class: "Genie says it can't reauthenticate", "auth failed" on reconnect, or
  MCP tool calls failing with auth errors after the user already tried the
  client-side disconnect/reconnect workaround.

## Step 1 — verify the platform side is healthy (read-only)

1. Genie itself: `genie_list` / genie overview on PROD — status `started`,
   skills attached, KB attached. (77184: gin-AYcm4fwE-rtsAJC-CD healthy, 21
   skills.) A stopped genie is a different fix — stop here if stopped.
2. Fleet runtime connection sweep:
   `wt connections list --runtime --profile josh-prod` (grep by email/name).
   One user's connection lost + everyone else fine = per-user stale token.
3. Prod end-user MCP server identity + VUA state (see Step 2).

## Step 2 — check the VUA-revert trap (BSYS-26815 class)

Any recipe push can silently revert connection personalization from "End
user's connection" (VUA Required) to "This server's connection" — which
produces EXACTLY this symptom while everything else looks healthy.

Check via the signed-in prod UI's own JSON API (fetched in-page, no special
auth): `GET /web_api/mcp/servers/<HANDLE>/tools.json` — every tool must read
`vua_required: true`. Also read the Connections tab
(`/connections_project_assets`): radio "End user's connection" must be
checked, and note the parent connection tile ("Used by N of N tools").

- Prod HR Genie Workday End-User server handle: `mcps-AYcm4fwf-fAP-CD`
  (the dev handle `mcps-AYbrRaxY-dhF-CD` 404s against prod — always resolve
  the prod-scoped handle; find it in the AI Hub MCP servers UI list).
- 77184 result 2026-10-10: 19/19 tools VUA Yes, personalization correct →
  revert trap DISPROVEN. If it HAD fired: fix = re-select end-user connection
  on each affected tool, save, re-verify tools.json — done, no reset needed.

## Step 3 — find the user's stale runtime child (the reset target)

`wt connections list --runtime --profile josh-prod` (JSON: strip the `⚠️ wt:
PRODUCTION instance…` warning line before parsing) and grep the full list for
the user's email. Expect ONE `application: "mcp"` runtime child per user,
named `MCP (Model Context Protocol) connection - <email> - <suffix>`, with a
`parent_id` (the server-side MCP parent — do NOT touch the parent).

The tell: `connection_lost_at` timestamp ≈ the day the user first reported
the failure, while `authorization_status` may still misleadingly read
`success`. (77184: Rodrigo's 19245566 lost 09-24 23:18 PT, ticket filed
09-25.) A lost-at date that old with the user still blocked = the stale
artifact the client-side reconnect cannot refresh.

## Step 4 — the backend reset (PROD WRITE — Josh's gate)

Delete the stale runtime child connection:
`wt connections delete <id> --profile josh-prod` → `"status": "deleted"`,
read-back 404. This is the entire "backend reset" — the guided reconnect
below creates a fresh connection. Watch for `{"message": "Too many requests"}`
under swarm load; retry with ≥75 s backoff.

## Step 5 — post the guided reconnect (the canonical 11 steps)

Verbatim from BTSUP-76177 comment 1107512 (Josh's approved wording — reuse it,
adapt only the greeting; do NOT shorten to "just reconnect"):

> I've reset your connection on the backend. Please follow the instructions
> below closely to ensure you get reconnected properly.
>
> The fix for this is more subtle than just disconnecting and reconnecting
> from the Genie. Please follow these steps exactly:
>
> 1. BT has reset your connection on the backend
> 2. Prompt the Genie again and it will present a button to login/connect
> 3. Click the connect/login prompt from the Genie
> 4. This will take you to the Workato verified user login screen
> 5. Before doing anything else or connecting, look to the right of the
>    Workday connection names and there should be buttons that say
>    "Disconnect"
> 6. Disconnect the Workday connections
> 7. Once disconnected, click "Connect" again
> 8. This should bring you to the Workday Login Screen
> 9. Login as usual through Workday Single Sign On
> 10. This will bring you back to the Workato VUA. Now click "Complete
>     Connection"
> 11. You should be redirected back to Slack. If not, open your Slack desktop
>     application again and start a new chat and test out your connection

## Step 6 — close the loop

Track the ticket until the user confirms a working connection (the
Slack-posts follow-up rule applies to any message sent under Josh's name).
If both checks passed and the reset did not fix it: escalate to the product
team with timestamps (Patricia Guevarra's thread is the product-side path) —
that is hypothesis 3, a step-up/reauth product defect, and there is nothing
further to fix on our side.

## Evidence anchors

- BTSUP-76177: original fix, comment 1107512 (steps).
- BTSUP-77184: full re-run 2026-10-10 — VUA clean, reset done, comment
  1134833 (steps re-posted).
- BSYS-26815 / memory `bsys-26815-benefits-skill-state`: the VUA-revert trap.
- Investigation file: `~/.claude/knowledge/projects/hr-genie/btsup-77184-and-72246-investigation-2026-10-09.md`.
