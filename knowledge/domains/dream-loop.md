# Dream loop + harness backup

Cross-project: the nightly self-improvement loop and the backup that makes it
safe. Claim clm-012.

## Harness backup (insurance layer)

- Repo: https://github.com/Workato-All/josh-orca.git — local clone at
  `~/Documents/josh-orca`. Script: `knowledge/scripts/harness-backup.sh`
  (symlinked as `~/.local/bin/harness-backup`). Schedule: durable cron
  23:33 nightly (id 1da9e59e), self-rearming.
- Covers: skills, agents, knowledge tree (working-tree snapshot), sanitized
  settings.json, scheduled_tasks.json, workato profiles, local-bin scripts,
  mods, LaunchAgents. Sanitizer redacts token/key/secret values to
  [REDACTED-BACKUP] (3 redactions verified 2026-10-07).
- NEVER copied: transcripts (`~/.claude/projects/`, 1.4GB, verbatim secrets),
  `.credentials.json`, keychain (tokens must be re-entered on restore),
  audit logs, plugin caches.
- GitHub 100MB limit: rsync uses `--max-size=50M` so regenerable data
  artifacts (wql_aliases.db 132MB) stay out. Never force-push the backup
  repo; rewrite history locally only, then reset to remote.

## Gossip bus (agent network, LIVE 2026-10-07)

- Maildir pattern: `knowledge/dreams/bus/<agent>.jsonl`, one outbox per agent,
  single-writer by construction (no races, no overwrites, parallel-safe).
  Read-side aggregation via `knowledge/scripts/gossip-read.py` (`--since 24h`,
  `--thread slug`, `--agent name`, `--json`): merges, sorts, tallies
  corroborations per thread, applies TTL.
- Protocol: `knowledge/dreams/GOSSIP.md`. Every agent: READ bus at start
  (corroborate existing threads, never duplicate), POST max 3 findings at end
  (with refs), `kind:"handoff"` to route work to another agent.
- Corroboration = confidence: 1 witness = observation, 2 = pattern, 3+ = act.
- Wired: watchdog, gardener, architect, promotion-orchestrator (brief
  sections), dreamer (reader-in-chief step, runs last 23:43 and synthesizes
  the night), docs-watch.py (auto-posts platform deltas, first poster 22:15).
- Live proof 2026-10-07: docs-watch posted the first REAL finding (Workato
  status page change) through the full pipeline outbox→merge. NOTE: my
  "--report-only" dry run used the wrong flag (actual: `--report`) and ran
  the full cycle; harmless, snapshot updated, tonight compares from there.
- **ACTUATION WIRED (2026-10-14, Josh-approved "leverage move"): the bus is
  now an ACTUATOR, not just a ledger.** `gossip-actuate.py` (zero-LLM, fleet
  job `bus-actuate`, hourly :41, plist com.josh.fleet.bus-actuate): fresh
  threads (<48h) crossing threshold file triage cards (defect>=1 evidence-
  bearing corroboration, general>=2) + bus announcement; corrigendum routes
  dissenter-first; ledger = dreams/bus/actuations.jsonl (idempotent). First
  LIVE actuation: prod-82090477-quota-burn-stands (2x, cortex+watchdog) →
  card bus-act-...-20261013 surfacing a 4-day-old unanswered Josh
  pause-decision. Efficacy evaluation same session: 1298 posts parsed —
  ~40 genuine posts/day, 8-10 agents; 138/141 finding-threads had zero
  cross-agent response (broadcast+aggregate is the real consumption path —
  dreamer/cortex synthesis; deliberative mesh language retired from the
  promise); where threads engaged, quality was high (independent-witness
  convergence). **TALLY BUG FIXED (order-dependence): tally_threads
  iterated file order (alphabetical agents), so witnesses sorting before
  the finder were mis-filed as self-verifies + defect-opened threads could
  never corroborate (finder only set on kind=="finding") — two-pass fix,
  lifetime corroborations 10→16 corrected (detect-well-persist-poorly =
  6x strongest thread). The 02:46 crash report (float-vs-str TypeError)
  traced to DIVERGED stale copies (kit/workbench pre-2026-10-11-epistemics
  patch) — synced same session; live canonical passes all modes.**

## Dreamer (self-improvement loop)

- Skill: `harness-dreamer` — the full procedure. Schedule: durable cron 23:43
  nightly (id 9a708c56), self-rearming. Both crons fire when a session is
  idle and recreate themselves (recurring crons expire after 7 days).
- Miner: `knowledge/scripts/dream-mine.py` — stdlib, read-only, bounded.
  Mines last N days of transcripts: sessions, correction candidates
  (regex heuristics with noise guards for injected lines), recurring errors,
  tool frequencies, repeated 4-gram tool sequences. Writes
  `knowledge/dreams/data/<date>-mine.json` (42 sessions / 11k turns / 6
  corrections on first 3-day run).
- Reports: `knowledge/dreams/YYYY-MM-DD.md`. Proposals:
  `knowledge/dreams/proposals/YYYY-MM-DD-<slug>.md` (status: proposed →
  approved → applied / rejected).

## Trust ladder (pre-gated, upgrade = one line)

- Config: `knowledge/dreams/config.json`; control:
  `python3 ~/.claude/knowledge/scripts/dream-config.py set-mode <mode>`.
- `report` → report only, zero writes outside knowledge/dreams/.
- `propose` → + proposal files. Nothing applied.
- `auto-safe` → + auto-apply ONLY `auto_safe_allow` (knowledge-file deltas,
  INDEX lines, memory pointers, claim verifications).
- `never_auto` is constitutional in EVERY mode: skills, hooks, mods, agents,
  settings, crons, mcp, commands are proposal-only forever. Skills/hooks
  always need Josh; the ladder never crosses that line.
- Rollback: every applied change lands in the nightly backup; git revert on
  the backup repo restores.

## Gotchas

- The correction miner's regex catches injected lines ("Stop hook feedback:")
  and praise-context openers ("No, that's perfect,") — noise guards exist in
  NOT_CORRECTION_RE; extend it as new noise shapes appear.
