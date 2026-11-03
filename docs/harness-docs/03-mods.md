# Enforcement mods: rules as code

Parent page: The Agentic Workato Harness

Three mods (plugins) and a row of session-level guard hooks watch every tool
call, prompt, and render. They are the layer that turns standing rules from
prose into mechanics. Each hook is a few lines of code; `claude plugin
validate` lists exactly what each touches before anything is installed. 42
automated tests cover the guardrails pair.

## workato-guardrails: 16 hooks

(v1.1.0 as of 2026-10-28; v0.8.0 through 2026-10-24 with 16 hooks, v0.7.0
through 2026-10-23 with 15 hooks. The 2026-10-29 sync merged two live-proven
additions into the kit: the /prod-bypass command, a time-boxed prod-write gate
bypass window honored by every surface gate at once (max 120 minutes, writes
stay audit-logged), and the CLI build-ledger filter that drops all-9s
placeholder recipe ids and marks those rows pending_id instead of recording
the fixture id as a real recipe.)

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
| Build ledger (platform) | every successful platform mutation | One JSON line per mutation: tool, server, session, recipe, folder, ticket. All-9s placeholder ids are build-time artifacts, never real recipes, and are recorded as null with a pending_id marker for a later resolver to backfill (added 2026-10-27). |
| Build ledger (CLI and browser) | CLI and browser mutations | Ledgers the paths that bypass the platform tools; a CLI start triggers a read-back that verifies the start actually took. |
| Slash commands | user | `/guardrails` status, `/builds` ledger summary, `/promotion-ready`, `/promoted`, `/cockpit`, `/snapdiff` (recipe snapshot history), `/prod-bypass` (time-boxed gate bypass window). |
| Snapshot history and cockpit | every push; on demand | After each push, pulls the fresh definition from the matching server and commits it to a local git repo, so "what changed in this recipe" is a diff. |
| Prod-write confirm gate | any write to production through ANY surface: platform tools, CLI, API wrapper, raw HTTP, browser | Holds the write for an explicit confirm dialog and fails closed on dismissal. Reads pass through. This is what makes handing an agent production credentials safe. |
| Remote-identity guard | git push to a non-org remote | Holds the push for explicit confirm, and denies outright when the remote's origin is misconfigured — org repos are the only sanctioned push targets (added 2026-10-13, per the mod's own guard list). |
| Push identity guard | every recipe push (dev and production) | After a successful push, looks the pushed recipe up by name (the join key) and makes one folder-scoped listing of running recipes; when another RUNNING recipe carries the same name it annotates the result naming both recipe IDs and their URLs. Kills the two-copy divergence class: a push that landed on a dead copy while the live one kept running under the same name (one tracked incident). Warn-only (built dev-side 2026-10-20, from a dreamer proposal accepted 2026-10-10). |
| user-model session briefing | first prompt of each session (fail-open) | The Python CLI owns retrieval, scoring, and briefing logging; the hook is a thin shim that hands the first prompt to the user-model context compiler and injects a task-conditioned briefing. Registered once inside the shared prompt-submit handler (added v0.8.0, 2026-10-24; spec dated 2026-10-23 in the knowledge tree). |

## brain-guard: 5 hooks for the knowledge system

| Hook | Fires on | What it does |
|---|---|---|
| MCP telemetry | every MCP call | Logs tool, result size, and error class. This is what makes cost and failure reports possible. |
| Turn usage | every completed turn | Logs input, output, and cache token counts. |
| Skill telemetry | every skill load | Logs which skills sessions actually use. |
| Knowledge telemetry | every read or write of knowledge and memory | Logs which knowledge is load-bearing and which is dead. |
| Write linter | every write under the knowledge or memory trees | Nudges on relative dates without absolute anchors, memory files missing frontmatter, and knowledge writes with no index update. Annotates, never blocks. |

## session-budget: the cold-start guardrail (added 2026-10-11)

