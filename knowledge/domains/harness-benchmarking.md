# Harness benchmarking — A/B bench, full harness vs vanilla

Built 2026-10-12 (spike, Josh-approved). Answers "is the harness/brain worth its overhead?" with controlled numbers instead of vibes. Artifacts: `bench/harness-ab/` (bench.py, score.py, raw results, report).

## The method (reusable, ~30 min per full pass)

- **Vanilla arm**: `CLAUDE_CONFIG_DIR=/tmp/harness-ab/vanilla-config` pointing at a config dir containing ONLY `{env, model}` copied from the real settings.json. Same gateway, same model, zero hooks/skills/agents/plugins/MCP/global-CLAUDE.md. Fully isolated from the real harness — verified, nothing in ~/.claude is written.
- **Full arm**: default config, no env changes.
- Both run headless `claude -p "<task>" --output-format json --dangerously-skip-permissions` in fresh seeded scratch workdirs (no project CLAUDE.md contamination). JSON gives duration_ms, num_turns, usage tokens per run.
- Battery of 6 tasks × 2 reps × 2 arms = 24 runs: lookup, build+run, bug-fix-to-tests, Workato-docs-billing (KB-grounded, scoreable against the procure-to-pay example = 6 Tasks), current web fact, multi-file refactor with unittest postcheck.
- **Scorer gotcha paid for**: postchecks that run `python3 -m unittest` from the run root find 0 tests in seeded subdirs (rc=5) — run from the fixture subdir. Every "fail" in the first pass was this scorer bug, not model failure; workdirs persist so rescoring is offline.

## Baseline numbers (2026-10-12, glm-5.3-flash via gateway)

| Metric | Full harness | Vanilla | Ratio |
|---|---|---|---|
| Trivial lookup wall | 19.2s | 2.7s | 7.2x |
| Trivial lookup in-tokens | 256k | 29k | 8.9x |
| Multi-file refactor wall | 32.5s | 19.0s | 1.7x |
| In-token footprint, all tasks | 5.9–21x | baseline | — |
| Correctness | 12/12 | 11/12 | — |

- **The tax is constant and front-loaded**: ~8x input-token footprint and several seconds of startup on EVERY run (CLAUDE.md, skill listings, MCP schemas, SessionStart hook MCP health check, hook output per tool call). As tasks get real, the ratio collapses (1.6–1.7x wall) because the harness context amortizes.
- **The tax buys accuracy on grounded questions**: T4 Workato billing — vanilla confidently answered "7 tasks" with fabricated reasoning and a plausible-looking doc link (hallucination class); full arm cited the real tasks.md example both times (2/2 vs 1/2). This is THE talking point when the questions come.
- T5 (current web fact) did NOT discriminate — the model's training data already knew Python 3.15. Pick facts the model can't know for future batteries.
- In-token counts are per-run throughput (cache reads included), not necessarily billed cost; on cached requests real cost is far lower. Say "context footprint", not "cost".

## Honest limits

N=2 per cell, one model, one day, headless mode only (interactive sessions load more harness surface). Latency deltas are real but absolute seconds are small for humans (≤50s worst case). Re-run the battery after major harness changes or with a bigger battery before quoting precision beyond ~1 significant figure.

## Capability battery (3-arm, 2026-10-12, same session)

Arms: FULL (harness+glm-flash) / VANILLA (bare glm-flash) / SONNET (bare Claude Sonnet 5.5 via `azure_internal_01/claude-sonnet-5-5`). 5 tasks × 2 reps (bench2.py). Rubric + auto scores:

| Task | FULL | VANILLA | SONNET |
|---|---|---|---|
| C1 Workato sync design (rubric /6) | 5.5 | **4 — told Josh "1 task/night, loops don't bill" (WRONG)** | 6 |
| C2 platform facts /3 | 3,3 | 2,**3** | 3,3 |
| C3 hidden bug | 2/2 | 2/2 | 2/2 |
| C4 build from spec | 2/2 | 2/2 | 2/2 |
| C5 billing-model summary | deepest (KB, step-level) | good | good (best hedging) |
| Wall avg across battery | 53s | 44s | **25s** |
| In-tokens avg | 669k | 122k | 73k |

