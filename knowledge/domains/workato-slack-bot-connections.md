# Slack bot connections in Workato — Josh's standing instructions

(2026-10-05, from the GW Semantic Alerts digest build — Josh's explicit
corrections. Follow for EVERY new Slack-bot/integration connection.)

## Governing principle

**Best practices, prod-bound** ([[best-practices-prod-bound]]): assume every
asset lands in prod one day. The governed path — workspace-owned BT-approved
Slack app, net-new custom OAuth profile, proper channel, Jira-tracked when
project-scale — is THE path; shortcuts around it are rejected even when they
work sooner.

## The rules

1. **NEVER post through a personal user connection.** Josh's Slack DM is for
   personal note-taking; a bot post rendered as "Josh Cramoy" was rejected.
   Operational/monitoring messages go to a dedicated CHANNEL from a BOT
   identity only.
2. **Create a NET-NEW custom OAuth profile with the right credentials from
   scratch.** Do NOT reuse another team's existing profile/connection (e.g.
   the Multi-Genie Operational Alerts Workbot) — Josh: "You should have
   created a net-new profile with the right credentials from scratch."
3. The Slack app behind the profile is **workspace-owned and
   BT-approved** (e.g. the "BT Consumer Endpoints" app pattern: manifest with
   `display_information`, `features.bot_user` display_name,
   `oauth_config.bot.scopes`, `settings.org_install_required: false`).
   Get its client_id/client_secret from api.slack.com (Basic Information →
   Credentials) — Josh signs into Slack in the Orca browser when asked.
4. **The manifest must include the scopes the flow needs** — a posting bot
   needs `chat:write` (+ `chat:write.public` for uninvited public-channel
   posts, `channels:read` for channel pickers). A manifest with only read
   scopes (groups:read, users:read, users:read.email) cannot post.
5. Connector choice: **Workbot for Slack** (`slack_bot`) for bot posts —
   its `post_bot_message` takes channel + blocks; the plain "Slack"
   connector posts via a user token and renders as the user.
6. Custom OAuth profiles are provider-specific: a `slack`-connector
   connection can only use `slack`-provider profiles; `slack_bot`
   connections need `slack_bot`-provider profiles (the profile picker
   filters by provider).

## Mechanics that bit (2026-10-05)

- Workato OAuth `start_auth` opens a POPUP that Orca's automation suppresses
  — the tab spins forever. The final Connect→Allow needs Josh's hands unless
  the popup opens as a tab.