The third mod exists because of a measured fact: a minority of long, resumed
sessions carried most of a week's model spend, because every turn re-hydrates
a giant context. session-budget renders a live spend and context band above
the prompt, warns once when a threshold is crossed, and at the hard limit
blocks the turn from ending until the session writes its closeout row: the
budget forces the exit interview, not just the exit. Its cost figure is
computed the one honest way on a third-party gateway, recomputed from the
transcript at the gateway's own rates, never read from the engine's built-in
ledger, which prices everything at list rates nobody pays. That rule cost one
live session to learn (a band showing a number twenty-five times the real
one) and is now law for every cost surface in the harness.

## The guard hooks (session level, added 2026-10-12)

Outside the plugins, a row of settings-level hooks enforces the two newest
standing orders and the session lifecycle:

- **manifest-guard** blocks the end of any session that touched Workato
  assets without a living export manifest on record. It detects mutations
  from tool calls only, never from prose (a report that merely names a
  mutation is not a mutation), and credits a session that filed the manifest
  late rather than blocking it.
- **redteam-guard** is the production twin: it blocks the end of any session
  that performed production-bound writes with no red-team verdict on record.
  A verdict reference on the governing ticket satisfies it; an override
  recorded by name satisfies it; dev-only and read-only sessions pass
  untouched.
- **session-drop-guard and the dead-man sweep** close the hardest capture
  gap: sessions killed outright (crash, force quit, closed lid) never fire
  an exit hook, so their mid-flight state used to die with them. A session
  ending substantially without a closeout is now recorded to a dropped-sessions
  ledger, and because the dead-man sweep runs on an external 60-second timer,
  it catches the hard kills a session-side hook physically cannot. The
  morning digest surfaces the last two days of drops with what to absorb.
- **airo-error-guide** turns the platform tool's failure modes into immediate
  teaching: an unknown-field error re-pulls the field guidance, an
  ungranted tool is told to use the CLI instead of retrying, a shell trap
  writes to a file instead of the command line. A week of forensics found
  it built but never wired, and a bigger class underneath: schema errors on
  the platform builder made at the highest average context footprint of any
  tool in the fleet. The hook is now registered, extended to inject the
  exact reference call the error text asks for, and verified end to end
  with a fresh probe that made the exact bad call and got the guidance in
  its context. The loop stops paying a turn to learn a rule the harness
  already knows.
- **jira-comment-guard** (added 2026-10-14) denies malformed tracker
  comments before they are sent: a role tag some projects reject, an unset
  parent, the shapes that had been failing a third of the time. The denial
  carries the corrective reason, so the failed roundtrip never happens.
- **error-sensor** (added 2026-10-26) is the deterministic capture end of the
  error canon loop: every tool error, Bash stderr or MCP failure, appends one
  normalized-signature event to a JSONL ledger. Repeats across sessions get
  the recorded canon lesson injected back into the session (knowledge page
  for the full loop). Known defect (logged 2026-10-26): it phantom-fires on
  successful Agent launches; the predicate fix with regression fixtures
  landed 2026-10-27 (fixtures: test_error_sensor_fixtures.py).
- **the MCP health check** dropped from a multi-line report at session start
  to a single line, with the detail cached for anyone who asks. Even the
  watchdogs pay rent per token.

All the guards share one detection law, paid for by two false-positive
incidents on their first night: mutation detection reads tool calls, parsed
per command segment, and never plain text. A document describing a dangerous
command must pass; the command itself must not.

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

Hardened 2026-11-02 (after the hook-allow-vs-ask-rule precedence finding): a
bypass window is now BOUND to the session that opened it — a second session
never inherits one — and every gate consumer re-checks the binding and the
window expiry at read time, so a hand-edited state file cannot carry an
arbitrary deadline. Re-opening is capped at 240 bypass minutes per session
per UTC day, and open and close both append audit lines to an append-only
prod-writes log (UTC timestamps). No binding or over-cap window fails
closed at every gate.

Verdict: the hooks are small and boring, which is the point. Governance
that requires an agent to be in a good mood is not governance; these rules
run the same way at 3 in the afternoon and 3 in the morning.
