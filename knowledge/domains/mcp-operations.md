# MCP Operations — domain knowledge

Cross-project MCP server/client operations knowledge.

## Client/server lifecycle

- Claude Code `/mcp` reconnect is a CLIENT-side reconnection: it reuses
  existing OAuth tokens and never re-runs a provider consent flow. Any fix
  that requires NEW scopes needs the underlying connection revoked and
  re-consented (see Workato platform file for the Google flow).
- MCP HTTP servers via mcp-remote can duplicate processes on multiple URL
  registrations (readout logs: ~/Documents/Claude/mcp-remote-*.md/.txt,
  2026-07-27); the duplicate-URL check in the session-start hook diagnoses it.
- Claude Desktop MCP reauth bug writeup: ~/Documents/Claude/claude-desktop-mcp-reauth-bug-report.md.

## Hosting patterns

- Workato-hosted MCP servers: auth type workato_idp (tester = Workato
  identity), access gated by Workato user groups on the server asset;
  per-caller VUA connections mean each tester consents their own provider
  account (e.g. Google) on first connect. Server assets live per environment
  (Development vs Production).
- The public Workato MCP marketplace registry (workato-registry MCP) is
  separate from workspace-internal MCP servers.


## claude.ai enterprise connectors in Claude Code — token costs and controls (2026-10-07)

From the Anton thread (75 org connectors, 29k bare-repo context complaint) —
docs-verified + locally reproduced:

- On first-party Claude (Sonnet 4.5+), tool search defers MCP tool
  definitions by default: only tool NAMES + server instructions load at
  session start ("167 tools, 0 tokens"). The residual MCP tax is the
  deferred-name list (~3.5k/190 names, mostly authenticate stubs for
  unconnected servers) — skill descriptions cost MORE (~6.5k/35 skills).
  Org skill-catalog curation is the bigger lever than connector pruning.
- Per-user surgical controls (all verified): deniedMcpServers with
  serverName "claude.ai <Display Name>" blocks individual claude.ai
  connectors; /mcp toggles per project; users can disconnect individual
  org connectors from their own claude.ai account. enabledMcpjsonServers /
  disabledMcpjsonServers apply ONLY to .mcp.json servers, not connectors.
  disableClaudeAiConnectors + syncClaudeAiSkills:false are the
  all-or-nothing flags (kill Atlassian/Slack along with the junk);
  syncClaudeAiPlugins is the third sibling.
- serverName "*" wildcard does NOT work in deniedMcpServers — enumerate
  names (wildcards only on serverUrl/serverCommand).
- Admin side: per-tool ask/blocked controls exist per connector (blocked
  tools never enter the tool list); NO documented per-group/per-role
  connector assignment — provisioning is org-wide. Whether Owner removal of
  an org connector disconnects members who already connected is NOT
  documented (endpoint-change precedent shows member copies can persist as
  custom connectors) — verify empirically before promising it. Managed
  settings (managedMcpServers / managed-mcp.json) are a separate delivery
  path that claude.ai deletion never touches; /mcp marks each server's
  origin.
- Self-serve tip that landed well: tell Claude which connectors to keep,
  have it diff against the full set and write the deniedMcpServers block.

## Claude.ai Research mode hijacks Workato MCP connector calls (2026-10-04 incident)

Source: ~/Documents/ChatGPT/Random Context/claude_research_connector_handoff.md
(mined 2026-10-10; the underlying 26-account Concord investigation was left
OPEN — 10 unresolved diagnostic questions, no recorded resolution).

- With Advanced Research enabled in a claude.ai conversation, the model
  delegates nearly every request to the research agent instead of calling
  available Workato MCP connectors directly (observed verbatim: "While it's
  on, I'm required to send almost every request to the research agent").
  When Claude refuses to use available Workato MCP tools, Research routing
  is a candidate root cause to check FIRST.
- Local vs remote matters: per Anthropic docs, Research can auto-invoke
  remote MCP connector tools but NOT local-MCP-server tools — how a Workato
  connector is registered (remote web MCP vs local desktop extension)
  decides whether Research delegation can succeed at all. Never assume
  locality without evidence.
- Do not prescribe "just turn off the Research toggle": the toggle was not
  findable in the tools menu (stale state / UI defect / rollout gap /
  hallucinated explanation all possible). Have the user confirm the control
  exists before calling it actionable.
- Evidence discipline: shared Claude conversation snapshots hide image
  attachments and omit tool-call traces, tool inventories, connector
  permissions, and errors; the assistant's prose about its own constraints
  is not proof of runtime state. Diagnose with a controlled read-only
  reproduction: record visible model/Research state/connectors → one
  read-only MCP call → repeat outside the Project → toggle Research and
  compare. (Full 8-step protocol in the source file.)

## Legacy-tree mining additions (2026-10-10)

- **mcp-remote OAuth refresh-token race**: multiple live mcp-remote
  processes against the SAME Workato endpoint race rotating OAuth refresh
  tokens and cause repeated interactive auth. Pin `mcp-remote@0.1.38`, one
  process per URL; measure cold OAuth separately from warm tool latency.
  (Gmail MCP v3 build handoff §4)
- **Stale client catalog ≠ executable server**: an advertised MCP catalog
  can diverge from the runtime surface — "tool not found"/"Unknown tool"
  before schema validation = stale client catalog vs server runtime;
  fix is reconnect/refresh and confirming ONE write reaches schema
  validation before benchmarking. Confirm endpoint identity before
  comparisons (a version alias was not the production baseline).
- **"Tool not found" = dispatch-level failure** — no Workato job will
  exist; check the server audit chronology for tool renames/activation
  dates (BTSUP-70714: wrapper called retired `Query_Call_Transcripts`,
  registered tool was `Query_Gong_Transcripts`; McpServerError + zero
  jobs = contract mismatch, not backend outage).
- **runtime-connections UI "Connected" ≠ execution-time authorization**
  (BTSUP-76224): Salesforce failed on the reporter's runtime VUA OAuth
  binding ("connection is broken. Please refresh") while the UI showed
  Connected; recipe-level 30-day history + one failed job with the
  Authorization error localized it. Diagnosis: user-specific re-auth,
  NEVER a shared-connection mutation.
- Custom-connector/VUA traps live in domains/workato-platform.md
  (preserve_in_runtime_connection, push-wipes-personalization, VUA pins
  connector revision, MCP isError gap).

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [Workato Developer API MCP server](../../kb-corpus/docs/en/mcp/developer-api-mcp.md)
- [Multilingual support](../../kb-corpus/claude/docs_en_build-with-claude_multilingual-support.md.md)
- [Clearing Up the Confusion: MCP ≠ Claude Code](../../kb-corpus/confluence/intbt/1805025304-clearing-up-the-confusion-mcp-claude-code.md)
- [Remote MCP servers](../../kb-corpus/docs/en/mcp/remote-mcp-servers.md)
<!-- kb-bridges:end -->
