# Claude Code Mods — domain knowledge

Mods = TypeScript/JS event handlers that run INSIDE Claude Code (v2.1.287+,
on by default). Unlike settings hooks, mods can rewrite events (prompts, tool
args, tool results), answer events short-circuit, draw UI (terminal + Desktop
Code tab only), and register `/commands`. Docs: code.claude.com/docs/en/plugins/mods/.
Build with: `claude plugin validate` (static analysis, no session) and
`claude plugin test` (runs tests with no session/network).

## Plugin anatomy

```
<mod>/.claude-plugin/plugin.json     # manifest (name, version, author)
<mod>/hooks/hooks.json               # {"modules": ["./register.js"]}  ← what makes it a mod
<mod>/hooks/register.js              # export function register(on) { on(event, matcher?, handler) }
<mod>/tests/*.test.ts                # import { expect, test } from 'claude-code/testing'
```

Handler: `async ($, e, next) => …`. Observe = `next(e)`; rewrite = `next({...e, field})`;
answer/block = return without next: `{ deny: 'text' }` (Claude reads it as tool
result) or `{ result: 'text' }`; post-tool = `const r = await next(e)` then
transform `r`. Matchers: `{ tool: 'Name' | ['A','B'] | /regex/ }` — MCP tools
match by full name `mcp__<server>__<tool>`; MCP args arrive SPREAD onto `e`
(loose, `[argument: string]: unknown`), not under `e.input`.

## Static-analysis rules (validate enforces)

- `on()` event names must be string literals; no destructuring/aliasing `$`;
  every API call spelled in full (`$.fs.write(...)`).
- ES module only, imports only from within the plugin (+ bare `claude-code`).

## Dev loop (the one that works)

1. Scaffold under a plain folder (Josh: `~/mods/<name>/`).
2. First load with `claude -p "hi" --plugin-dir ~/mods/<name>` — this generates
   `.claude-plugin/types/claude-code/index.d.ts` (~15K lines: every event, API
   method, result shape). **Trust the generated .d.ts over web docs.**
3. Iterate: edit → `claude plugin validate .` → `claude plugin test`.
   `--plugin-dir` sessions hot-reload on file save (turn end).

## Confirmed gotchas (2026-10-05, workato-guardrails build)

- **Installed plugins cache by version**: edits to the source folder do NOT
  reach an installed copy. To iterate installed: bump `version` in plugin.json,
  `claude plugin install <mod>@<marketplace>` again. For active dev, use
  `--plugin-dir` instead of installing.
- **JSON-escaped newlines break ID regexes**: MCP results JSON-stringify to
  carry literal `\n` sequences, so `recipe_id` can be preceded by the `n` of
  `\n` — a `[^_\w]` prefix class or `(?<![_\w])` lookbehind both reject it.
  Normalize first: `text.replace(/\\n/g, ' ')` before extracting IDs.
- `$.fs.write(path, text)` OVERWRITES — no append. For audit logs use
  `$.process.run(['sh','-c','cat >> file'], { input: line })`.
- `$.ui.log` lines are transcript-visible to the user but Claude does NOT read
  them — right channel for visibility-only output. `$.ui.log` needs $.ui, not
  process.
- Matcher `{ tool: /^mcp__server__/ }` cleanly scopes a hook to one MCP server.

## Josh's plugin: workato-guardrails (~/mods/workato-guardrails, marketplace ~/mods = "josh-mods")