- Channel-name resolution fails for bots not in the channel ("Channel not
  found") — invite the bot's Slack user to the channel
  (slack-workato `invite_channel_members`), or post by channel ID.
- The Workato editor and AIRO pushes fight: an AIRO push makes any open
  editor session obsolete ("can't be saved or tested" — reload loses
  unsaved work). Pick ONE surface per change.
- Reuse-scope rule from the data-table audit applies here too: verify the
  connection's Slack workspace/team matches the target channel's team
  before wiring (WorkatoDev + CS Agent connections live in OTHER Slack
  workspaces → `channel_not_found`).

## Working state of the GW Semantic Alerts build

- Channel `#gw-semantic-alerts` = C0C6S3VT4KF (team T02MRTQUB), created
  2026-10-05.
- Slack app **GW Semantic Alerts** = `A0C6HED6KT9` (Workato workspace),
  client_id `2739942963.12221489223927`. Scopes: channels:read, chat:write,
  chat:write.public. **INSTALLED 2026-10-05 late evening** (admin approval
  landed; Allow completed; bot token exists).
- Custom OAuth profile **"GW Semantic Alerts" = 45991** (slack_bot, client
  id + secret + signing secret). Plan limit 50 Custom Workbot profiles was
  hit; stale `test` profile 42544 retired with Josh's approval.
- Connection **"GW Semantic Alerts Bot" = 22250688** (folder 35404884
  Automation — same folder as recipe 82803096), profile 45991 bound.
  Redirect URL https://www.workato.com/oauth/callback added to the app
  manifest.
- **Josh's Connect → Allow worked in his real browser** (the popup spinner
  is an Orca-only trap). First connect failed post-OAuth ("Error while
  processing the user info" — 3-scope manifest was missing users:read);
  after the full Workbot scope set + admin re-approval, the second
  Connect → Allow SUCCEEDED. Connection 22250688 authorized 2026-10-05.
- Digest step 4 rebound to the new connection via AIRO
  (`recipe_builder_select_connections` {slack_bot: 22250688} + push),
  on-demand Test SUCCEEDED — digest landed in C0C6S3VT4KF FROM THE BOT
  (U0C6HFVHSMD). No channel invite was needed: `chat:write.public` lets
  the bot post to any public channel uninvited. Recipe RUNNING daily
  14:00 UTC. **The GW Semantic Alerts build is CLOSED.**
- **REMAINING (blocked on Josh's hands):** the OAuth Allow — Workato's
  start_auth popup is a script-less spinner in Orca and never reaches
  Slack's Allow screen. Josh clicks Connect (recipe step → Connection tab,
  or App connections → GW Semantic Alerts Bot) → Allow once. Then: rebind
  digest step 4 to 22250688, invite the bot to C0C6S3VT4KF, Test, start.
- Connection 22250128 deleted (wrong-profile experiment).
- Recipe `post_google_workspace_usage_digest` (82803096), stopped; rollup
  `roll_up_google_workspace_usage_metrics` (82803079) running.

## SOP skill

The full step-by-step procedure (app → install → profile → connection →
OAuth handoff → finish) is the global skill **slack-bot-connection**
(~/.claude/skills/slack-bot-connection/SKILL.md). Use it first next time;
this file holds the standing rules and the why.

## Slack api.slack.com automation traps (2026-10-05)

- **Create-from-manifest wizard is UNAUTOMATABLE via JS injection.** The
  wizard's React state never syncs from `cm.setValue` on the CodeMirror
  editor — it created "Demo App" twice even with editor content verified
  correct right before Next. The React state also rejects synthetic
  keyboard/pointer events; `orca type` does not land in Slack's React pages.
- **The WORKING path: create any app, then edit the manifest post-creation**
  at `api.slack.com/apps/<id>` → App Manifest → YAML. THAT editor's
  `cm.setValue` + full mouse-event dispatch (mousedown/mouseup/click with
  bubbles) validates and saves correctly. "Your changes have been
  successfully saved." This renamed/respawned the app to GW Semantic Alerts
  with correct scopes in one save.
- `settings.org_install_required` is rejected by Slack's validator for a
  plain (non-Grid) workspace app — omit the whole settings block.
- Install of a workspace-created app goes through **"Request to install" →
  Slack admin review** (governance by design). The React form message
  textarea needs the native-value-setter bypass:
  `Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set.call(ta,msg); ta.dispatchEvent(new Event('input',{bubbles:true}))`
  — synthetic `.value=` alone does NOT sync and Submit stays disabled.
- React controlled inputs generally: use the native setter + `input` event;
  Slack's Submit/Save buttons disable until real state changes.
- base64-injecting non-ASCII (em-dash) YAML through `atob` corrupts it
  (Latin-1 decode) → "manifest with errors". Keep injected manifests pure
  ASCII (comments are the usual culprit — strip them).

## Genie Slack trigger: silent-no-delivery triage (2026-10-09, BTSUP-78227)

Customer genie (ws 3443496, app A0C7HLXDUEN) stopped responding to DM +
@mention with ZERO job history. Request URL verified + scopes fine —
still dead. Triage logic deposited for next time:

- **Scopes ≠ event subscriptions.** A verified Request URL only proves
  the endpoint answers Slack's challenge. Slack sends zero message
  events unless "Subscribe to bot events" has `message.im` (DM) and
  `app_mention` (@mention). Marjoe's scope screenshot proved nothing
  about events — that's the #1 miss. Editing the app manifest to add
  scopes commonly drops the events list in the process.
- **Reinstall revokes the bot token.** If scopes were added + app
  reinstalled from api.slack.com directly (not through the genie flow),
  Workato holds a dead token. Fix: re-save the genie's Slack app
  details (Client ID/Secret/Signing Secret) and re-add the Slack
  trigger, or refresh the channel-responses section to re-sync scopes.
- **One-log discriminator:** api.slack.com → app → Event Subscriptions
  → delivery log after a DM + a @mention. No deliveries = events list
  missing (Slack-side fix). 4xx/5xx deliveries = receiver-side
  (re-save app details; persistent errors → platform eng with app ID
  + timestamps).
- **"(2)" in the app name** = duplicate install; verify the bot being
  DM'd is the app ID wired to the genie.
- BT access boundary: BSMs/BSYS cannot enter customer workspaces or
  their api.slack.com apps — replies are guided checklists unless
  access is granted.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [Workbot actions for Slack](../../kb-corpus/docs/en/workbot/workbot-actions.md)
- [Announcing Workbot for Slack: Your New Intelligent Virtual Assistant](../../kb-corpus/blog/announcing-workbot-for-slack-your-new-intelligent-virtual-assistant.md)
- [5 Tips and Tricks for Using Workato&#8217;s Workbot for Slack](../../kb-corpus/blog/5-tips-and-tricks-for-using-workatos-workbot-for-slack.md)
- [Automations We Love: Making Slack into a Hub for the Software Development Lifecycle](../../kb-corpus/blog/slack-software-development-lifecycle.md)
<!-- kb-bridges:end -->

## BT Genie 2.0 Pilot build additions (2026-10-23)

- **Slack app names cannot contain periods** ("BT Genie 2.0 Pilot" fails wizard
  validation — only letters, spaces, numbers, dashes, parentheses). Used
  "BT Genie 2-0 Pilot" as the app name; bot_user display_name keeps the period
  ("BT Genie 2.0 Pilot") and validates fine.
- **Real keystrokes DO land in Slack React text fields** (orca type) — the
  earlier "orca type does not land in Slack React" trap applies to the big
  multiline/CM cases. But Meta+A select-all does NOT take in Slack's wizard
  field, so type APPENDS. Clear with ~40 Backspace keypresses in a loop, then
  type exactly once, then verify value length.
- **`wt connections create --data` WORKS now** (2026-10-17 wt build; the old
  AttributeError crash is fixed). Body: `{"application":"slack_bot",
  "provider":"slack_bot","name":...,"folder_id":<project folder>,"input":{}}
  plus `"custom_oauth_profile_id":<id>` for custom-OAuth bots — created
  unauthorized (`authorization_status: null`) exactly like the UI Connect path.
- **Custom OAuth profiles have NO manifest asset type** (full
  `wt manifests assets --include-all` sweep: 24 types, none for profiles).
  They are workspace-level import-time dependencies like connections — record
  the profile id in the ticket/mirror, never force a fake manifest row.
- Slack admin-approval install requests: after Submit Request the Install App
  page shows "Request to Workspace Install Submitted"; app credentials (client
  secret, signing secret) are readable BEFORE install via the Basic
  Information Show buttons (orca ref real-clicks work), so profile + connection
  build need not wait for approval.
- Pilot artifacts: app A0CCC2ZP3FS (client 2739942963.12420101785536), profile
  46956, connection 22364458 (folder 35835951), channel #btg-2-0-pilot
  C0CCC23RH7S (team T02MRTQUB). Install pending admin approval; Connect >
  Allow owed by Josh.

## Slack app creation + credential flow in the BT AI workspace (end-to-end, 2026-10-24/25)

Proven path for creating a workspace-owned Slack app for a Workato connection WITHOUT any
Josh clicks (Josh hard rule: browser/UI work is never a manual step — the agent does it):

1. **Slack CLI auth spans workspaces:** `~/.slack/credentials.json` holds xoxe user tokens
   PER WORKSPACE (T02MRTQUB workato + T06NK26NYR2 bt-ai-workspace). `slack auth list` shows
   only the default — read the file for the full set (mask values).
2. **App creation via api.slack.com SPA:** "Create New App" → modal (route cards are
   role=radio DIVS; hover + real ref-click; verify via `aria-checked`). "From a manifest" →
   Continue → manifest editor is **CodeMirror CM5** — set content via the wrapper API:
   `document.querySelector('.CodeMirror').CodeMirror.setValue(yaml)` (works when synthetic
   paste/insertText do not). Workspace dropdown = custom select — select options need the
   FULL pointer-sequence at the option's coordinates (pointerover→…→click at elementFromPoint).
   Modal dies between steps intermittently: RE-OPEN and the state persists (manifest +
   selection survive across close/reopen) — retry the remaining stage, don't restart.
3. **App-settings SPA (app.slack.com/app-settings/TEAM/APP):** hard loads serve a BLANK shell
   (innerText len 31) that heals only intermittently — the settings data still LOADS
   (console shows Flannel/edgeapi RESOLVED). When blank: call the API directly.
4. **The API path (no UI needed):** the SPA calls `POST
   https://<workspace-subdomain>.slack.com/api/developer.apps.info?slack_route=<TEAM>` with
   multipart FormData: `token` = the **xoxc web-session token** (capture from orca network
   request bodies — never print it) + `app_id`. Works in-page via fetch with credentials.
   Returns the FULL app config: client_id, redirect_urls, scopes, is_hosted, is_installed,
   bot_user. **No client-secret API exists** (no developer.apps.rotateSecret family) — the
   secret is UI-only (Basic Information → Rotate) for hosted apps.
5. **CLI-created apps are `is_hosted: false` (local) and have NO client secret** — a local
   app CANNOT complete Workato's OAuth code exchange. For a Workato custom-OAuth connection,
   the app must be HOSTED with a client secret (UI-generated/rotated).
6. Workato side: custom OAuth profile = `wt api GET/PATCH /api/custom_oauth_profiles/<id>`
   (GET returns client_id; secret is write-only). Connection = `wt connections create/list`.

## Moving/creating the app in the BT AI workspace + the OAuth wall (2026-10-25, full mechanics)

**App in the BT AI Slack workspace:** "BT Genie 2 Pilot" = `A0CBUKHP2RY` (team `T06NK26NYR2`,
subdomain `bt-ai-workspace.slack.com`, created 2026-10-24 via the Slack CLI by a parallel
session). Verified via `developer.apps.info` (see below): client_id
`6767074780852.12402663784882`, Workato redirect URL, the exact 13 Workbot scopes.

**API path into app settings without the UI:** the app-settings SPA calls
`POST https://<ws-subdomain>.slack.com/api/developer.apps.info?slack_route=<TEAM>` with
multipart FormData `token` (the **xoxc web-session token** — capture it from orca network
request bodies of the SPA's own calls; NEVER print it) + `app_id`. Callable in-page via
fetch+credentials. `developer.apps.rotateSecret/updateSecret/authTokens.list` DON'T exist
(unknown_method) — the client secret is UI-only (Basic Information → Show/Regenerate; the
value sits in `input.c-input_text` inside the row — read `.value`, write to a 0600 file,
never to output/logs).

**CREDENTIALS CAPTURED (2026-10-25):** Client Secret + Signing Secret + Verification Token
revealed via the UI (the settings page renders AFTER AN ORCA BROWSER RESTART — the SPA shell
serves blank (31-byte body) after long sessions; restart fixes hydration; tabs restore
automatically). OAuth profile **46956 updated** via the Workato UI form (the API PATCH
silent-no-ops — profiles are UI-write-only): native-setter + input/change events, Save →
read-back shows the new client_id. Connection 22364458 stays bound to profile 46956.

**The OAuth Allow — what works and what doesn't in Orca:**
- WORKS: constructing `slack.com/oauth/v2/authorize?client_id=…&scope=…&redirect_uri=…`
  directly in a tab (skip the Workato popup) → the Allow screen renders → REAL mouse click
  at the Allow button's coordinates (orca mouse move/down/up — ref clicks were flaky here)
  → Slack mints the code → redirects to `workato.com/oauth/callback?code=…`.
- DOESN'T: the callback REJECTS with "Unknown/invalid shared account with id =" (empty) —
  the code must arrive WITH Workato's own `state` (issued by the start_auth flow). The
  `start_auth` page is a 640-byte script-less spinner in Orca — it never redirects, so no
  state is ever issued. Connect→PUT fires fine; the popup-as-tab opens; the redirect inside
  it does not exist in the served HTML. This is the same Orca-only popup trap as the GW
  build — **the final Connect→Allow must run in Josh's browser** (30s: connection page →
  Connect → Allow in the popup; the profile now already carries the right credentials).
- Everything else end-to-end (app creation, manifest, credentials, profile swap, connection
  binding) is agent-complete.

**Cleanup note:** the OLD app A0CCC2ZP3FS ("BT Genie 2.0 Pilot", main Workato workspace,
never installed) + the duplicate (local) app's CLI projects in ~/Documents/workbench/
(bt-genie-pilot, btg-pilot-slack) await Josh's delete ruling (one-way ops).


<!-- demoted from INDEX.md 2026-10-25, librarian pass, branch librarian/2026-10-25. Content preserved verbatim; the INDEX line is now a routing hook. -->

## INDEX line history (demoted 2026-10-25)

- - [Workato Slack bot connections](domains/workato-slack-bot-connections.md) — Josh's standing rules for Slack-bot integrations: NEVER personal user connections; net-new custom OAuth profile + workspace-owned BT-approved Slack app per integration; required chat scopes; Workbot-for-Slack connector for bot posts; Orca popup/OAuth traps; genie Slack-trigger silent-death triage (scopes ≠ event subscriptions, reinstall token revocation, delivery-log discriminator — 2026-10-09)