Findings:
1. **Vanilla-flash's failure class is always the same: confident wrong billing/domain facts** (C1 "1 task/night", C2 task-billing drop, bench-1 T4 "7 tasks"). Structure/design it gets right; the numbers it confabulates.
2. **Bare Sonnet 5.5 matched harness+flash on every capability task and is 2-5x faster / ~10x leaner.** Honest result. What bare Sonnet does NOT bring: governance (prod gates, dedicated apps), memory/knowledge tree, voice, Jira/Slack plumbing, agents, manifests — none of which this battery measures.
3. Local-code tasks (C3/C4) are below the discrimination floor for all three arms — batteries must lead with domain-knowledge tasks.
4. Scorer gotcha struck TWICE: seeded fixtures land in a subdir; unittest postchecks must run from that subdir or every arm "fails" with rc=5.
5. Vanilla/sonnet arms have built-in WebFetch/WebSearch (no settings denial) — sandbox arms are web-capable by default; full arm used KB. Correction: bench-1 T5 vanilla pass was via built-in web tools, not training data.

## Gateway model-routing facts (2026-10-12, verified)

- Bare `sonnet` alias resolves CLIENT-side to glm-5.3-flash via env pins; gateway never sees "sonnet".
- Real Sonnet = two-part IDs: `azure_internal_01/claude-sonnet-5-5` LIVE-VERIFIED (self-ID + modelUsage canonical). `mantle_internal_01/claude-sonnet-5` also works. `bedrock_internal_01/*` = 403 AWS Marketplace IAM (subscription not enabled on Josh's tenant).
- Sonnet via gateway carries real costUSD in modelUsage (first-party billing shape, service_tier field); flash runs report costBasis "unknown".

## Knowledge-lookup battery + framing correction (2026-10-12, bench3)

5 Workato facts (3 public docs incl. cssup Confluence recipe-name 255 / lookup-tables 100; 2 task-billing), full (KB) vs bare Sonnet (web), 2 reps.

| | FULL (harness+flash) | SONNET (bare, web) |
|---|---|---|
| Correctness | **10/10** | correct on all valid runs, but self-flagged "from memory, verify it" on task facts and "didn't open the page" on one |
| Wall per one-shot | 25-71s | 5-17s |
| USD per one-shot run | $0.72-0.97 | $0.07-0.13 |

**The framing correction (Josh's point, confirmed by the data):** one-shot benching charges the harness's ~130k-token context on EVERY run — but in a live session that context is loaded once and amortized across a working day, so the marginal cost of a KB lookup is a sub-second tool roundtrip, and the marginal dollar cost is near the tool call alone. Per-run numbers systematically overstate harness cost and understate its amortized value. The honest per-lookup story: KB = fast, curated, cited (incl. internal BT Confluence), no web dependency; bare Sonnet = cheap one-shots but unverified-memory answers, shallow reads ("search summary, didn't open the page"), web-availability dependent.

**Also failed honestly:** the internal-knowledge moat is NOT secrecy — cssup Confluence is publicly crawlable. The moat is curation depth (34k-doc corpus, internal spaces, fleet-generated content), retrieval speed, and the governance/pace layer around it.

**Pace evidence does not exist as a number and cannot:** build-ledger (14.6k events, Oct only) and mission-control were born WITH the harness — the pre-harness era was never instrumented. Pace is demonstrated by outputs (5+ fleet agents, 34k-doc KB, dozens of BSYS builds in ~5 weeks), not by a fabricated before/after metric. stats-cache dailyActivity changed schema mid-year, so its era comparison is unusable.

**Bench gotchas:** (1) gateway now reports costUSD on flash runs (~$0.72-0.97 per one-shot with full harness context — watch this); (2) `claude -p` intermittently returns empty stdout under sustained load (429-lockout window) — record rc+stderr, retry failed rows; (3) never parse `--output-format json` with string-find — scan for the last JSON object with a JSONDecoder loop; (4) string-match scorers need to handle "**No.**" punctuation variants — rubric-read the actual texts before scoring fail.

## Context-cost layer breakdown (2026-10-12, measure.py + measure_mcp.py)

Trivial prompt, cold start, full harness: **128,193 in-tokens / $0.64** (gateway rate ~$5/MTok blended). NO-MCP variant: **24,445 / $0.12**. NO-PLUGINS: identical to full (tool search defers plugin skills = plugins are free).

**MCP servers = ~104k tokens = 81% of the harness tax.** Per-server delta vs 24.4k baseline:
HEAVY: airo-dev +20.7k, airo-prod +20.1k, gslides +16.4k, atlassian +15.4k, gmail +11.0k, slack +9.8k, workday +7.0k (sum 100.4k). CHEAP (tool search deferring well): semantic +1.2k, duckduckgo +1.2k, fireworks +1.0k, org-chart +0.9k, brain +0.5k, kb +0.3k, registry +0.3k (sum 5.4k).

Static always-on context: CLAUDE.md stack 8.3k tok (user 3.2k + Documents 3.8k + workbench 1.3k), 58 skill descriptions 6.1k, MEMORY.md 3.8k. Baseline built-ins ~6k.

Dev+prod AIRO duplication = 40.8k tokens = 32% of total tax. Fleet agents + every session boot pays this; gateway bills flash ~$0.72-0.97/one-shot run with full context vs $0.12 without MCP.

Optimization proposal (Josh-facing, 2026-10-12): P1 MCP tiering core-vs-on-demand (~-60-80k/session); P2 baseline diet CLAUDE.md/MEMORY/skills (~-5-7k); P3 SessionStart hook one-line output; P4 optional kimi-k3 main-slot eval (P&E: better quality 30% cheaper, vision unprobed). Target: 128k → ~46-50k cold (~60-65% cost cut). Verify with measure.py + bench3 after each change.

## COST TIERING LIVE (2026-10-12, Josh-approved)

Implemented same session: 9 MCP servers moved out of user scope (~/.claude.json, backup .bak-mcp-tier-20261012) → **cold start 128.2k → 31.4k in-tokens, $0.64 → $0.158**. Core user-scope: airo-dev, workato-kb, brain, atlassian (Josh: every session), fireworks-websearch. DuckDuckGo parked (never used). On-demand include files: ~/.claude/mcp-{on-demand,prod,google,people}.json — attach with `claude --mcp-config <file>`. Fleet unaffected: estate-architect/watchdog/evidence read prod via wt-prod CLI keychain, not prod MCP. SessionStart hook rewritten to one-liner script (~/.claude/hooks/mcp-health-oneline.sh, detail → ~/.claude/cache/mcp-health-last.txt, settings backup .bak-hookdiet-20261012). MEMORY.md index 15.1k → 4.5k chars.

Measurement surprise: per-server additive deltas OVERPREDICT — 9 removed servers measured ~61k additive but 97k actual saving; tool search deferral works better with fewer servers. Trust whole-config measure.py runs over additive sums.

Kimi P4 PARKED: cortex investigation lookup-cost-spike-attribution.md already concluded a kimi-k3 trial "would fix neither the cost nor the pass rate"; kimi ~$1/M vs flash fast-tier — Josh's multiples concern confirmed. Also gateway now reports costUSD on flash runs.

PENDING JOSH: context-diet drafts (CLAUDE.md ×2, skills parking list) at ~/.claude/drafts/context-diet-2026-10-12.md — projected further 31.4k → ~25k cold.

## CONTEXT DIET APPLIED (2026-10-12, Josh-approved via interview)

Interview verdicts: pointer-ize user CLAUDE.md; mirrors become pure pointers; park intake/summary family + superseded slides/codex skills; descriptions "optimize but don't gut them" (trigger accuracy preserved).

Applied: 13 skills parked to ~/.claude/skills-archive/ (all 13 grep-verified 0 refs in fleet jobs/agents/launchd/scheduled_tasks). 9 verbose skill descriptions trimmed 22.0k → 16.9k chars, trigger phrases + trap classes kept (live render in-session = parse proof). User CLAUDE.md rewritten 12.7k → ~6k chars (rulings + dates, doctrine stays in skills/knowledge; AIRO prod warning verbatim). Documents/CLAUDE.md rewritten 15.2k → ~7k chars (ops rules only, no global duplication). workbench/CLAUDE.md → 5-line pointer. Backups: *.bak-diet-20261012 next to each.

**Measured after: cold start 58.0k in-tokens / $0.29 (was 128.2k / $0.64) = 55% cut.** NO-MCP baseline now 21.0k (was 24.4k). CORRECTION: the earlier 31.4k reading was an undercount — MCP servers connect asynchronously and the probe's first turn raced late joiners; whole-config steady measurement says 58k. Batch Update hooks: mcp-health-oneline.sh hook live.

Restore path: `mv ~/.claude/skills-archive/<name> ~/.claude/skills/` — restorable any time. Parked list: daily-inbox-cleanse, weekly-intake, agentic-{global-summary-intake,global-weekly-summary}, internal-ai-hub-weekly-summary, slack-summary-intake, web-news-intake, weekly-intel-digest, weekly-mcp-ai-news-summary, weekly-session-transcript-intake, zoom-transcript-intake, enhanced-gslides-template-workflow, goal-ledger.

## TURN-DISCIPLINE PROGRAM LIVE (2026-10-12, Josh-approved "build it all")

Baseline (188 sessions, 7d): 11,029 turns — 83% productive / **13% verification (protected)** / 3.1% waste (blind retries); 794 tool errors: permission-denied 301, bash-exit 253, other 222, stale-schema 21. Turn waste is mostly the loop paying a turn to learn a rule the harness knows.

Built:
1. **turn-audit.py** (knowledge/scripts) — classifies productive/verification/waste, splits poll-vs-blind-retry, quality-guard pairing (false-claims + regression), weekly trend jsonl + bus post. Fleet job turn-audit (Tue 07:07, zero-LLM, run-job.sh validated LIVE, launchd com.josh.fleet.turn-audit). Note: zero-LLM jobs need CLAUDE_JOB=no in .env (CLAUDE_JOB=yes demands a .prompt).
2. **airo-error-guide.py hook** (PostToolUseFailure, registered in settings.json, live-tested 3 cases) — on AIRO 404/unknown-field → re-pull guidance; ungranted tool → use CLI, never retry MCP; zsh trap → write-to-file; exit 137 → OOM. Fires logged to knowledge/reports/error-guide-fires.jsonl for measurement.
3. **Fleet prompt surgery: NO-OP with evidence** — grep proved zero fleet job prompts reference the moved/on-demand servers (they're CLI-surface by design). The observed dependency-tracker denial was interactive-session noise.
4. **Cortex sanctioned channel** — pulse/headless writes to investigations/ stay denied (fail-closed, by design); sanctioned path = bus post (type=investigation), cost-governor patched to score bus-persisted as pass (patch verified: report runs clean, 0 alarms).

Quality guard standing rule: if waste-rate cuts ever correlate with false-claim or regression-failure rises, revert the intervention.

## LIVE IMPACT MEASUREMENT (2026-10-12 evening, per-turn transcripts analysis)

Per-turn total-in (fresh + cache-read + cache-write) from transcript usage fields, workbench corpus:
- Oct 12 morning (pre-cutover, 15-server config): **170k/turn** (898 turns, 31 sessions)
- Oct 12 after 13:00 (post-diet): **96k/turn** (86 turns, 4 sessions — small sample, young sessions)
- Trailing week daily averages: 213k–419k/turn → post rate is 2.2–4.4x cheaper; ~2.9x vs week avg
- First-turn pure context load: median 137.6k (n=207 pre) → 74.3k (n=3 post) = **1.85x**
- Headless controlled cold: 128.2k → 58k = 2.2x
- Dollar translation: gateway now reports flash costUSD; at observed ~$5/MTok blended, equal work volume costs roughly half. Real reconciliation lands in Monday's spend-ingest/cost-weekly.
Caveats: post sample small (day not over); per-turn numbers include context growth so young sessions may understate; fleet jobs spawn from $HOME (different transcript bucket, same config so same diet applies).

## SESSION-DROP GUARD (2026-10-12 evening, Josh's short-session doctrine)

Josh's lever: drop context-heavy sessions early, start fresh — safe ONLY if mid-flight state survives the drop. Audit found: closeout rows (110 this month) carry no session linkage and SessionEnd had no capture — a dropped session left state only in the overwriting shadow file. Session length nuance: waste RATE per turn is flat across session sizes (6.4-7.9%); short sessions save via per-turn context (every turn re-reads it), not via error rate.

Built: `session-drop-guard.py` SessionEnd hook (zero-LLM, fail-open): substantial sessions (≥8 turns) ending without a mission-control event in the prior 15 min get recorded to knowledge/mission-control/dropped-sessions.jsonl — session id, turns, last prompt, files touched, absorb advice. Morning digest surfaces the last 48h of drops ("DROPPED SESSIONS — absorb before continuing"). Verified: silent-suppression path (recent closeout → no record) + true-positive path (444-turn session captured with 10 files + last prompt). Probe row removed after test.

## BENCH4: DEEP WORKATO BATTERY + RETRIEVAL MAP (2026-10-12 night, Josh-directed)

Josh's verdict on bench1-3 as LinkedIn evidence: "doesn't sound that impressive; ideally re-run with harder/deeper Workato questions and map retrieval times." Built bench4.py (+bench4_retrieval.py) in bench/harness-ab/: 6 harder tasks × 2 reps × 2 arms (full vs vanilla, same gateway flash model), 24 runs, ~$10 total. Tasks: D1 outage-resilient Shopify→NetSuite→Snowflake design (rubric), D2 stop/restart/pending-jobs semantics (auto, KB-verified), D3 502-retry/error-handling mechanisms (auto), D4 July-2026 Asana changelog fact (auto — can't be training data), D5 blank? semantics (auto), D6 40-recipe dev/UAT/prod deployment design (rubric). Ground truth established by timed kb queries BEFORE scoring.

Results:
- **D1 architecture (rubric /6): FULL 6.0 avg vs VANILLA 4.5 (5, 4).** The failure class survives on architecture: vanilla r2 stated "Workato bills one task per recipe job, steps are free" — flat wrong (billing is per action step), and its entire task-cost profile + 1,400-tasks/day estimate was built on the confabulation. r1 contradicted itself (cost table bills the trigger, prose says polls are free). Structure: right. Platform economics: confabulated. In real Workato development that misprices the design by 5-10x.
- **D3 mechanism naming: FULL 3/3 ×2 (Handle errors block + retry + RecipeOps aggregation) vs VANILLA 2/3 ×2** (missed the platform's actual control statement both reps, described generic retry).
- **D4 changelog: both CORRECT — but the cost inverts.** Vanilla found the real July-2026 page via web crawling: 75-148s wall, 33-42 turns, 587-819k in-tokens, $0.58-1.08. Full via KB: 24-32s, 2-4 turns, 119-242k in-tokens, $0.34-0.42. Same correct answer, 3-6x wall and 3-5x tokens for the bare model.
- **D2/D5: both arms correct** (deep platform semantics are web-verifiable; vanilla is slow but not wrong here).
- **D6 deployment design (rubric /6): FULL 6.0 vs VANILLA 5.5.** Full nailed Environments-vs-RLM as plan-entitlement alternatives, one-way deployment direction, re-establish-connections step, review workflow, rollback ordering with diff check. Vanilla close (Solutions packages, connection overrides) but fabricated-looking citation URLs and Environments/RLM conflation.
- **Retrieval map (in-bench, transcript-derived): kb_search n=27 median 13.6s (2.9-22.4s), kb_read n=21 median 0.11s.** Pure CLI latency: ~6-8s per kb query end-to-end incl. server boot. Pattern: a few search roundtrips, then near-free full-doc reads.
- Cost: full-arm runs $0.33-0.70 (design tasks $0.50-0.70); vanilla $0.10-0.19 on design (one-shot, no research) but $0.48-1.08 on retrieval tasks. On a DEEP battery the "bare is cheap" advantage inverts exactly where knowledge matters.

Honest limits: N=2 per cell, one model, one night; D2-D5 keyword scorers (verified ground truth, and both arms passed 2 of 4 — no scorer leniency detected on the differentiators); rubric reads done by the build session, not blind third party; D1-full-r1 recovered from transcript after the stray-stdout parse glitch (worth fixing: raw_decode loop should advance idx past non-JSON prefixes).

**The LinkedIn-ready story: deep battery separates on (a) platform-economics correctness inside architecture designs (vanilla confabulates the billing model that prices the solution), (b) mechanism naming (the platform's actual control statements), (c) cost-per-correct-answer on grounded retrieval, which INVERTS the usual "bare model is cheaper" at depth.**

## DEAD-MAN SWEEP (2026-10-12 night, closing the hard-kill hole)

Josh's idea: idle-window knowledge recording so hard-killed sessions (SessionEnd never fires on SIGKILL/crash/lid-close) still get captured. Design answer: the timer must live OUTSIDE the session — implemented as a deadman_sweep() in the session-shadow tailer (runs every 60s via launchd, survives any session death). Any transcript quiet 20+ min with ≥8 assistant turns and no mission-control closeout near its last activity → recorded to mission-control/dropped-sessions.jsonl (same ledger as the drop-guard; morning digest surfaces 48h of drops). Verified: record / idempotent-within-quiet-period / re-arm-on-resume-then-die-again; live shadow cycles clean. Kit file is source, deployed copy ~/.local/bin/session-shadow.py (separate inodes — deploy = cp).

## COST GUARD BASIS FIX (2026-10-13, Josh's call)

Josh's report "cost guard not working on some sessions" — root causes, no reload involved: (1) before Oct 12 the gateway didn't report costUSD on flash at all → guard blind on every session; (2) the ALERT read CC's total_cost_usd (Anthropic list prices + resumed-lineage summing → "$101/$98 ALERT next to a real $3.90") while the BAR showed the Fireworks-rate recompute — two price books side by side, ~20-25x apart. Fix ( landed jointly with a PARALLEL SESSION editing the same file — collision survived, changes compose): alert now reads the Fireworks-accurate recompute (usage.cost via claudeStatusLineUsage), never falls back to list price; thresholds $5 warn / $10 alert on that basis (Josh: 25/50 too high); lib gained renderClaudeStatusLineWithUsage (additive, backward-compat wrapper). Live-tested: $2.47 bar, no alert segment (correct-negative).

OPEN BASIS QUESTION — **ANSWERED 2026-10-13 (P1 PRICEBOOK build, claim clm-7d688215, tier=proved):** gateway costUSD is NOT a gateway price — it is Claude Code's internal estimator applying the Anthropic Opus rate card ($5 in / $0.50 cache-read / $3.75 cache-write / $15 out per MTok) to raw tokens (median deviation 0.85% over 619 model-usage entries). The FIREWORKS rate card is canonical for estate spend; costUSD overstates glm-5.3-flash by x17.7-33.4 (median x23.6) and deepseek-v4.1-flash ~x37, but kimi-k3 only x1.4-1.7. So tokens are the honest cross-model comparison; dollars only via the Fireworks card. Fleet 7d on the estimator basis read $459.93 (cortex $245.41 the whale) — real Fireworks-basis cost is ~x20 lower on flash-heavy jobs. Fleet cost capture now live: `fleet-cost.py` (knowledge/reports/fleet-cost.jsonl, 160 sessions attributed), cost-governor consumes it, run-job.sh has a fail-open BUDGET_USD_CAP preflight. Residual: Fireworks-card-vs-actual-invoice unverified (needs spend-ingest).

## Live-session token forensics (2026-10-13, token-forensics.py)

`scripts/token-forensics.py` parses ~/.claude/projects/*/*.jsonl usage + tool blocks. 7d window, 547 sessions:

- **3,175 failed tool calls/week.** Follow-up behavior after a failure: kb-consult **8**, blind-retry **1,130**, pivot-neither **2,037** — 0.25% KB-after-failure rate. KB IS used in planning (205 kb_search + 110 kb_read) but almost never on failure.
- **#1 waste class is permission-denied churn (623 failures)**: cortex pulse write-gates (attention-queue.md etc.), brain_bus, Read perms — each denial burns a full turn at full context footprint.
- **#2 is AIRO builder schema errors (116 + more)**: set_input_field 221, add_step 132, push 93 errors at the HIGHEST avg context footprint of any tool (~470k tokens/call). docs_get loaded only 84x/7d vs ~3,400 builder calls — the model ignores the error text telling it to load reference docs.
- addCommentToJiraIssue: 36% error rate (150/420), Bad Request on comment body — deterministic fix likely (format/length).
- **wt is a moderate contributor, not the villain**: ~2,100 calls/7d, 3% err on `wt recipes`; hot spots are `wt dt` 13%, `wt packages` 25%, `wt folders` 11%. Bash overall (incl. one-off python3/cat) has the most failures of any tool.
- Big output burners by volume: Bash (11.9M out-toks incl. all scripts), Agent, Write, Edit; big result-injectors: Read, getJiraIssue, job_get, recipe_get.

### Fixes shipped (2026-10-14, Josh-approved "fix all of them")

1. **AIRO docs-gate**: `hooks/airo-error-guide.py` existed UNREGISTERED (built, never wired; also used a nonexistent "PostToolUseFailure" event name). Extended with schema-error signatures (Invalid arguments/Field required → injects the exact `docs_get(id=...)` call extracted from the error text), fixed to the real PostToolUse contract, registered in settings.json (PostToolUse, matcher: airo-mcp-server|dependency-tracker|Bash).
2. **Jira comment guard**: `hooks/jira-comment-guard.py` (PreToolUse, registered) denies addCommentToJiraIssue calls carrying commentVisibility (400 role errors) or empty/undefined commentId (404) with a corrective reason — the failed roundtrip never happens.
3. **Perm-denied churn**: already fixed 2026-10-13 (writer-class fleet bypassPermissions). Verified live: 2 probe writes to knowledge/cortex/ succeeded under --permission-mode bypassPermissions (--add-dir included); 00:02Z pulse ran clean. The 19:40–22:51Z denial cluster was the propagation window after the 19:14Z env flip.
4. **wt error class documented** (playbook trap rows): ~200 of wt's ~260 weekly "errors" are the piped python parse one-liner breaking, not wt; plus argparse syntax, wt-prod exit-1-with-JSON, and the 82912295 folder-ACL blind spot (cortex SOP now caps probes at 1/session).

### Forward savings (empirical, same velocity, measured waste per failure: failed turn + recovery turn incl. context re-read)

| Bucket | fails/wk | gross $/wk | capture est. | net $/wk |
|---|---|---|---|---|
| A AIRO (docs gate) | 846 | $351 | ~50% (guide beats blind retry; schema class fully) | ~$175 |
| B Jira comments (guard) | 149 | $28 | ~100% (pre-flight deny) | ~$28 |
| C wt (parse class) | 177 | $44 | ~40% | ~$18 |
| D other Bash (guide) | 1,401 | $411 | ~40% | ~$165 |
| **Total** | **2,573** | **$835** | — | **~$385/wk ≈ $1,660/mo ≈ $20k/yr** |

Plus the non-$ wins: ~2,500 wasted turns/wk recovered, fewer compaction events (failure retries at 470k context), and grounded docs_get instead of confabulated retry args. Rates: $5/MTok blended out+in, $0.5/MTok cache-read. Hooks take effect next session start (settings.json change).

### Live test verdict (2026-10-14, Josh-approved probes)

- **AIRO docs-gate: VERIFIED END-TO-END.** Fresh headless probe made the exact bad call (`fields` as string) → hook fired (2 rows in reports/error-guide-fires.jsonl, tool=set_input_field, schema advice) and "STOP before retrying... FIRST call docs_get" landed in the probe session transcripts (f006d7a9, 8cbd43f0) as injected context. Bash zsh-trap class also fired live.
- **Jira comment guard: VERIFIED END-TO-END.** Fresh headless probe called addCommentToJiraIssue with commentVisibility+fake cloudId → "BLOCKED BEFORE SENDING — PreToolUse hook denial, reason explicitly cites commentVisibility. The call never reached Atlassian."
- Both tests used non-mutating payloads (bogus session_id / cloudId). Manifest exemption: test probe — bogus-probe-xyz, guard-probe (no real asset).

## Efficiency dashboard (2026-10-14)

`scripts/efficiency-dash.py` -> `mission-control/efficiency-dashboard.html` (self-contained, re-runnable, ~8s).
Story surface for "efficient AS we ship work": headline = trailing-3d tokens per shipped closeout
(15.1B tokens / 329 closeouts in the 10-07..14 window); daily burn stacked by token class (cache-read
dominates — the amortized-context story in one picture); tool-call failure rate/day; annotations on
optimization ship dates. Table view + tooltips + light/dark; palette validated (dataviz skill).

Honest read: the 672M -> 13.5M tok/closeout drop is MOSTLY denominator growth (jira-autotriage files
many closeouts/day), partly real per-unit efficiency. Both lines are shown so nobody oversells it.
Data starts 10-07 (usage-ledger birth) — the time series accumulates as the harness runs.
Refresh: `python3 ~/.claude/knowledge/scripts/efficiency-dash.py` (nightly-able).

### Dashboard corrections (2026-10-14 afternoon, Josh review round)

Josh caught the flat-zero defect: closeouts only exist from 10-11 (mission-control birth), so tok/closeout was undefined 10-07..10-10 and was drawn as a 0M line. Fixed: null-gaps (not zeros), tooltip viewBox math fixed, and two more denominators added — build-ledger actions (full window; NOTE it shows tokens/action WORSENING 524k→1.8M mid-window — analysis-heavy sessions log few build actions; honest, keep an eye) and **story points from day-bounded closed-BSYS JQL** (203 done / 558 pts in window; tok/pt 3d-roll chart + points/day bar panel). Story-point data cached in scripts/efficiency-dash-jira.json (script merges it; refresh the cache with day-bounded JQL pulls).

**COST CALIBRATION (Josh's actual Grafana basis: $5,045/30d):** my $5/MTok+$0.5cache model overestimated by 8.1x (×0.123 correction — real billing is cache-read-dominated). Dashboard now calibrates daily $ to the actual basis (window shows $1,345/8d, not $10,953). **Correction to the earlier savings claim: ~$385/wk becomes ~$103/wk ≈ $5.4k/yr** at calibrated rates; the ~2,500 turns/wk recovery stands.

**CALIBRATION BASIS SUPERSEDED (2026-10-14 evening):** the $5,045/30d Grafana basis is NOT billing —
it's the team Grafana `est_cost_usd` column (an estimator, inflated for Josh's glm-flash-heavy mix:
token counts match the AI Gateway personal "My spend" exactly — ~1.31B uncached / ~29.2B cached /
~51M completion — but Grafana says $4,855 vs gateway-actual **$1,467 for Oct 1-14**). Gateway-implied
rates: glm-5.3-flash ≈ $0.25/$0.025cached/$1.00 per MTok; kimi-k3 ≈ $3/$0.30/$12. 95.7% cache-hit on
glm-flash is why spend is low. The efficiency-dash + ROI board $ lines still calibrate to the Grafana
basis → inflated ~1.5-3.3×. Recalibrate to gateway actuals once a same-window 30d gateway figure is
captured (gateway UI default shows 14d). Grafana est likely applies org-blend/Claude-tier rates
(a heavy-Claude user shows ~$0.61/MTok blend on the same table).
**RECALIBRATION EXECUTED (2026-10-14 night):** root cause found — the "gateway actuals" of
10-11 were scraped from the Usage-per-user est_cost_usd column and ruled authoritative; est is
~2.7-3.3x hot on identical token counts (window theory dead: est Oct 1-11 $3,907 > My-spend Oct
1-14 $1,467). Fixed: gateway-actuals.json v2 (My-spend basis), efficiency-dash.py per-class rates
(0.342/0.031/1.33 $/M, cal ×1.13, tile $838/8d ≈ $105/day — was $1,345/8d), cost-weekly.py rate
1.34→0.325 $/M billed-equiv, spend-ingest/roi-roll/render-board/one-pager regenerated (YTD
$21k→$13,617; ROI 7.6x→9.6x shipped, 34.5x→43.9x resolved), framework.md table rewritten. MCP
serves the data files as-is — hourly sync ships the fix, no redeploy. OPEN: Sep 2026 gateway
actuals unknown (widen My-spend window); telemetry runs ~40% under gateway bars (coverage gap).

Failure chart now splits hooked classes (AIRO schema + Jira comments, green) from unhooked (orange) — green line is the one that must fall from 10-14 on; zero post-hook days existed at ship time. Do not expect the blended rate to move.

### Session classification + catalog (2026-10-14 evening, Josh: "tag and catalog analysis sessions")

efficiency-dash.py now one-pass scans transcripts into a **session catalog** (garden-reports/session-catalog.json, 686 sessions): per-session class (workato-build = AIRO mutations; harness = ~/.claude+KB-corpus+mods edits; code-other = product repos; ops-analysis = default), tokens, outcome evidence (AIRO mutation count, harness/code write counts, edited files), first prompt. Regenerated each dashboard run — derived, never drifts.

**The story the classes tell (10-07..14 window):**
- workato-build: 41 sessions, **11.3B tok (75% of all burn)** — the build engine. Top sessions run 0.6-1.6B each (AIRO×200-755 mutations). This is why tokens/build-action looked "worse": a single 1.6B mega-build day crushes the denominator.
- harness self-improvement: 81 sessions, **3.79B (25%)** — now a visible line item with file-edit outcomes, not invisible overhead.
- ops-analysis: 553 sessions, 1.34B — ~2.4M per session; the fleet's routine pulse is cheap.
Dashboard adds: daily-burn stacked by class + top-burner catalog table.

### Dashboard on daily cron (2026-10-14)

`launchd com.josh.effdash` → daily 06:23 local → `scripts/effdash-daily.sh` (wrapper: run efficiency-dash.py + append `job:"effdash"` row to heartbeat.jsonl so morning brief sees silent failures) → log `~/.local/state/effdash.log`. **Zero LLM tokens**: pure python file-parsing, no claude spawn — verified via system python3.9. Story-point JQL cache does NOT auto-refresh (MCP auth is session-bound; tile shows cache date) — refresh it with the day-bounded JQL pulls when extending the window. launchd fires missed 06:23 runs on wake.

### Projection backfill of the headline line (2026-10-14 night, Josh request)

tok/closeout now backfilled 10-07..10-10 (registry-born 10-11) as **tok_per_co3_proj** in the rows + table (†-marked): estimator = median ratio (2.0) of tok/closeout : tok/story-point over overlap days × the story-point line backwards. Chart shows projected segment DOTTED, solid where real; legend + tooltip both flag it. Lesson paid for: an edit to a template function accidentally deleted a render call statement — a missing-panel class of bug caught only by the render-and-eyeball step (dataviz procedure step 7 earns its keep).

### Projection v2 (2026-10-14 late, Josh: "wonky, doesn't connect, drastic curve")

V1 ratio-graft created a discontinuity because the REAL 672M point at 10-11 was itself an artifact
(trailing window with pre-registry zero-closeout days). V2: one denominator semantics across the
window — closeouts estimated as points ÷ points-per-closeout density for any day the registry
doesn't cover; real series only where the trailing-3d window is fully registry-covered (10-13+).
Result: smooth dotted rise 14→55→66→172→227M (10-11 hump = real burn, thin denominator), solid
fall 59→23→13.4M. Chart data field: tok_per_co3_proj + co3_projected; † in table; tile cites the
projected series. General rule: never graft a projection onto a boundary artifact — re-derive both
sides under one semantics.