Installed user-scope 2026-10-05. **v0.8.0 2026-10-07** (37/37 tests pass) — adds
hook 13, the prod-write confirm gate for every non-AIRO surface. Hooks in one register.js:
1. Secret redaction (outermost tool.call hook — registered first, so it sees
   every other hook's result last): redacts sk-ant/sk-/ghp_/xox/Bearer tokens
   and `api_key: value`-shaped assignments; prose with the word "token" untouched.
2. Prod-write audit: every `mcp__workato-airo-mcp-prod__*` write → append to
   `~/.claude/workato-audit/prod-writes.log` + `$.ui.log` band. Never blocks.
3. Jira story-points: denies `mcp__atlassian__createJiraIssue` without
   customfield_10057 unless project in {BTSUP, HROPS, PSM, MCP}.
4. URL linker: annotates AIRO/tracker results containing recipe_id /
   data_table_id / folder_id with canonical app.workato.com URLs (skips if
   already linked).
5. jira-story-standards prompt injection: `prompt.submit` context injection on
   Jira-creation prompts — reads the live SKILL.md at session.start (bounded to
   4K chars), embedded fallback digest if unreadable.
6. Status band (`ui.render` {component: AbovePrompt}) + `/guardrails` command
   showing hook list + prod-write counter (persisted via `$.store`).
7. Datapill trap warning: annotates `recipe_builder_pull` (dev AND prod AIRO)
   results with the sample-value/hardcoded trap at the moment of exposure.
8. Writeback verification nudge: annotates Jira/Confluence write results
   (create/edit/comment/transition/issue-link/page create+update/comments)
   with "re-read via getJiraIssue/getConfluencePage before reporting done".
   NOTE: createJiraIssue results carry BOTH the story-points passthrough and
   this nudge — tests assert containment, not equality.
9. Push risk scorer, 10-12. build ledger + recipe snapshot history (see
   workato-platform domain file for the ledger/risk details).
13. **Prod-write confirm gate (2026-10-07)** — every surface, not just AIRO MCP.
   Detects prod-targeting Bash commands and holds WRITES for a confirm dialog,
   fail-closed on dismissal: `workato-prod`, `wt-prod`, `WORKATO_PROFILE=
   josh-prod`, `--profile josh-prod`, raw http carrying the prod credential
   (matched by a stable identifier from the prod JWT, not the secret), and Orca
   interactions on prod urls. Reads pass through untouched. Classifiers
   `prodSurface` / `wtIsWrite` / `workatoIsWrite` parse the group+op token;
   longest-wrapper-first regex matters (`\bwt\b` matches inside `wt-prod`).

Hook-order principle: register policy-outermost hooks first (redaction), then
audit, then gates, then cosmetic annotators — first-registered sees the event
first and its result last.

**Local-marketplace install nuance (confirmed 2026-10-06):** plugins from a
LOCAL directory marketplace load IN PLACE from the source folder — edits take
effect at next session start / `/reload-plugins` without reinstall. The
cache-by-version trap only applies to git/remote marketplaces. `claude plugin
update <mod>@<marketplace>` re-records the version number after a bump.

## Rollback / removal

- Disable for all sessions: `claude plugin uninstall workato-guardrails@josh-mods`
- Disable one session: `/plugin` → Installed → disable, or start `claude --safe-mode`
- Full removal: uninstall + `claude plugin marketplace remove josh-mods` +
  delete `~/mods/` (plugin, marketplace, tests all live there; installed cache
  at ~/.claude/plugins/cache/josh-mods/ disappears with uninstall)
- Nuke switch: `"disableAllHooks": true` in ~/.claude/settings.json stops all
  mods + settings hooks (plugin's skills/commands still load)

## Gateway model routing (settings.json env block)

- Model slots live in `~/.claude/settings.json` → `env`: ANTHROPIC_MODEL,
  ANTHROPIC_DEFAULT_SONNET/HAIKU/OPUS/FABLE_MODEL, CLAUDE_CODE_SUBAGENT_MODEL,
  CLAUDE_CODE_BG_CLASSIFIER_MODEL, ANTHROPIC_CUSTOM_MODEL_OPTION. Gateway:
  `https://ai.preview.workato.com/anthropic`; valid model IDs in the same
  file's `availableModels` array.
- Slot semantics (Josh, 2026-10-05): glm-5.3-flash IS the main model — keep it
  in ANTHROPIC_MODEL / SONNET / HAIKU / SUBAGENT / BG_CLASSIFIER; kimi-k3 stays
  on OPUS/FABLE. ANTHROPIC_CUSTOM_MODEL_OPTION is the slot for trying an
  ALTERNATE model without displacing the main one. Current alternate (since
  2026-10-05): `fireworks/deepseek-v4-pro`.
- Lesson: "swap out GLM-5.3" meant the non-flash GLM-5.3 in the custom-option
  slot ONLY — do not interpret it as replacing the main model. A wholesale
  swap was made and reverted same day (backup:
  `~/.claude/settings.json.bak-pre-deepseek`).
- Env changes take effect on next session start, not hot-reload.

- `availableModels` in settings.json is a STATIC list, NOT proof the gateway
  serves a model. Live probe (2026-10-05, POST /v1/messages on
  ai.preview.workato.com/anthropic): WORKING = glm-5.3-flash (main),
  fireworks/kimi-k3, fireworks/glm-5.3, baseten/glm-5.2-fast, nebius/glm-5.2,
  fireworks/minimax-m3, fireworks/qwen3.8-max. NOT DEPLOYED (rejects with
  "Model not found, inaccessible, and/or not deployed"):
  fireworks/deepseek-v4-pro, fireworks/deepseek-v4-flash, fireworks/glm-5.2.
  WORKING deepseek: `fireworks/deepseek-v4.1-flash` (and alias `rr/deepseek-
  v4.1-flash`) — both resolve to accounts/fireworks/models/deepseek-v4p1-flash.
  Custom-option slot set to deepseek-v4.1-flash 2026-10-05. To re-probe: curl
  the gateway /v1/messages with a 8-token ping.

- Catalog endpoint: `GET https://ai.preview.workato.com/v1/models` (ROOT path,
  OpenAI-style; `/anthropic/v1/models` 400s with "model is empty"). Returns
  282 entries, `owned_by: static-wkt`, spanning fireworks/, baseten/, nebius/,
  azure_internal_0*/ + bedrock_internal_0*/ + mantle_internal_0*/ (Claude, GPT),
  vertex_global/ (Gemini). It is a STATIC list — it includes models that are not
  deployed (e.g. fireworks/deepseek-v4-pro), so catalog presence is NOT proof of
  serving. Always ping /anthropic/v1/messages before trusting an ID.
- Full sweep of Josh's availableModels (2026-10-05): WORKS = baseten/kimi-k3,
  nebius/kimi-k3, fireworks/kimi-k3, baseten/deepseek-v4-pro,
  baseten/deepseek-v4-flash, baseten/glm-5.2, baseten/glm-5.2-fast,
  nebius/deepseek-v4-pro, nebius/glm-5.2, nebius/minimax-m3,
  fireworks/glm-5.3-flash, fireworks/glm-5.3, fireworks/minimax-m3,
  fireworks/qwen3.8-max, fireworks/deepseek-v4.1-flash. NOT DEPLOYED =
  nebius/deepseek-v4-flash, fireworks/deepseek-v4-pro,
  fireworks/deepseek-v4-flash, fireworks/glm-5.2. NOT IN CATALOG AT ALL =
  baseten/inkling, baseten/inkling-small (stale entries in settings).
- Provider matters: deepseek-v4-pro serves via baseten/ and nebius/ but NOT
  via fireworks/. If Josh wants pro-tier DeepSeek, use baseten/deepseek-v4-pro.
- `ANTHROPIC_CUSTOM_MODEL_OPTION` alone does NOT put a model in the /model
  picker — the ID must also be in the `availableModels` array (that array is
  what the picker renders).

## announce-stop-guard.sh — both-directions hardening (2026-10-06)

Two live misses + one false positive, all fixed and regression-tested:
- MISS: "Now the compile-rejection path" / "Now for the real verification"
  slipped the now-the rule. Fix: optional `for` after now/next, noun list
  += path/phase/part/pass/sweep/round/batch/stage/wave/deploy/release/
  rebuild/restart/remap/install/migration/patch/backfill/reconcile/verify/
  validate, plus re- prefixed forms (re-probe, re-check, re-test, re-run…).
- FALSE POSITIVE: the "ends with colon" rule used per-line grep — any bullet
  lead-in colon mid-message fired it. Fix: check only the last non-empty
  line (`awk 'NF{l=$0} END{print l}'`), matching the documented intent
  (whole-text trailer).
- Method note: test hook regexes against the REAL escaped sentences plus
  innocent status sentences ("Now green across the board.") before
  declaring done — both directions.

## /reload-plugins gotcha (confirmed 2026-10-06)

`/reload-plugins` re-reads mod CODE but does NOT re-run `session.start` —
so `$.command.register` calls made there do NOT register new commands in the
current session. Symptom: band/renders work (ui.render hooks reload) but
new slash commands say "Unknown command". Fix: start a FRESH session. Old
commands keep working (registered at an earlier session.start). Same reason
a version-bump + update is not enough for new commands: new-session required.

## Shareable kit (2026-10-07)

The whole harness (2 mods, 4 agents, knowledge scaffold, scripts, schedule
templates, installer) is packaged as
`~/Documents/agentic-workato-kit/` (git repo, 38 files) — templated with
{{HOME}}/{{WORKSPACE_*}}/{{FIELD_*}} tokens + config.example.sh; install.sh
renders + installs (python render — config values contain sed-breaking |/[]).
Sandbox-tested with fake HOME + KIT_SKIP_INSTALL=1. Share: push the repo
(GitHub/private) → co-worker fills config.sh → ./install.sh → restart →
connect MCP servers themselves.

Gotchas baked in: sed delimiter trap (values with |); version-check heredoc
needs argv not interpolation; /reload-plugins does NOT re-run session.start
(new slash commands need a new session).
Kit v2 (2026-10-07): also ships airo-mcp-playbook + workato-development-playbook
skills (templated) and the wt Developer API wrapper (bin/wt — auth via env
var/keychain, no secrets in kit). 52 files. Installer renders skills + puts
wt in ~/.local/bin with a PATH check.

## Installer/sandbox testing gotchas (2026-10-07, learned by breaking live files)

- CONFIG-OVERRIDE TRAP: config.sh sets `export KIT_HOME="${HOME}"` which
  clobbers an env-provided KIT_HOME when install.sh sources it — a "sandbox"
  KIT_HOME env var silently loses and the install renders into the LIVE
  harness. Fix: config files use `: "${KIT_HOME:=${HOME}}"` (env wins).
- RULE (Josh, after the incident): before any install-like test, PRINT the
  destination paths and verify them against the live harness BEFORE writing;
  a sandbox is verified-isolated, never assumed-isolated.
- Second trap in the same event: a "restore" of a config file from a tmp
  backup made AFTER a test had already overwritten it restores the TEST
  state, not the real one. Recover true originals from git, not tmp copies.
- harness-backup.sh now sources the kit config.sh when run bare (cron path)
  so BACKUP_REPO_URL is always present; verified bare run pushes.
- onboard.sh: interactive questionnaire (validating answers, EOF-safe,
  3-strike cap, env-respecting KIT_HOME); install.sh runs it when config.sh
  is missing and stdin is a TTY; example config no longer ships Josh's real
  workspace IDs.

## Kit CX round (2026-10-07 night)

- verify.sh: 32-check doctor (prereqs, config, bins, LIVE dev+prod identity
  vs config, mods, knowledge+git, dreamer mode, bus outboxes, agents,
  skills, MCP health, crons, backup) — 32/32 pass on Josh's machine. Two
  gotchas baked in as fixes: `claude mcp list` is CWD-SENSITIVE
  (project-scoped servers only visible from the project dir — verify.sh cd's
  to PROJECT_PATH) and nested health checks are flaky (one retry).
- onboard.sh now captures API tokens at questionnaire time → straight to
  keychain (read -s, never written to a file).
- README: Quick start (clone → onboard → install → verify) + install journey
  rewritten; install.sh NEXT points at verify.sh.

## Kit support incident #1 (2026-10-07): the dirstack ghost

First teammate install report: `zsh: not enough directory stack entries` after
clone + onboard. Sandbox repro of the exact commands (clean zsh, local clone):
clean. Root cause is the REPORTER's zsh config (alias/function loop or broken
precmd hook; error is zsh's own string, fires after bare git clone = before any
kit code). Lesson pattern: teammate-reported install errors get a clean-env
repro BEFORE touching the kit; the structural proof (bash subprocesses can't
touch the parent zsh dirstack) carried the verdict. Fix shipped as a README
Troubleshooting entry + triage commands for the teammate (whence -v ls cd
pushd, precmd_functions, unsetopt AUTO_PUSHD).

## Mod sandbox constraints (learned 2026-10-07, bypass build)

- The hooks validator is STATIC: `$` may only appear at `$.noun.event(...)`
  call sites — passing `$` to a helper function fails module LOAD (not the
  test, the load; the whole plugin dies with HooksError). Inline or
  restructure; no helpers taking $.
- The sandbox has no `process` global: `process.env`/`process.cwd()` throw
  "process is not defined" at load. Home paths must be literal (or
  {{HOME}}-templated in the kit); cwd comes from the event or is skipped.
- The plugin TEST kit exposes `$.tool.call` only — no $.process/$.fs, so
  tests cannot fixture filesystem state (e.g. a bypass flag file). Design
  hook logic so untestable paths fail closed and get live-verified instead.

## grill-gate skill (2026-10-07, stolen pattern)

- Stole the "grill-me" self-answer pattern (Matt Pocock's viral skill, surfaced
  in the 2026 best-Claude-skills roundups) as a user-scope skill:
  `~/.claude/skills/grill-gate/SKILL.md`, wired as a standing rule in the
  global CLAUDE.md ("Planning-phase grill gate").
- Behavior: during planning/brainstorming, a one-sentence gate — requirements
  clear (goal/scope/done-criteria, no open directional choice) = bypass and
  proceed; anything directionally unclear = grill. Grill = self-answer every
  repo/docs/ticket/tool-answerable question first (cite sources), then ask
  Josh only true judgment calls in ONE batched round, each with a recommended
  answer. No drip-feeding, no silent directional defaults.
- Why this shape: the two roundups' baseline failure mode is "agent charges
  ahead on wrong assumptions OR asks open-ended questions that force Josh to
  write paragraphs." The recommended-answer contract makes the reply one word.
- Tested per writing-skills TDD: 2 baseline vs 2 with-skill arms on the same
  vague scenario ("make the nightly report faster"). Baselines mined first
  but asked open questions with no recommendations; both skill arms converged
  on mining pass + gate statement + 3-4 batched questions each carrying a
  recommendation. GREEN, low variance, no refactor loop needed.
- Not folded into the superpowers:brainstorming plugin file — that lives in
  the versioned plugin cache (wiped on plugin update). User-scope skill +
  CLAUDE.md standing rule survives updates; user instructions take precedence
  over plugin skills per using-superpowers.

## Insights report analysis (2026-10-08, /insights over 107 sessions/3 months)

Friction data: buggy generated code 78x (dominant), wrong approach 39x,
premature claims recurring — yet 90%+ outcomes. Josh's challenger behavior
is the conversion mechanism; the goal is moving that verification cost from
Josh into the harness.

Already institutionalized (report's suggestions, don't rebuild): Verification
Rules in CLAUDE.md, Orca-not-Playwright rule, headless fleet (launchd, not
crons), 40+ skills incl. manifest-hygiene/triage/verify-recipe, proposal
approval loop + morning digest (built the night before the report ran).

Genuinely new — filed as triage findings (verdict via /triage):
1. `preflight-prod-impact-checklist` (3pts): hook 13 gates WHETHER a prod
   write happens; nothing enumerates WHAT (tenant confirm, asset list,
   stop/start windows) before it. Roster-deactivation + duplicate-tree
   incidents were both "wrote the right gate, wrong target" failures.
2. `deterministic-lint-posttooluse-hook` (2pts): py_compile/ruby -c after
   every Write/Edit — the 78-bug class (regex, type-mismatch, boolean-vs-
   string, py3.9 datetime.UTC) is catchable pre-runtime for ~free.
3. `unverified-items-line-on-done-claims` (1pt): every completion claim
   lists what was NOT verified. Closest thing to a free win in the report.
4. `prior-art-first-design-rule` (1pt): required prior-art sweep (knowledge
   tree, skills, ledgers, recipes) in design phase before new mechanisms.

Open opportunities (no action filed): parallel debug swarm fed by the triage
queue when backlog grows (squad-build pattern); replay gym (already
ACCEPTED proposal) covers the report's "test-gated recipe rewrites" +
golden-fixture ideas; loadout job already fixes the "abrupt session starts"
half-landed-work friction.

Josh habit notes (keep): challenger stance is the highest-leverage habit in
the dataset; multi-part directives are fine (outcomes 90%+); mid-flight
course-corrections (Playwright→Orca) should keep happening; abandoned
low-stakes threads are healthy priority gating, not a defect.

## plist-mangle investigation CLOSED + cockpit render fix (2026-10-08 /triage)

- **plist-shell-write-mangle: suspect cleared, no active mangler.**
  brain-guard register.js is annotate-only (`nudge()` appends lint text to
  tool results, never writes files); lint-changed.py is a read-only
  PostToolUse syntax check. Canary plists via heredoc AND the Write tool
  stayed byte-clean (10s window); all 26 ~/Library/LaunchAgents plists have
  intact `</key>` tags. Original gym-build incident not reproducible — if
  it recurs, canary immediately and suspect whatever touched the file's
  directory, not these hooks.
- **/cockpit full dashboard verified by real render** (headless Chrome
  screenshot): the 03:22 styling pass produced a clean, fully-styled page —
  the twice-flagged "looks terrible / see no html" complaint predates it
  and was never verified back to Josh; the full-page dashboard is GOOD as
  of 2026-10-08. Bare /cockpit pane is text-by-design with a tested
  fallback (headless/VS Code).
- Real render defect found+fixed in brain-dashboard.py: Fleet table's
  last-log column printed raw `}` / `]` rows (it took lines[-1] of
  pretty-printed JSON logs). Now skips bare brace/bracket lines; verified
  0 lone-bracket cells after regen.
- **triage recorder trap**: workato-health re-appends a fresh queue row per
  sweep (only evidence/ts change) and triage-decide.py finds by slug
  SUBSTRING with no status filter — duplicate rows make the open finding
  ambiguous and terminal rows keep colliding on fragments. Workaround used
  2026-10-08: dedupe keeping newest evidence, rename terminal rows out of
  the fragment space, hand-append matching outcome-ledger lines. Fix worth
  building: dedupe-on-append in the source agent + recorder match on
  (slug, status==open).

## Gym plist mangle incident (2026-10-08, RESOLVED)

The gym.plist was written corrupted TWICE (Write tool + heredoc): line 13
`<key>StandardErrorPath</key>` had its close become `</string>` — plutil/
xmllint saw corrupt bytes while the Read tool showed correct content.
Root cause hunt: 3-way canary (Write tool / heredoc / python3) all clean
next day; brain-guard + workato-guardrails contain zero file-rewrite code
(grep: no writeFile/sed -i outside audit appends). Verdict: one-time
transient (partial write / checkpoint race during parallel churn), NOT a
standing hook bug. Durable fix: lint-changed.py PostToolUse hook extended
to .plist (plutil -lint) + .xml (xmllint --noout) — the exact incident
pattern now feeds back to the model on every write; proven on a repro
canary. Lesson: when a written file is visible-corrupt but tools disagree
about its content, suspect a partial write racing a reader, and make the
linter cover the format instead of chasing a phantom rewriter.

## 2026-10-09: build-ledger writer made atomic

register.js `ledgerAppend` + `verifyClaim` (guardrails 1.0.0 cache) now
pipe their line through `/usr/bin/python3 knowledge/scripts/atomic_io.py`
(flock + tmp + os.replace) instead of `cat >>` — closes the truncated-
line corruption class at the multi-session hot path. NOTE: this edits
the plugin CACHE copy (register.js.bak-20261009 alongside); a plugin
update to a new version will drop it until the source repo carries the
same change — the source repo was not found locally. Pre-existing,
separate defect: gym.py calls main() (line 157) before defining
check_a6 (line 162) → nightly gym run NameErrors; untouched.

## Counter scoping bug + fix (2026-10-09)

- The status band's "prod writes this session: N" was a LIFETIME counter:
  session.start seeded it from `$.store.get('prodWrites')` (a persistent KV)
  and both increment sites saved it back, so it accumulated across sessions
  (showed 636; log has 991 audited lines since 10-07). The "this session"
  label was simply false.
- Fix: register() runs per session, so module state is naturally
  session-scoped — `prodWrites` is now never seeded from the store; a new
  `lifetimeWrites` var carries the persisted store key (same key, continuity
  kept). Both render sites show "this session: X · all time: Y".
- Lesson: any `$.store`-backed counter with a session-shaped label is lying;
  decide the scope first, then pick in-memory (per-session) vs store
  (lifetime) per counter, never one var doing both.
- Tests 42/42 green (`claude plugin test` in the mod dir), deployed via
  bin/mods-deploy.sh; live pickup needs /reload-plugins or restart.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [Plugins (Beta)](../../kb-corpus/claude/docs_en_api_beta_organization_plugins.md.md)
<!-- kb-bridges:end -->

## Kit installer hardened + getting-started walkthrough (2026-10-10)

- install.sh no longer fails hard or fails silently: every swallow
  (`|| true` mod installs, WARN-only kb clone, unguarded render) is now
  captured + classified + registered as a DEGRADED item with the verbatim
  fix command; runs tee to install-logs/install-<ts>.log (gitignored);
  with_retry/with_retry_stream give network steps 3 attempts; ERR/EXIT
  traps print failed step + completed-vs-not + log path + resume line;
  render() failure is fatal (corrupt installs).
- NEW getting-started.sh: post-install adoption walkthrough, 8 resumable
  steps (verify -> mcp OAuth -> settings.json -> keychain tokens ->
  plugins/reload -> schedules -> trust ladder -> first task). Each step
  live-probes, never trusts last run's memory; state in
  ~/.claude/getting-started-state.json (chmod 600, statuses only);
  --status / --reset flags. onboard.sh = pre-install config, verify.sh =
  doctor, getting-started.sh = the guided middle layer.
- Guinea-pig feedback loop: a teammate's failed run is diagnosable from
  two artifacts they can send back — the install log + `--status`
  output. Status: homegrown/non-production; COMMITTED + PUSHED 2026-10-10
  (9229e55, github.com/Workato-All/workato-agentic-kit); never live-run
  interactively (Y/n + token-paste paths only exercised via piped EOF) —
  first real guinea-pig run still pending.
- Bug class worth remembering: `rc=$?` captured after `if/fi` reads 0,
  not the branch's status — capture inside the else branch. And a
  trailing AND-list in an EXIT-trap cleanup fn can flip exit 0 -> 1
  under set -e; use if-forms + explicit return 0.

## Harness-fix round 2026-10-11 (fleet meta-work)

- **queue-append.py dedupe vs closures**: dedupe-on-slug (added 2026-10-11 to stop
  49 overnight re-files) also blocked the fixed/resolved closure rows the
  harness-fix close-out depends on — queues are append-only ledgers, last row
  wins, so a status-change row must never be deduped. Fix: dedupe only
  status=open re-files; closure rows pass through. Lesson: when tightening a
  recorder's dedupe, enumerate EVERY row-shape the append path is load-bearing
  for before gating it.
- **Plist without a job def = silent nightly exit 1**: com.josh.fleet.evidence
  was installed (daily 00:53) before jobs/evidence.env+prompt existed; runner
  died at `source "$JOB.env"` then `JOB_CWD: unbound variable` (set -u) AFTER
  echoing "start", so logs look alive while claude never launches. Def authored
  (config/fleet source of truth + kit copy) and the job verified live: first
  heartbeat 09:18:02Z + claim-verification-2026-10-11.md. Lesson: a fleet plist
  install checklist item — the job def must exist and `bash -c 'source
  jobs/<name>.env; cd $JOB_CWD'` must succeed before installing the plist.
- **Oct-10 stale-heartbeat cluster (brief/canary/cost-governor/decision-inbox/
  harness-fix/loadout/ops-autopsy)**: machine-down gap, not a defect — all
  validated on the 2026-10-11 ~09:10Z tick; 127 last-exit status in launchctl is
  stale residue from the gap.

## session-budget v0.1.0 (2026-10-11) — the cold-start guardrail

Born from the cost analysis (reviews/harness-cost-benefit-2026-10-11.md): 26 of 333 sessions = 80% of the week's $3,371 gateway spend, all long RESUMED sessions re-hydrating giant contexts. The mod makes starting cold cheaper than resuming.

- **Band** (AbovePrompt): live `session $X / $60 · ctx N%`, dim → yellow at warn → red at hard.
- **Warn toast**: once per session when either warn line is crossed (defaults $25 / 60% context).
- **Hard stop**: `classic.Stop` blocks turn end (max 3 blocks/session, native `stop_hook_active` respected) with orders: invoke the `handoff` skill, then append one closeout row to `~/.claude/knowledge/handoffs/session-closeouts.jsonl` — the row's session_id is the gate that reopens Stop. Fail-closed: unreadable ledger = block.
- **Exemptions**: fleet jobs (CLAUDE_JOB=yes), non-interactive surfaces, `/budget` command to inspect state.
- **Env knobs** (literal names, engine requirement): SESSION_BUDGET_WARN_USD (25), HARD_USD (60), WARN_CTX_PCT (60), HARD_CTX_PCT (85), CLOSEOUT_LEDGER, SESSION_BUDGET_FORCE=warn|hard|off (simulation + kill switch).
- Engine constraints learned: `$.env.get` takes LITERAL names only (no computed vars); `$`-taking helpers must be top-level `function` declarations; `$.state` needs the typed atom contract (types/index.d.ts); the TEST ENGINE implements no `$.fs` noun — closeout-pass branch untestable there, pinned as fail-closed test instead. Test kit signature is `test(name, async ($, on) => …)`, and raising a classic event needs a bottom `on('classic.Stop', () => ({}))`.
- Installed in ~/mods/session-budget + marketplace josh-mods; dev copy in .claude/dev-mods/<session>/session-budget for hot-reload. 6/6 tests, tsc clean (borrowed ManaMargin's tsc; no system tsc).

### brain-guard node:fs load failure — FIXED 2026-10-11
Symptom: "hooks module did not load: cannot import node:fs". Hooks modules may import ONLY relative files + 'claude-code'. Fix: voices.json + INDEX.md reads moved to `$.fs.read` (lazy, cache-once, fail-silent), writer id moved from `process.env` to `$.env.get`. Engine sandbox lessons: **`$` does not exist at register time** (no warm-up calls in register body — lazy-load in hooks); **no `process` noun in the test engine** (use `$.env.get`, the mockable noun); **no optional chaining on `$`** (validator refuses `$?.fs` — try/catch instead, it's also fail-correct: missing noun = rule stays silent). Verified: validate ✔, plugin tests 7/7, node --test 7/7, cache 0.4.1 synced.

### manifest-guard false-positive fix (2026-10-12, night)
First-night bug: the guard regexed EVERY transcript text block, so tool RESULTS / relayed reports merely NAMING `data_table_create` counted as mutations — it blocked a fully read-only analysis session (the cost/analysis one) on the BSYS-29503 session's work. Fix: detection runs on `tool_use` records only — MCP tool NAME matched against the full AIRO-mutation list, Bash `command` against a CLI-mutation regex (`wt/workato … recipes push/import, dt create/update/delete/truncate/add-row/upsert, packages import, api PUT/POST/DELETE`); text blobs count only for the LENIENT side (manifest_seen remediation credit). 5-case proof: real MCP mutation blocks, Bash write blocks, text-mention passes, remediated passes, live session passes. Underlying gap NOT fixed: build-ledger.jsonl rows carry hand-named `session` labels, no per-Claude-session id — cross-session attribution stays impossible until the ledger writer records session_id (same class as the 2026-10-10 attribution fix; fleet-build Stop-guard applicability also unverified — `claude -p` Stop blocks make the run continue, which may be desired, Josh to rule).

### session-budget cost-source fix (2026-10-12, night — the $85-vs-$3.39 bug)
First live session caught it: the band showed $85.03 where Josh's status line showed $3.39. Two wrongs in `$.session.usage().cost.usd`: (1) it prices every call against ANTHROPIC's list — on the Fireworks gateway that's a number nobody is ever billed (the fireconnect statusline's own header documents this); (2) for a resumed session it sums the whole lineage since first launch. Fix: the mod spawns the statusline's own exported helper — `node -e "import('.../fireconnect/.../statusline.mjs').then(m => m.claudeStatusLineUsage(argv))"` via `$.process.run` (array-form args, no shell quoting; dynamic import is legal in a SPAWNED child, only banned in module source) — Fireworks list rates per actual model, cache-adjusted, parent+subagents, keyed on transcript_path (captured at classic.SessionStart/Stop; band caches 30s). Thresholds realigned to the statusline's: warn $25 / hard $50. Live probe: `{"cost":3.53,"cachePct":"89%"}` on this session. Fail-soft: helper failure = cost n/a, ctx-% gating still works. LAW: on a third-party gateway, NEVER trust the engine's cost ledger for budget logic — recompute from the transcript with the gateway's rates, from one shared helper, never a mod-local pricing table.

### redteam-guard false-positive fix (2026-10-12, night — round 2)
The guard already scanned tool_use-only, but a Bash command can CONTAIN prose: a knowledge-deposit heredoc documenting the mutation patterns matched `\bworkato\b[^\n]*packages? import` mid-line and blocked a write-free session. Fix in BOTH guards (redteam + manifest): segment the command on newlines/&&/;/|, strip sudo/env prefixes, and require the prod/dev binary to be the segment's actual first WORD before checking mutation verbs — prose mentions can't match. Proof: heredoc-documents-patterns passes both guards; `wt-prod recipes push` blocks redteam; `wt manifests import` blocks redteam (division of labor: manifest-guard = dev hygiene, redteam-guard = prod-bound); both pass this session's live transcript.

### session-budget $n/a fix + statusline alert-source fix (2026-10-12, night — round 3)
Second live-session failure: band showed `session $n/a` because the mod loaded MID-session — classic.SessionStart had fired long before, lastTranscript was empty until a Stop fired, so fireworksCost returned null. Fix: the spawned node helper now DERIVES the transcript itself when the path is empty (newest .jsonl by mtime in ~/.claude/projects/<cwd-slug>/ — the live session's file is appended every turn); live probe: derived this session's transcript, cost $3.96 (statusline showed $3.9070). LAW: any session-scoped mod must not depend on SessionStart having fired before it loaded — mid-load is the normal case for hot-reload. Same night, Josh's statusline had the inverse bug: its `cost ALERT: $98 >= $50` segment keyed on cost.total_cost_usd (Anthropic-list + lineage-summed) while the rendered figure was Fireworks-accurate — fireCostAlerts now takes the computed claudeStatusLineUsage cost and NEVER falls back to total_cost_usd (no accurate figure = no alert). Live probe with poisoned payload (total_cost_usd: 98): renders $4.0042, no false ALERT.

### /reload-session slash command (2026-10-14)
Personal slash command at `~/.claude/commands/reload-session.md` (global — works in every project; no hooks, no settings.json changes). What it does: mid-session state re-absorb WITHOUT losing conversation history — one parallel batch re-reads josh-now.md (other live session), newest files in knowledge/handoffs/, MEMORY.md index, INDEX.md, `claude mcp list`, claims-sweep-latest.json; then a verdict-first DELTA report ("what changed since this session started, what to do differently"), including an honest "not refreshable" list (CLAUDE.md content, MCP tool schemas, skill list, settings hooks are baked at startup — restart or `claude --resume` to pick those up). Born: Josh lost track of a session mid-flight and wanted one command to refresh.

Gotchas learned:
- Slash commands load at session start — the session that CREATES the command can't use it until next session. The verification probe: `claude -p "/reload-session"` (headless fresh session) — proves the command file loads, parses, and executes end-to-end for ~one small session's cost. Reusable as the live-verification loop for any command file (the output follows the command's structure exactly — verdict-first sections — which is what distinguishes a loaded command from the raw string being treated as prose).
- Lightweight alternative to a mod: anything that's just "inject a well-structured prompt" needs no plugin/hooks machinery — a commands/*.md file is the whole artifact.

## Team-share state (2026-10-15)

- **Three public-ish repos:** workato-agentic-kit (mechanics), workato-dev-kb
  (KB library: pipeline + public docs corpus, NOT the brain), knowledge-corpus
  (the brain's authored knowledge layer, weekly swept export via
  knowledge-export.sh — deny-listed dirs leave EXPORT-STUB.md skeletons).
- **kit install order for a teammate:** kit (onboard/install/verify) → dev-kb
  installer → clone knowledge-corpus INTO ~/.claude/knowledge (seed) → first
  session. install.sh preserves an existing INDEX.md.
- **config.sh leak fixed:** was git-tracked with real workspace IDs in the
  org repo; untracked + gitignored 2026-10-15 (90aec49). Tokens were always
  keychain-only via onboard.sh (dev + prod profiles).
- **personal-identity-templates/** ships the writing-voice skill template +
  people-file template; personal content is gitignored everywhere and
  sweep-blocked in every export.
- **docs:** 11-capabilities.md + 10-knowledge-getting-started.md published to
  BTI Confluence (2956034461, 2956034485); docs-sync is NIGHTLY 06:52 now
  (cron d4b9fad7, was weekly Tue). New pages need Josh go; updates autonomous.
- **publish trap:** the main session's Atlassian MCP exposes Jira tools only;
  Confluence read/publish works in HEADLESS sessions (claude -p with
  --allowedTools). Fleet-style dispatch is the publish path.
- **history rewrite (2026-10-15, Josh-approved):** people/, voice content,
  slack-posts.jsonl purged from all josh-knowledge history via git-filter-repo
  (backup: /tmp/josh-knowledge-backup.bundle); knowledge-corpus reset to a
  single clean commit (leaked extract files purged; backup bundle in /tmp).
  Teammates with old clones must re-clone.
