# Slack native MCP (mcp.slack.com) — recon 2026-10-14

Purpose: Slack's OFFICIAL MCP (Josh: "supports formatted drafts"). We want it
working in Claude Code (mission 1: formatted draft) and we want its
endpoint/input/response shapes copied into OUR slack-workato MCP (mission 2).
Ours was built on the undocumented `drafts.create` endpoint; theirs is the
reference implementation Slack ships.

## Transport + auth (probed live 2026-10-14)

- Endpoint: `https://mcp.slack.com/mcp`, Streamable HTTP. Anonymous POST
  initialize → 401 JSON-RPC `{"code":-32001,"message":"missing_token"}`.
- Protected resource metadata: `https://mcp.slack.com/.well-known/oauth-protected-resource`
  → authorization_servers = itself; bearer_methods header+form; scopes:
  canvases:read/write, channels:history/read/write, chat:write, emoji:read,
  files:read/write, groups/im/mpim:history/read/write, lists:read/write (NEW
  scope family — Slack Lists), plus more past the head cut.
- Auth server metadata (`/.well-known/oauth-authorization-server`):
  - issuer = https://mcp.slack.com
  - authorization_endpoint = **https://slack.com/oauth/v2_user/authorize**
  - token_endpoint = **https://slack.com/api/oauth.v2_user.access** (same
    user-token family our VUA connection uses)
  - grants: authorization_code, refresh_token, **urn:ietf:params:oauth:grant-type:jwt-bearer**
    (JWT-bearer = token-exchange/service path worth exploring for our recipes)
  - token_endpoint_auth_methods = **client_secret_post** (requires a
    registered client's secret — NO registration_endpoint, NO DCR)
  - PKCE S256 supported
- CONSEQUENCE: `claude mcp add slack-native https://mcp.slack.com/mcp` fails
  health with "Incompatible auth server: does not support dynamic client
  registration" — Claude Code's auto-OAuth needs DCR, Slack deliberately
  doesn't offer it (pre-registered AI-vendor clients instead).
- UNBLOCK PATH: register/get a Slack app's client_id+secret → script the
  authorization_code + PKCE flow with a local listener (same loop as the
  slack-workato re-auth playbook: in-turn flow, Chrome has the Slack session)
  → refresh_token → attach server with `claude mcp add --header "Authorization:
  Bearer <token>"` and refresh out-of-band. jwt-bearer grant may remove the
  refresh dance — unexplored.

## Mission 2 hypotheses (to verify once connected)

- Formatted drafts: native MCP's draft tool almost certainly accepts Block Kit
  `blocks` (or rich text_blocks) on the draft surface — our `drafts.create`
  integration only sends plain `text`. If the undocumented endpoint accepts a
  `blocks` array, our MCP gets formatted drafts with a one-field addition.
- Compare: tool list, input schema, response envelope (their draft tool's
  response shape vs the raw drafts.create response ours proxies).
- Capture actual request/response JSON of a formatted draft create via MCP
  proxy logging or verbose client.

## CONFIRMED (2026-10-14, staging-post v2 live test): chat.postMessage has NO list support
- "- " prefixes in postMessage text render as LITERAL dashes; mrkdwn has no list/indent syntax at all. Bold/links/emoji only.
- Real lists in Slack messages exist ONLY as rich_text blocks (rich_text_list, indent 0-9), created either by the composer interactively or via a `blocks` param on chat.postMessage / drafts.create. No text encoding carries list structure.
- Composer conversion of "- " works while TYPING; paste conversion is unreliable (Josh's live copy-paste test flattened twice).
- Manual path that always works: paste text, select the lines, Cmd+Shift+8 (bullet list) — composer wraps selection in a real rich_text_list.
- OUR MCP FIX (mission 2 payoff): add a blocks field to our create_message_draft / post_message recipes — that's exactly what native Slack MCP does for "formatted drafts". Without it no text-based path will ever carry indents.