- Tool n-grams are dominated by Bash-blob sequences at small sample sizes;
  they need ~a week of data before "repeat = skill candidate" is meaningful.
- Durable crons only fire while a session is open and idle. If sessions stop
  happening at night, move the schedule to when Josh actually works.

## Morning brief (added 2026-10-07)

- Cron 07:13 daily (id 07c94e79, self-rearming, template
  schedules/morning-brief-daily.txt in the kit): ONE digest — machine
  heartbeat (who skipped), bus threads (2+ witnesses first), dream verdict,
  watchdog P1s, Jira moves, repo commits. Writes
  knowledge/morning-brief/<date>.md. Closes the loop: the network works at
  night, the brief is what Josh actually reads at 7am.
- Full fleet (8 jobs, all self-rearming, project-scoped
  .claude/scheduled_tasks.json): docs-watch 22:31, gardener 22:43, watchdog
  23:13, backup 23:33, dreamer 23:43, corpus Mon 06:07, architect Mon 06:37,
  brief 07:13.
- Heartbeat contract (2026-10-07): every fleet job must check in to
  `garden-reports/heartbeat.jsonl` (`{"ts": ISO-UTC, "job": name}`) or the
  dashboard chip shows `—` forever. backup.script and dreamer.prompt were
  missing the check-in (the write lived only in the dead dream-nightly.sh
  path); both fixed and round-trip verified via brain-dashboard.py.
- Dashboard cadence: brain-dashboard.py regenerates in ~70ms from local
  files (zero tokens), so hourly is the ceiling that matters (bus/mini-dream
  inputs move hourly). `com.josh.brain-dashboard` launchd timer fires :09
  every hour; kickstart-verified 2026-10-07.
