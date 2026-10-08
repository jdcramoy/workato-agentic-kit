# Enforcement mods: rules as code

Parent page: The Agentic Workato Harness

Two mods (plugins) hook every tool call, prompt, and render. They are the
layer that turns standing rules from prose into mechanics. Each hook is a
few lines of code; `claude plugin validate` lists exactly what each touches
before anything is installed. 42 automated tests cover the pair.

## workato-guardrails: 13 hooks

| Hook | Fires on | What it does |
|---|---|---|
| Secret redaction | every tool result | Strips API keys, tokens, and secret-shaped values before the model reads them. Registered first so it sees every other hook's output. |
| Prod-write audit | any write tool on the production MCP | Appends one line to an audit log and prints a transcript band. Never blocks. |
| Push risk scorer | every recipe push | Looks up the recipe's live health (running state, fail rate, last-run age) and annotates the result. Production pushes scoring medium or above are held for an explicit proceed or cancel. |
| Story-points gate | ticket creation | Denies tickets without a story-points estimate, with the scale inline. Exempt projects are configurable. |
| URL linker | platform and tracker results | Appends canonical clickable URLs for any recipe, table, or folder ID, so every summary carries links. |
| Standards injection | prompts that create Jira work | Adds the team's story standards as hidden context, read live at session start. |
| Datapill warning | recipe pulls | Warns at the moment of exposure that DSL exports can show mapped datapills as literal sample values. |
| Writeback nudge | every Jira or Confluence write | Reminds to re-read the artifact and confirm rendering before calling it done. |
| Build ledger (platform) | every successful platform mutation | One JSON line per mutation: tool, server, session, recipe, folder, ticket. |
| Build ledger (CLI and browser) | CLI and browser mutations | Ledgers the paths that bypass the platform tools; a CLI start triggers a read-back that verifies the start actually took. |
| Slash commands | user | `/guardrails` status, `/builds` ledger summary, `/promotion-ready`, `/promoted`, `/cockpit`, `/snapdiff` (recipe snapshot history). |
| Snapshot history and cockpit | every push; on demand | After each push, pulls the fresh definition from the matching server and commits it to a local git repo, so "what changed in this recipe" is a diff. |
| Prod-write confirm gate | any write to production through ANY surface: platform tools, CLI, API wrapper, raw HTTP, browser | Holds the write for an explicit confirm dialog and fails closed on dismissal. Reads pass through. This is what makes handing an agent production credentials safe. |

## brain-guard: 5 hooks for the knowledge system

| Hook | Fires on | What it does |
|---|---|---|
| MCP telemetry | every MCP call | Logs tool, result size, and error class. This is what makes cost and failure reports possible. |
| Turn usage | every completed turn | Logs input, output, and cache token counts. |
| Skill telemetry | every skill load | Logs which skills sessions actually use. |
| Knowledge telemetry | every read or write of knowledge and memory | Logs which knowledge is load-bearing and which is dead. |
| Write linter | every write under the knowledge or memory trees | Nudges on relative dates without absolute anchors, memory files missing frontmatter, and knowledge writes with no index update. Annotates, never blocks. |

## The production credential split

Development and production are separate identities end to end: separate MCP
servers, separate CLI profiles, separate API tokens. The production token
lives only in the OS keychain, is read per invocation by wrapper scripts
that print a production banner, and never sits in a shell profile or a
file. Every production write through any surface is held for confirmation
by the fail-closed gate.

For deliberate batches of production work, `prod-bypass` provides a
time-boxed, audited stand-down of the gates: on for 30 minutes or 2 hours,
visible in the status band while active, every write during the window
logged as bypassed. Trust the gate, then make the exceptions explicit and
temporary rather than training anyone to click through dialogs.

Verdict: the hooks are small and boring, which is the point. Governance
that requires an agent to be in a good mood is not governance; these rules
run the same way at 3 in the afternoon and 3 in the morning.