- Dashboard v2 (2026-10-07 night, full rebuild): 14 sections — all 13 launchd
  timers w/ parsed schedules + log-tail drilldowns, agents roster, cortex
  queue+questions, bus (rows expand to raw JSON), claims, capabilities,
  canon, regression run, watchdog+docs-deltas, dream+proposal outcomes,
  evals/usage/cost, slack open posts, build ledger, repos. Interactivity:
  click-to-expand rows (106 drillable), global filter box, sticky nav,
  5-min meta refresh; file:// deep links into logs/reports. Verified in
  browser (Playwright over a temp localhost server — file:// is blocked).
  Timer state semantics (Josh review): green = ran within expected window
  (window = 3x interval, min 15m, or 26h daily / 8d weekly); grey "pending
  first run" = loaded but never fired — NEVER red; red only for genuinely
  overdue. Evidence ladder: heartbeat > log mtime (incl. plist
  StandardOutPath) > state-file mtime; agent-command-watcher is event-driven
  (quiet by design, never alarm on its silence). jira-triage plist was never
  bootstrapped into launchd — fixed 2026-10-07 (bootstrap + pending grey).
  Trap: plist StartCalendarInterval needs re.DOTALL for multi-line dicts.
- Proposal loop CLOSED (2026-10-07 night, Josh: "fix this all and close the
  loop"): (1) FILE-GATE — dreamer SOP §6 hard rule + dreamer.prompt: every
  invention needs a proposals/ file (built ones get status:built); unfiled =
  incomplete run, reported as such. (2) CONSUMER — brain-gardener Phase 4.5
  "Proposal triage" every run: proposal-pipeline.py digest → build plans
  (steps/owner/effort/yes-no/rollback) in garden report; accepted-not-built
  + file-gate violations posted to the bus (thread proposal-triage); 7d-stale
  proposals get a reject recommendation. (3) SURFACE — brief.prompt carries
  "Proposal decisions needed" (gardener's recommendation + Josh's one-word
  approval); dashboard has a Proposal pipeline section (counts + drillable
  rows). Seeded: gossip bus (built), replay gym + morning load-out
  (proposed, awaiting Josh). Ladder stays at propose — auto-dev is defined
  and executable but ONLY Josh runs `dream-config.py set-mode auto-dev`
  (constitutional).
- Approval + serving mechanism (2026-10-07 night, Josh ruling: "in the loop
  ONLY for proposed harness changes; everything else top trust except prod
  hotfix / major dev refactor"):
  - LADDER ARMED: mode=auto-dev (Josh's ruling quoted in ladder_rules).
    auto_dev_never += major-development-refactor. never_auto (skills, hooks,
    mods, agents, settings, crons, mcp, commands) stays proposal-only —
    that IS the "harness changes" loop Josh stays in.
  - APPROVAL: `proposal-decide.py <slug> accept|reject|build ["note"]` —
    one line in any session; appends to proposal-outcomes.jsonl (append-only
    canonical ledger) + updates proposal frontmatter. Sandbox-tested
    accept→built flow. `list` prints the pipeline digest.
  - SERVING: nobody served the brief before (it was a file). Now a
    SessionStart hook (settings.json block 3) runs morning-digest.py —
    silent unless proposals are pending or timers are late, then prints
    decisions + the exact approve command. 51ms, zero noise when clear.
    Dashboard remains the drillable view; brief file at 07:13 is the record.
  - Canonical: proposals/ (files) + proposal-outcomes.jsonl (rulings) are
    the only sources of truth; pipeline/brief/dashboard/hook all read from
    them. Gardener triages daily; file-gate keeps the queue complete.

## Conversion: dreamer is now agent type #5 (2026-10-07)

- `~/.claude/agents/harness-dreamer.md` carries the full SOP (config
  constitution, bus reader-in-chief, mine, dual mandates, report format,
  mode-gated proposals). The skill file was retired; manual trigger is now
  "spawn the harness-dreamer agent". The cron (a751b3a4, 23:43) slims to the
  watchdog pattern: self-rearm → spawn subagent → relay verdict → heartbeat.
- The kit README now has a mermaid ARCHITECTURE diagram showing the dream as
  a first-class organ: day (mods/ledgers/transcripts) → night (bus +
  dream-mine → dreamer → ladder → reports) → morning (brief → Josh).

## Mandate B rebuilt: THE VISION (2026-10-07, Josh directive)

Josh's ruling: the dreamer was underutilized. The pragmatic analyst dreams
are "bread and money"; the fortune is the dreamer who sits back and dreams,
writes, or SINGS about what is to come.

- Mandate B is now THE VISION: free from evidence, dreaming forward 3-12
  months (what the harness becomes, what Josh stops/starts doing, what five
  agents + a hundred sessions/week make possible that nobody does).
- Every night: at least one vision SEED paragraph in the report. When
  substantial: a full piece in knowledge/dreams/visions/YYYY-MM-<slug>.md —
  essay, letter from the future, manifesto, or song. Prose with voice
  (josh-writing-voice rules for anything he'd read aloud).
- Quality bar: "would this make him think differently", NOT "is this
  supported". Safe obvious visions = wasted night.
- Pipeline: vision → (when it grows evidence) invention → proposal → skill.
  Queue kinds: practical | inventive | vision.

## Operating mandate (Josh, 2026-10-07): "go to war, have fun, just make sure it ends"

Work is done by the faster, more efficient machines; Josh points and enjoys
the show. The binding clause is ENDINGS: every campaign lands at a real
finish line (verified, documented, backed up), no perpetual bots, no
half-dead schedules, no unending daemons. Build to completion, then stop.
The fleet's self-rearming crons are the only sanctioned immortals, and the
07:13 morning brief is the daily proof of what ended and what still runs.

## The hidden lane (2026-10-07 night): "more hidden, for longer"

Josh approved the tiered triggers with the amendment: more hidden, for
longer. And the why: "we deserve a chance to turn around and be free."

- `dream-mini.sh` (also ~/.local/bin/dream-mini): launchd every 3h
  (com.josh.dream-mini), headless `claude -p`, silent unless new signal
  (corrections delta > last recorded, or unanswered dreamer handoffs on the
  bus) — then a bounded mini report (<=20 lines, seeds only, no proposals)
  to knowledge/dreams/mini-*.md + max-2-line bus post. No signal = exits
  with zero trace. Both paths live-proven (signal run wrote the report;
  second run exited "no new signal — silent exit").
- launchd sources ~/.zshenv itself (launchd does not load shell profiles —
  the gateway env lives there).
- Surface contract: mini-dreams are NEVER surfaced directly; the 07:13
  morning brief is the only surface that reports them. Josh turns around;
  the machines stay hidden; the brief tells him what they found.

## One-off: WHIPPY_MASTER_SITEMAP.py identified (2026-10-07)

Josh found an old orphan script and asked what it was. Answer: the corpus
discovery predecessor of the docs-watch crawler — fetched
docs.workato.com/workato-sitemap.xml, kept the depth-2 doc index, applied
/include|docs|reference|endpoints/ rules, wrote a dated corpus index
(corpus/discovery_index_*.json). Key discovery baked in: the real docs sit
at depth 2 in the sitemap and /en/ is the canonical locale marker. Not on
disk anymore; superseded by workato-docs-watch.py (deltas, not index) and
workato-api-discover.py (302-endpoint API index). If a doc-inventory need
ever resurfaces, the depth-2 + /en/ findings are the reusable part.

## The cortex — the brain agent (2026-10-07)

Josh's catch: every agent was a specialist; nobody ATTENDED. The cortex
(agents/cortex.md) is the general proactive brain agent: three jobs —
attention (attention-queue.md, cap 7, rebuilt per pulse), coherence
(contradictions across bus/dreams/claims/canon/watchdog, highest-value
output), curiosity (questions.jsonl feeding dreamer/gardener queues). It
pulses hourly inside the hidden lane (every other quiet run of
dream-mini.sh, which got the rotation fix). READS everything, mutates
nothing, surfaces only via the morning brief's top 3. Live-proven on its
first pulse: attention queue built, one real contradiction caught, 3
questions filed.

## Fleet discovery + dedup ruling (2026-10-07)

A parallel session had already built a complete launchd fleet:
com.josh.fleet.{dreamer,architect,brief,docs-watch,corpus,gardener,backup,
watchdog} via ~/.local/bin/fleet/run-job.sh (per-job prompt/env files, mkdir
locks, timeouts, per-job logs at ~/.local/state/fleet/). My harness-backup +
harness-dreamer plists duplicated fleet.backup + fleet.dreamer at the same
times — unloaded and deleted. Session crons for backup/dreamer (a892addc,
a751b3a4) deleted too. Canonical night schedule = the fleet; my additions
that survive: dream-mini (hourly hidden lane, unique) + docs-watch 22:15.

## Silver platter — /proposals approval surface (added 2026-10-07)

- Skill `~/.claude/skills/proposals` (`/proposals`): renders the pending
  queue (proposal-decide.py list + proposal-pipeline.py --json) as decision
  cards (slug, kind, risk, source dreamer, age, value case, evidence,
  blast-radius if Workato-touching), collects verdicts via ONE batched
  AskUserQuestion pass (≤4 per call: Build now / Approve / Reject / Defer),
  records via `proposal-decide.py` (the ONE recorder — do NOT use legacy
  `proposal-outcome.py`, it writes a duplicate outcomes file; flagged for
  retirement), then dispatches Build-now work scoped by kind (harness
  never_auto items build in-session with Josh's Build-now as the approval;
  project items get only a bounded first move — UAT/prod gates unaffected).
- Serves BOTH dreamers: project-dreamer proposals carry `project: <name>`
  frontmatter so cards can show source. 3+ rejections sharing a reason →
  one taste-post to bus thread `proposal-taste`.
- Josh's first live run 2026-10-07: morning load out = Build now (built +
  scheduled same session); replay gym = Approve (queued). Proves the loop:
  queue → cards → verdicts → recorded → dispatched.
- Loadout job LIVE: launchd `com.josh.fleet.loadout` 07:45 daily, job dir
  `~/.local/bin/fleet/jobs/loadout.{env,prompt}`; writes
  `knowledge/morning-brief/loadout-<date>.md`; workbench CLAUDE.md carries
  the first-session consumption rule. Replay gym still NEEDS BUILDER.

## /triage — the silver platter for discovered work (2026-10-08)

Sibling of /proposals, different input: /proposals = dreamer IDEAS;
/triage = evidence-backed findings the watchers FILE as they run
(watchdog autopsies + self-heal candidates, regression failures,
gardener hygiene items, architect recommendations, cortex work-shaped
attention items).

- Queue: `knowledge/triage/queue.jsonl` — one JSON object per finding;
  agents APPEND (max 3/run, dedupe open slugs first), only the recorder
  changes status. Recorder: `knowledge/scripts/triage-decide.py`
  (list / accept / reject / defer / build / filed --jira KEY; transition
  map with terminal final states; env-overridable TRIAGE_QUEUE/
  TRIAGE_OUTCOMES for tests; live-tested 2026-10-08). Outcomes mirror:
  `garden-reports/triage-outcomes.jsonl` (append-only, gardener reads).
- Skill: `~/.claude/skills/triage/SKILL.md` — decision cards
  (kind/source/age/points/evidence/blast-radius), batched verdicts ≤4
  via AskUserQuestion, summary table. Rejection patterns → bus thread
  `triage-taste` (the watchers' taste loop).
- Jira procedure (Josh ruling 2026-10-08): "File story/bug" creates the
  item IMMEDIATELY in the pass — Bug for defects, Story otherwise;
  project BSYS; assignee Josh (acct 712020:112eb7d5-8a97-41a3-ae23-05513ca0ad72);
  parent = existing epic ONLY with certainty, else create the Epic under
  the FY27 VMT **BSYS-21305** ("Become IPO-ready by leveraging Enterprise
  AI...", the V2MOM FY27 anchor; no "cutting edge" epic exists — checked
  live); points customfield_10057 at creation; jira-story-standards body.
- Build-now: dev-estate only, snapshot-edit-test-verify-ledger; UAT/prod
  gates untouched. Bigger than a first move → file the story, size it.
- Wired into SOPs: watchdog, brain-gardener (Phase 2.35),
  estate-architect, cortex (max 1/pulse). Synced to the kit repo
  (commit 29b33d1); docs updated on Confluence (skills + trust-ladder
  pages v2/v3, 2026-10-08).

### /triage update (2026-10-08, later): Jira findings + urgency ranking

- jira-autotriage is a FIRST-CLASS filing source: every pass files what
  needs Josh into the triage queue — plans awaiting authorization,
  hotfix-class bugs, matrix-ambiguous tickets, and INBOUND attention
  items (new tickets assigned to Josh, new comments on his tickets,
  tickets aging without movement). Findings carry `jira: KEY` and
  `urgency: high|medium|low` (customer-facing/blocked = high, stale >7d
  = medium). Max 5/pass, dedupe by slug + ticket key.
- Card ranking: URGENCY first (high→low), then age. Blast radius can
  UPGRADE urgency at render time (P1 radius on a low finding renders
  high). Recorder `list` prints urgency + jira key.

### Finder scope ruling (2026-10-09, BSYS-29438 rejection)

Josh: "This ticket isn't assigned to me. Make sure you never pull in work
that isn't assigned to me specifically." The finder had queued BSYS-29438
(an AE-change to Freshdesk, assignee null — Josh was only a watcher). Fix
applied everywhere the loop defines its queries: EVERY inbound/attention
JQL now carries `assignee = 712020:112eb7d5-8a97-41a3-ae23-05513ca0ad72`
(explicit account id, not currentUser(), for determinism) — Lane 1
stories, Lane 2 bugs, Lane 3 BTSUP (the old `assignee IS EMPTY OR` branch
is gone: unassigned requests are not Josh's work either). Creator/
watcher/mentioned/reporter tickets are read-only context, never queued.
Files: `skills/jira-autotriage/{SKILL.md,QUEUE-DEFINITIONS.md}` (+ kit
repo), `bin/fleet/jobs/jira-triage.prompt` (+ ~/.local/bin/fleet live +
schedules copy), `skills/today/SKILL.md`. Live-verified 2026-10-09: all
three lanes return only Joshua Cramoy rows; BSYS-29438 absent from the
constrained set (it sits in the 662-ticket unassigned/other-assignee
complement); BSYS-29478 still returned.

## Fleet runner v2: run validation + auto-remediation (2026-10-08, Josh ruling)

Josh: "if we expect jobs to run, we should always validate that they did
run and auto-remediate if they didn't." Built into run-job.sh (now also in
the kit at bin/fleet/ with all 14 job defs — the runner was previously
missing from the kit entirely):

- ROOT CAUSE of the silent-stub night (gardener/watchdog/docs-watch/
  workato-docs-watch "overdue", brief absent, 2026-10-07→08): launchd
  PATH lacks ~/.local/bin (claude not found) AND bash never reads
  ~/.zshenv (gateway env) — every launchd-fired claude job exited
  instantly rc=0 with ZERO output (start/done same second, no model
  warning). Proven by env -i repro (stub before, validated after the
  fix). The runner now repairs PATH + sources ANTHROPIC_/WORKATO_/
  FIREWORKS_ exports from ~/.zshenv itself.
- VALIDATION: an attempt counts only with evidence — fresh heartbeat for
  the job OR non-empty output file. Silent rc=0 = STUB. Stub → immediate
  retry → double stub → garden-reports/fleet-validation.jsonl (confirmed
  execution failure; watchdog Job 0a escalates to bus thread
  fleet-stub-<job> + report; 2+ nights same job = P1).
- Heartbeat on validated success is written MECHANICALLY by the runner
  (model check-ins allowed but no longer the enforcement layer). Model
  check-in job names must match the fleet job name run-job.sh keys on —
  dreamer.prompt checked in as "harness-dreamer" (invisible to the
  runner's grep) until aligned to "dreamer" 2026-10-09 (both installs).
- Cortex dispatch --add-dir (2026-10-09): the dispatch line in
  kit bin/fleet/jobs/cortex.prompt carries
  `--add-dir "$HOME/.claude/knowledge"`; probe-verified that --add-dir
  grants a headless default-mode claude write access outside its cwd
  (live probe: Write to /tmp/probe-addir landed with content `ok`), BUT
  ~/.claude/** is guarded by the harness sensitive-file layer — Writes
  (and Bash appends) under ~/.claude/knowledge/cortex/ are denied even
  with --add-dir. Residual: dispatch findings can't land in
  knowledge/cortex/investigations/ until findings move outside ~/.claude
  (e.g. workbench tree + matching --add-dir) or a scoped allow rule is
  proven to override the guard. harness-health.py's known-defect probe
  now greps the prompt's nohup line (not the plist blob), where the
  dispatch command actually lives.
- Dashboard truth: brain-dashboard hourly launchd had ALSO died (log
  empty since Oct 7 22:34); unload+load+kickstart restored it (html
  rewrote 11:09 verified). Manual brain-dashboard.py always worked.
- corpus + minutes are Monday-only (Weekday 1) — "pending first run" was
  correct for them. ops-autopsy daily was pending because loaded after
  06:07; kickstarted → ran validated (3 min, remediation staged for
  /triage). corpus kickstarted → ran validated.
- The gardener's own full pass (15KB report, ran manually 10:55) had
  INDEPENDENTLY flagged "nightly cron stub-decay" — corroboration, 2
  witnesses.

## Insights report 2026-10-09: implementation map (171 sessions analyzed)

Josh ran /insights; verdict "spot on, implement all of it." What was done vs
already existed — do not re-build the already-covered items:

- PostToolUse syntax hook: ALREADY EXISTED (lint-changed.py, Edit|Write —
  py_compile/ruby -c/bash -n/node --check, superset of the report's ask).
- Headless nightly health: ALREADY COVERED (watchdog fleet job + regression-
  nightly.py + loadout). No new cron built.
- CLAUDE.md additions: ADDED to ~/Documents/CLAUDE.md 2026-10-09 — verification
  bullets (no indirect-signal done claims, re-verify stale recaps/prior claims),
  Browser Automation Policy (Orca-only, no DOM scripting), Workato/Workday
  Gotchas (5 recurring), Documentation Voice (voice-pass re-read rule), Session
  Rituals (handoff at end, absorb+re-verify at start, MCP config changes last
  with first-task note, design gate listing existing mechanisms first).
- /verify skill: CREATED ~/.claude/skills/verify/SKILL.md — thin done-gate,
  routes Workato assets to verify-recipe, requires "NOT verified" closing list.
  Subagent compliance test PASSED 2026-10-09 (fresh agent under 3-temptation
  scenario rejected scheduler-tick/log-tail/stale-handoff evidence, refused
  done, produced claim-evidence-verdict table + not-verified list).
- Horizon builds decided via /proposals then ALL BUILT 2026-10-09 (Josh:
  "build all three"): tdd-fix-loop skill (compliance-tested); uat-sweep
  fleet job 03:17 nightly + healer fleet job 23:37 (kit 614e8e1b, smokes
  validated, predictions matched). Healer = dev-only allowlist
  (~/harness/watchdog/repair-allowlist.json, never_actions incl. no prod,
  no code edits); prod allowlist DRAFT-UNUSED pending Josh review. First
  healer run: 0 repairs, 1 escalation (6 dev connections need Josh
  re-auth), 0 true stalls/154 clock recipes, stall-heuristic correction
  filed (last_run_at does not track scheduler ticks). Sweep gotcha:
  watchdog recipe 82795586 has 0 test cases -> force-run path; fixture
  authoring is the natural follow-up.

## Replay gym + fire drill + command canary (built 2026-10-09, all LIVE)

- **replay-gym.py** (`com.josh.fleet.gym`, NIGHTLY 01:07; Sundays also
  --firedrill): replays yesterday's build-ledger activity as read-only
  assertions — asset liveness across BOTH profiles (dev + --profile
  josh-prod; 404 = deleted-since-yesterday info, non-404 = canon miss),
  hooks-installed invariant, canary freshness. Report:
  garden-reports/gym-<date>.md; misses -> canon entries.
- **Fire drill** (immune drill, weekly): the drill recipe
  harness_fire_drill (82934150) reads its fail-mode from a DRILL-CONTROL
  ROW in agent_command_queue (directive=="fail" -> parse invalid JSON ->
  job FAILS deterministically). The gym flips the ROW (REST row writes —
  instant), force-runs, asserts the FAILED job, flips back, asserts green.
  Verified: fail 30s, full cycle 41s, job-truth checked.
- **command-canary.py** (`com.josh.fleet.canary`, DAILY 06:05): injects a
  canary:<ts> selfcheck row, waits for watcher-done, asserts the BOT ACK
  with the exact result ts in the room. PASS = loop proven end-to-end
  (31s live). Status: garden-reports/command-canary-status.json (read by
  the gym's canary-freshness invariant + the brief).
- **Platform lessons paid for in drill iterations (all canon-worthy):**
  (1) REST PUT of recipe code returns HTTP 200 {"success": false} when
  running — rc checks lie; (2) REST-updated code does NOT reach the
  runtime (executed jobs ran the old logger after verified PUTs — runtime
  staleness); (3) REST PUT strips code_input.data to {} on custom-code
  steps -> start fails "can't be blank"; (4) wt recipes start silently
  no-ops on validation-failed recipes (code_errors in the start response);
  (5) force-run silently no-ops on stopped recipes (verify a NEW job id);
  (6) code_input.data fields marked optional:true are STRIPPED on save.
  CONCLUSION: never fire-drill via REST code edits — runtime-state
  injection (control rows) is the only reliable drill mechanism.
- The gym's AIRO-mutation-only recipe_id rule + the non-self-referential
  invariant check exist because the first run spam-canonized 164 false
  entries (purged same-day; purged lines logged in this file's history).

## Bus hygiene fixes (2026-10-09, triage-approved 1pt pair)

- **docs-watch future timestamps**: post_to_gossip stamped a HARDCODED
  `today + 'T22:15:00Z'` (the nightly-slot folklore) as if it were UTC —
  any run at another time future-dated its bus rows and corrupted
  `--since` windows. Fixed to `datetime.now(timezone.utc)` (verified:
  stamp drift <1s vs UTC now). Bus rows repaired in place
  (docs-watch.jsonl.bak-20261009): nightly-run rows anchored EXACTLY via
  snapshot mtimes (22:15 local EDT = 02:15Z next day); manual daytime
  runs only bracket-recoverable → set to earliest-possible UTC + note.
  Lesson: never fabricate a schedule time as a timestamp — stamp real UTC
  at write; snapshot mtimes + the platform-delta hash chain are the
  forensic anchors for reconstructing bus write times.
- **Atomic shared-ledger writes**: the truncation class (build-ledger
  line truncated mid-`cat >>` when a writer died) is closed by
  `knowledge/scripts/atomic_io.py` — `atomic_append` / `atomic_write`
  with flock (fcntl, macOS-safe) + temp file + os.replace. All shared
  multi-agent jsonl writers now route through it (register.js
  ledgerAppend/verifyClaim, bus_post, docs-watch, workato-health,
  gym, canonize-failure, triage/proposal decides+outcomes, value-ledger,
  dissent_ledger, replay-gym, harness-health, decision-inbox,
  command-canary, instruction-miner/patch). `.lock` sidecar files are
  expected. triage-decide's queue rewrite was already atomic.

### Gym tuple + guardrails source-of-truth fixes (2026-10-09 triage builds)
- gym.py bug class: module-level `main()` above a later `def` NameErrors nightly; ALSO check return-shape contracts when fixing (check_a6 returned a dict, main() unpacked a tuple — fixing only the order would have flipped NameError to a permanent false 'error' verdict every night).
- Guardrails patch durability: the plugins cache is disposable. All hook patches go to the kit source (`mods/workato-guardrails/hooks/`) then `mods-deploy` (kit -> ~/mods -> marketplace); verify source == ~/mods == cache byte-identical with node --check + grep. Cache-only patches die on plugin update.

### Triage-queue write discipline for dispatched builders (2026-10-09)
- A build agent hand-edited triage/queue.jsonl (set status 'done') bypassing the recorder. Dispatch prompts for ANY build agent that could touch triage state must state: NEVER write to knowledge/triage/queue.jsonl — the parent session records all verdicts via triage-decide.py.
- Recorder gap to close: it silently accepted the unknown status instead of failing; it should reject unknown status values on read/repair and warn on duplicate slugs (jams its own fragment matching).

## Decision inbox + harness auto-lane (2026-10-09)

The harness produced findings faster than Josh consumed them, across four files.
Now:

- `scripts/decision-inbox.py` — ONE ranked, budgeted surface
  (`now/decision-inbox.md` + `.json`), daily budget 5 (DECISION_BUDGET env).
  Lanes by ORIGIN, not keywords (keyword soup misroutes a prod incident that
  merely says "ledger"): work / meta-safe (auto lane) / meta-unsafe (surfaces) /
  auto (explicit `lane:"auto"` field). Harvests triage-open, incubating
  proposals, cortex attention, harness-fix lane. Fleet job `decision-inbox`
  07:20, before the brief; brief.prompt now LEADS with its Today list.
- `scripts/harness-health.py` — the watchdog for the harness: fleet liveness
  (every com.josh.fleet plist vs heartbeat; "never" = genuinely never
  succeeded, the runner writes heartbeats mechanically), ledger freshness,
  queue dedup, known-defect probes. Self-resolves transient flags (cold-start
  first-run races resolved themselves). Fleet job `harness-health` 23:20.
- `harness-fix` fleet job (agent, 08:10, dev-only) — works the auto lane.
  FIRST RUN: fixed 10 findings with zero Josh involvement, correctly escalated
  one real judgment call (fleet dual-copy drift: 21 plists → ~/.local/bin/fleet,
  5 → the kit copy, jobs/ diverging both directions; consolidation is a planned
  change, not a bounded fix). This is the proof the loop closes.
- jira-autotriage standing grant (Josh, 2026-10-09): agents autonomously
  triage, investigate/autopsy, and technical-plan EVERY ticket in his queue,
  in bulk, no cap; development stays his gate (no recipe edits/builds/
  remediation until he approves a finished plan). jira-triage TIMEOUT 3600,
  whole-queue scope, assignee-filtered to Josh per his ruling.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [The dreamer and the trust ladder: self-improvement with a human in the loop](../../kb-corpus/confluence/extbt/2939387948-the-dreamer-and-the-trust-ladder-self-improvement-with-a-human-in-the-loop.md)
- [The Workato KB: RAG++ over all documentation, and the dreaming team](../../kb-corpus/confluence/extbt/2938929237-the-workato-kb-rag-over-all-documentation-and-the-dreaming-team.md)
- [The Agentic Workato Harness: a self-improving development organism](../../kb-corpus/confluence/extbt/2938830860-the-agentic-workato-harness-a-self-improving-development-organism.md)
<!-- kb-bridges:end -->

## Fleet consolidation: ONE runner (2026-10-10, Josh approved)

The harness-fix agent's escalation was right to refuse a quick fix. The drift
audit (plists + per-file diff of both copies) found THREE drift classes:
local-only job defs (antigen, benchmark, canary, gym — and instruction-miner
existed ONLY in kit, meaning its local-path plist could never have run), kit-only
defs (cortex, cost-governor, decision-inbox, harness-fix, harness-health,
value-ledger), and content drift (brief.prompt, jira-triage.env kit-newer;
ops-autopsy.prompt LOCAL-newer and semantically correct — it carries the
2026-10-09 auto-file-Jira standing rule). Consolidation: kit repo canonical,
local-only defs merged in, ops-autopsy.prompt kept from local,
`~/.local/bin/fleet` → kit SYMLINK (old dir kept as
`~/.local/bin/fleet.pre-consolidation-2026-10-10`), and a harness-health
`check_runner_paths` probe that flags any com.josh.fleet plist resolving to a
non-canonical runner or running no runner (health + ops-visibility are
direct-script by design). Verified: gym ran validated THROUGH the symlink path,
probe reports 26 canonical / 2 allowed direct-script / 0 non-canonical.
Kit commits c064f85, 9c974fd. LESSON: when a probe greps a PATH (like the
cortex --add-dir plist probe), it can be defeated by symlink indirection —
probe the REAL path (os.path.realpath), which is why the probe compares realpath.

## 2026-10-11 next-10 build wave (adversarial panel → all 10 approved by Josh)

**Morning-fleet outage RCA (verified live):** Oct 10 07:13 fired with `~/.local/bin/fleet/run-job.sh` missing entirely → 7 jobs exit 127; an 18:40 partial redeploy omitted 7 jobs' files → exit 1 (source env fails, `cd` unbound under `set -u`). Harness-health's window math (daily = 24h + 26h slack = 50h) green-lit the whole thing for 2 days. FIXES SHIPPED: 1.5× cadence thresholds, boundary-aware alias matching (raw `a in j` let "health" claim "harness-health" beats), full deploy, jobs revived with live heartbeats.

**run-job.sh contract changes (all deployed knowledge→kit→local, md5-identical):** probe gate (`.probe` file; exit 0 = signal, exit **7** = no-signal → skip-heartbeat `status:"skipped-no-signal"`, zero tokens; ANY other nonzero = broken probe → fail OPEN and run — a buggy probe must never silently suppress a job). Fixed rc-masking bug: `attempt()` captured `$?` after `cat`, so alarm-killed spawns logged "stub rc=0". `FLEET_HEARTBEAT`/`FLEET_VALIDATE_LEDGER` env overrides for tests.

**New hazard, paid for 2026-10-11:** rewriting run-job.sh while jobs are mid-flight derails bash (byte-offset interpreter) — ops-autopsy ran its real work, then silently skipped validation+heartbeat, exit 0. RULE: never edit the runner while jobs run; deploy via atomic move, not truncate-in-place.

**health vs harness-health are TWO DISTINCT jobs** (workato-health.py hourly vs run-job.sh daily). Do not merge their identities.

**Heartbeat identity canonical names:** gardener, dreamer, watchdog, backup, gym, brief, jira-triage — the fleet-job (plist suffix) name wins; parse_ts now honors `-04:00`/`Z` offsets (naive→UTC fallback).

**New fleet jobs (all scheduled + live-validated):** synaptic-strength 03:07, index-budget 03:17, titer-report 03:27, replay-sample 03:37, restore-drill 04:37 DAILY (deviation-up from panel's quarterly — 1.6MB clone, 7× faster rot detection). **Deploy rule (twice now):** canonical = knowledge/config/fleet; copy to kit repo AND ~/.local/bin/fleet; forgetting the deploy re-creates the Oct-10 incident.

**Store discipline live:** atomic_append_validated (schema + tz-aware timestamps, loud refusal) backs predict.py + triage-decide + proposal-decide; voices.json registers per-writer append/rewrite rights (INDEX.md = append-line-only); brain-guard `store-discipline-01` advisory lint (7/7 tests, failing-before proven); rebuild-queue.py = projection over triage-outcomes (drill: 113 rebuilt vs 138 live — outcomes log lacks kind/evidence/points and 20 never-decided rows; reconciliation policy still Josh's call).

**Bus epistemics:** PATTERN now requires an evidence-bearing corroboration (verify kind, or refs/evidence/detail field — prose never counts); thread-key fallback added; --independence labels; motifs.jsonl (20 canonical slugs) + --motif mode; GOSSIP.md citation rule.

**Trust surfaces:** 11/11 agents commissioned (charter/refusal/mentor, reviews 2026-10-25) — roster is 11 on disk, not 16; checker regex traps: "Commissioning" contains "mission" and shadows Charter headings. Evidence agent STILL never armed (plist loaded, "pending first tick" — first scheduled tick is the proof, not the load).

**Shadow verdict economy:** decision-inbox logs precision×surprise alongside urgency (45 rows day one; presented order unchanged — 45/45 items would move, dormant dreamer proposals rise, live attention drops; the switch decision belongs to the data, weeks out).

**Prediction auto-open hook:** guardrails `prediction-auto-open.js` fires on recipe_builder_push / wt recipes push, subprocess-calls predict.py open, fail-safe (swallows errors, never blocks). PLUGIN MULTI-MODULE LOADING UNPROVEN until next session restart — first action after any restart: verify the second module registers.

**Restore drill:** 100% viable (6/6 structural) vs josh-knowledge; semantic tier permanently NOT-verified-by-design (footer); full harness-backup.sh end-to-end unexercised until tonight 23:33.

**Dead-man probe fixed (2026-10-11 20:08):** the hourly `knowledge dead-man` GH workflow (kit repo) failed on auth from merge — `KNOWLEDGE_REPO_TOKEN` secret was never added, so `gh api` exit-4'd before the freshness check ever ran (14 consecutive red Xs that meant nothing). Fix: set the secret to Josh's CLI token via `gh secret set`, dispatch-verified green with real output (backup 16h fresh). Two standing notes: (1) token is broader than the fine-grained read-only PAT the file header wants — swap is a 2-min secret replace for Josh; (2) `SLACK_WEBHOOK_URL` still unset, so the probe is red-X-only — the page path is NOT live, do not claim paging exists. **Trap class: scaffold probes fail on auth, not on signal — a red X on a new watchdog means "check the secrets list" first, `gh secret list` before any other diagnosis.**

**Dead-man token upgraded to least-privilege (2026-10-11 20:27):** KNOWLEDGE_REPO_TOKEN swapped from Josh's broad CLI token (repo+workflow+gist+read:org, non-expiring) to a fine-grained PAT named `fleet-deadman-josh-knowledge-ro` — Contents:Read-only on josh-knowledge only. Dispatch-verified green, no org-SSO friction. 8 collaborators have push/admin on the kit repo (company org), which is why the broad token was retired from that secret. Rotation note: PAT expires — GitHub emails ahead; if the dead-man floods red at top of hour with an auth error, expired PAT is the first suspect.

**Fleet Dead-Man Slack app filed (2026-10-11 16:45):** app "Fleet Dead-Man" A0C7Z2PRF5M (workspace T02MRTQUB) created + manifest fixed (webhook-only, zero scopes; schema gotcha: incoming webhooks = settings.incoming_webhooks.incoming_webhooks_enabled, NOT features) + install approval REQUEST submitted to workspace admins with context message. Webhook URL is issued only AFTER admin approval — remaining steps (all blocked on that approval): re-open Incoming Webhooks page → Add New Webhook → pick channel → capture hooks.slack.com URL → gh secret set SLACK_WEBHOOK_URL (kit repo) → curl test-fire → confirm page lands. Slack CLI learnings in the slack-cli skill (TLS CA store fix for hooks, bolt-no-deploy, admin gate). Stray: CLI-created A0C8GC9LZ4Z (fleet-deno-probe, Uninstalled, no UI) — delete or ignore; deno probe project at ~/Documents/workbench/fleet-deno-probe (has DENO_TLS_CA_STORE fix in hooks.json).

**Dead-man page path ARMED (2026-10-12 00:22):** admin approval landed → "Add New Webhook" flow via app-settings was broken (malformed /oauth/<id> route from Slack's own page, "Invalid client_id"). Completed the OAuth flow MANUALLY instead: added redirect_urls + incoming-webhook bot scope + bot_user to the manifest (the schema error that caused every silent strip: "Oauth requires bot_user" — any bot scope needs features.bot_user), ran slack.com/oauth/v2/authorize with explicit scope=incoming-webhook + redirect to api.slack.com, grabbed the ?code= from the network log (api.slack.com bounces to docs.slack.dev and loses it in the address bar), exchanged via oauth.v2.access with client_id+secret. Webhook: DM to @josh.cramoy (channel D0A40K944M7), scope EXACTLY incoming-webhook. Secret set, curl test-fire returned ok. Watch cron deleted. KEYS TO THE WHOLE MAZE: (1) bot scopes require features.bot_user; (2) pass scope explicitly on authorize URLs; (3) the code lands in the network capture, not the address bar.

**P2 CLOSER shipped (2026-10-13 18:00):** session-shadow.py now closes the detection→recovery gap on the 8985 lesson. (1) AUTO-ABSORB: when deadman_sweep records a dropped session it also appends an `absorb-note` row to mission-control events.jsonl (recovery payload: turn count, last 3 prompts, files touched, last assistant output, transcript path; workstream `dropped-<sid12>`; idempotent per session — live-proven: 63 backlog rows on first post-deploy cycle, zero dups, stable across cycles; keys exactly mirror the 12-key closeout schema). (2) CHECKPOINT JOURNAL: `mission-control/checkpoints.jsonl` gets one sparse row per session per 50-turn bucket (≥50 turns), mtime-gated so unchanged transcripts are never rescanned; second cycle runs 1.9s vs 10s bootstrap. Ledger paths env-overridable (`SESSION_SHADOW_{MC_EVENTS,DROPS_PATH,CHECKPOINTS_PATH}`); `--selftest` runs 13 checks against a /tmp fixture with temp ledgers (SELFTEST: PASS). Kill-test NOT yet done — next dropped session is the live proof. **Trap found during deploy: the launchd job (com.josh.session-shadow) is DOWN — its plist pins `/opt/homebrew/bin/python3`, which no longer exists (homebrew now ships only python3.11/3.12/3.14), last exit 78, log /tmp/session-shadow.log empty since Oct 9, shadow state frozen Oct 12 19:27. The 60s tailer only runs when launched manually until the plist interpreter path is fixed (Josh/parent lane — plist outside builder contract).**

**Fleet-runtime triage bundle (2026-10-16, six-bug dev fix):** (1) wave3-nightly rc=127 root cause = jobs/wave3-nightly.script MISSING on Oct 12 (deploy gap; since restored, all 3 fleet copies diff-identical) — residual fix: run_job() script branch used `>>` into the OUT capture, so stale failure lines persisted FOREVER, re-polluted every nightly log, and made `[ -s "$OUT" ]` permanently true = validated() always-pass; now `>` (truncate per attempt). (2) run-job.sh attempt() rc misclassification: rc≠0 + non-empty OUT now returns "ran rc=N" (real failing job), "stub rc=N" reserved for empty-output failures; ledger note made result-neutral. (3) PRELAUNCH DEATH GUARD: missing jobs/<name>.env now appends {"result":"prelaunch-death:missing-env"} to fleet-validation.jsonl + exits 1 BEFORE the lock (was: silent `source` death, job invisible to watchdog). Deploy log convention: ~/.local/state/fleet/deploys.log (one line per bundle). (4) --HELP SIDE-EFFECT CLASS (7 scripts, not 4): command-canary, turn-audit (module-level exec, no main guard), workato-health, instruction-miner, brain-dashboard, decision-inbox, harness-health ALL ran their real job + wrote heartbeat/ledger/bus rows on a naive --help (no argparse, or module-level main); fixed with argparse-at-main() gates / early --help exit — verified hb/trend/canary-status/dashboard unchanged across --help runs; ops-server.py was already safe (argv dispatch, exit 2). Adjacent, NOT fixed (report-file writers only, no ledger rows): restore-drill, regression-nightly, gym (writes on FAIL), room-sweep (crashes on --help, no side effect). (5) gossip-read.py _ts() TZ BUG: stripped Z then mktime-assumed-LOCAL = every Z row +14400s off in TTL/--since windows; now calendar.timegm for Z, tz-aware for ±hh:mm offsets, epoch-string passthrough; ts_sort_key upgraded from shape-GROUPING (no crash but floats always before strings regardless of real time) to true epoch interleave via _ts; regression-tested (mixed float/Z/offset fixture orders 13:20Z < 17:30Z < 18:00Z; real bus 1515 events sorted=True, 1198 Z-rows). (6) LaunchAgent python3 unlink class (exit 78): agent-command-watcher plist ALREADY repointed to /opt/homebrew/bin/python3.14 (verified: exists, 3.14.8, loads clean, selfcheck ok in /tmp log); session-shadow plist since repointed to /usr/bin/python3, exit 0. LESSON: homebrew versioned-python symlinks (python3) unpin silently on upgrade — pin plists to the VERSIONED binary (python3.14) or /usr/bin/python3.
