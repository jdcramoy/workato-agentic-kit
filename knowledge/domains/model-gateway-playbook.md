# Model gateway playbook (multi-model harness on Workato AI gateway)

Source: #ai-pe-coding-agentic-models (C0BJFG4Q0QK, 144 members, Alexey's team) full-history
sweep 2026-10-10 + live `/v1/models` pull + the pinned PoC guide + the P&E eval sheet.
This file is the operating playbook for routing Josh's agent fleet across gateway models.

## The gateway

- Base: `https://ai.preview.workato.com` — `/v1` (OpenAI protocol), `/anthropic` (Anthropic
  protocol, what Claude Code uses). Key = `ANTHROPIC_AUTH_TOKEN` in `~/.claude/settings.json`.
- `/v1/models` returns ~326 IDs but most are 5x internal replica copies (azure_internal_01-05,
  bedrock_internal_01-05, mantle_internal_01-05). Distinct usable families:
  - OSS on 3 providers: fireworks/{kimi-k3, kimi-k3-fast, glm-5.3, glm-5.3-fast, glm-5.3-flash,
    deepseek-v4.1-flash, minimax-m3, qwen3.8-max}; baseten/{kimi-k3, glm-5.2(-fast), glm-5.3(-fast,
    -flash), deepseek-v4-flash, deepseek-v4-pro, deepseek-v4.1-flash}; nebius/{kimi-k3, glm-5.2,
    deepseek-v4-pro, minimax-m3} (Nebius slow, no cache discount).
  - Frontier: azure_internal_*/ and bedrock_internal_*/ (Claude 4.5-5.5 lines, Fable-5, GPT 4.1-6.x),
    vertex_global/gemini-3.6|3.8-flash, openai_direct/gpt-6-luna.
- `rr/` prefix = round-robin frontend over baseten+fireworks. Unstable throughput (160 vs 31 tps
  swings). NEVER use rr/ for benchmarks; prefer explicit provider-prefixed IDs.
- Ops roadmap (Alexey, late Sep): model-router pass-through mode → enable expensive OAI/Anthropic
  models per team → team budgets → config distribution → burn dashboards. `/model router` not GA.
- Pricing endpoint doesn't exist yet (asked in channel); Grafana: grafana.infra.wktodev.net/d/dmcfjsb.

## Evidence-based model verdicts (P&E sheet, 88 scored runs + channel consensus)

- **kimi-k3** — best OSS flagship, "solid replacement for Opus" for review/investigation
  (score 7.5-9.6 on review tasks); weak on heavy multi-file feature work; forgets past ~300k
  context — keep context below that. Expensive under CC without caching (93% cache hit → ~$1/M).
  Baseten serving has highest throughput; fireworks slower.
- **deepseek-v4-pro** — best cost-efficiency measured ($0.021/score-point vs kimi $0.38);
  collapses on large multi-file features ("already done / infeasible" ~400s).
- **deepseek-v4-flash / v4.1-flash** — ultra-cheap fast tier (386 req = $0.85); haiku-slot material.
- **glm-5.3-flash** — dominated: kimi beats quality at 30% less cost; "very slow" reports.
- **glm-5.2** — Fireworks' own "best cost/perf for sustained coding" rec, but poor on P&E sheet (2.67).
- **qwen3.8-max** — do not recommend (0.00 avg on OMP; "не рекомендую" from ops).
- **GPT-5.6 Luna** — best code-review value ($0.16/run, 7.5); **reasoning effort matters more than
  model size** (max 67% vs low/medium 20% on their benchmark).
- **MiniMax M3** — fastest drafter, shallow; **Gemini 3.8 Flash** — mid; **Haiku 4.5/Sonnet 5 via
  gateway** — poor scores, rate-limit-prone.
- Provider ranking (guide): Fireworks primary, Baseten second, Nebius last.

## Josh's rulings

- **Sonnet slot STAYS glm-5.3-flash** (Josh, 2026-10-10): deepseek-v4-pro has no image vision
  (gateway 400 "does not support image inputs") — dealbreaker for his workflow. Do not re-propose
  deepseek-v4-pro for any slot Josh needs vision in.

## Harness configuration (proven env block, from gateway ops)

```
ANTHROPIC_BASE_URL: https://ai.preview.workato.com/anthropic
ANTHROPIC_AUTH_TOKEN: (Josh's key, already set)
ANTHROPIC_DEFAULT_OPUS_MODEL:    <strong model>   # currently fireworks/kimi-k3
ANTHROPIC_DEFAULT_SONNET_MODEL:  <worker model>   # currently fireworks/glm-5.3-flash
ANTHROPIC_DEFAULT_HAIKU_MODEL:   <cheap model>    # currently glm-5.3-flash; evidence says deepseek-v4.1-flash
ANTHROPIC_DEFAULT_FABLE_MODEL:   <strong model>
CLAUDE_CODE_BG_CLASSIFIER_MODEL: <cheap model>
CLAUDE_CODE_MAX_CONTEXT_TOKENS: "1048544"  CLAUDE_CODE_AUTO_COMPACT_WINDOW: "1048544"
CLAUDE_CODE_MAX_OUTPUT_TOKENS: "32768"
API_TIMEOUT_MS: "600000"  BASH_DEFAULT_TIMEOUT_MS: "1800000"  BASH_MAX_TIMEOUT_MS: "7200000"
```
The Agent tool's model aliases (opus/sonnet/haiku/fable) resolve through these env slots —
this IS the per-swarm routing mechanism, already live. Agent definitions can pin their own
model in frontmatter.

## Multi-model coupling patterns (channel-tested)

- **Fusion** (openrouter.ai/openrouter/fusion pattern): N models run the same task alone,
  answers cross-checked → consistently lower hallucination, better fact-checking; slower + costlier.
- **Advisory mode** (ops' term): two models observing each other — untested by the channel; our
  dissenter/verify agents are structurally this; make them different models.
- Split patterns: strong planner + cheap worker; cheap drafter + strong reviewer. Generator-critic
  on different providers also diversifies outage risk.

## Fleet gotchas (hard-won)

- Per-key concurrency limit ~30-40 parallel requests — a large swarm fanning out simultaneously can
  trip it; spread agents across providers/models and stagger bursts.
- Open-weight models degrade/stop on long contexts (500k+); unexpected abrupt turn-ends reported.
- 429s after 7-17 min continuous runs; fireworks/kimi-k3 occasional 504/503; deepseek-v4-pro takes
  no image inputs. Capability metadata (thinking flags) not always forwarded.
- No audit logs; per-token attribution approximate — use Grafana, budget ~$800/mo default with
  soft/hard caps coming.

## Bench script (BUILT 2026-10-10, live-smoked)

`~/.claude/knowledge/scripts/model-bench.py` — POSTs streaming probes to /v1/chat/completions
per model, records pass/fail + tokens + ttft/wall/tps to `knowledge/models-evals/bench.jsonl`.
`--list` dumps the model roster; `--vision-probe` tests image support with a 1px PNG;
`--probes fixtures` runs the canon regression fixtures as eval tasks (see below).
First live smoke (1 run, 2 probes): kimi-k3 passed both with cache hits visible
(cached_tokens>0 — provider caching confirmed via OpenAI-protocol path too); deepseek-v4.1-flash
passed reasoning, exhausted max_tokens on code (verbose — same model hit the 2048 cap once
in fixture mode; verbose-on-code is a real trait of it).

**Fixtures mode (WIRED 2026-10-10):** each usable fixture (non-empty input + expect) from
`knowledge/fixtures/` becomes a behavior contract — the model writes a Ruby `transform` lambda
for the input, the judge executes it locally and applies wt's exact expect ops
(present/absent/eq/ne/contains/gt/lt + dotted-path). Grows automatically as testcase-authoring
canonizes more bugs. Judge gotchas paid for: (1) `INPUT = {json}` in Ruby is a SYMBOL-key hash
literal — models read string keys, so serialize via `JSON.parse('...')` or every eq silently
fails; (2) locals defined inside `eval` aren't visible to enclosing compiled code — call through
the binding (`b.local_variable_get(:transform)`). Currently 1 usable fixture (82921718, echo
demo — low difficulty; the two real fixtures 78677477/82794233 have empty input/expect stubs).
Post-fix smoke: deepseek-v4.1-flash and kimi-k3 both pass 3/3 checks.

**Vision matrix (live-probed 2026-10-10):** deepseek-v4.1-flash = YES (answered a 1px PNG
correctly); kimi-k3 (fireworks + baseten) = accepts image input; **deepseek-v4-pro = NO**
(HTTP 400 "does not support multimodal" on baseten, "model mapping not found" on fireworks —
the fireworks/ listing is stale for it; only baseten/deepseek-v4-pro routes). Only v4-pro is
vision-less; haiku/classifier slots could move to deepseek-v4.1-flash for cost if Josh wants.

## Phase 3 DONE (2026-10-10): role-routed agent fleet

Custom full gateway model IDs in agent frontmatter `model:` CONFIRMED working (headless probe:
`query_source: agent:custom:pin-probe` — the "unrecognized_model" client warning is cosmetic,
the request routes through the gateway fine). Pins applied to ~/.claude/agents/*.md:

- evidence → `fireworks/deepseek-v4.1-flash` (haiku-class claim hunter)
- workato-watchdog → `baseten/deepseek-v4-pro` (investigator/autopsies; text-only so the vision
  gap is safe; baseten because fireworks mapping is broken)
- dissenter → `baseten/kimi-k3` (strong adversarial reviewer)
- spec-distiller → `fireworks/kimi-k3` (strong planner)
- cortex, brain-gardener, dreamers, estate-architect, promotion-orchestrator → inherit (main model)

Spread = provider diversity (2 fireworks + 2 baseten) per the ~30-40 per-key concurrency limit.
Agent registry snapshots at session start → pins take effect NEXT session.
Phase 4 advisory coupling achieved structurally: the dissenter now runs a DIFFERENT model
(kimi via baseten) than the work it reviews (main = glm-5.3-flash). Fusion-style cross-checks
available on demand: spawn the same task to agents pinned on different models and diff.

## Phase 4 invocation policy (Josh ruling 2026-10-10: SURGICAL, never default)

Phase 4 costs nothing at rest — the pinned agents only run when their normal triggers fire,
and Fusion is spawn-on-demand with nothing automatic behind it. Still, the decision framework:

- **DEFAULT = single model.** Role-routed pins (Phase 3) already give most of the win. No
  fusion, no extra passes, on routine work.
- **Advisory mode (dissenter/verify on a different model) fires when:** a proposal gates a
  build (dreamer→dissenter is already mandatory), a fix touches production/UAT, a claim is
  load-bearing for a "done", or evidence conflicts. Already structural — no new spend.
- **Fusion (N models, same task, diff answers) ONLY when ALL of:** (1) the task is
  hard-to-reverse or prod-facing, (2) a wrong answer costs more than ~$5 of tokens (fusion
  costs N×), (3) the failure mode is subtle — plausible-but-wrong output, not an error.
  Typical: prod hotfix plans, recipe logic with financial side effects, security-sensitive
  changes, Jira plans Josh will approve a build from.
- **Never fusion for:** investigations, searches, drafts, routine dev, anything cheap to redo.

**Fusion tooling (BUILT + live-smoked 2026-10-10):** skill `~/.claude/skills/fusion/SKILL.md`
(carries this gate + judging rules) + script `~/.claude/knowledge/scripts/fusion-run.py`
(Mode A: same prompt to N models via /v1, ledger to models-evals/fusion.jsonl, pairwise
similarity — heuristic only). Mode B = parallel Agent spawns with different `model` values
for tool-needing tasks; disjoint/read-only file ownership, never same-file writes.
Smoke demo: both panelists independently caught a NaN fail-open bug in a billing-debit
condition change. Panel lessons: thinking models (glm) emit reasoning_content BEFORE
content — give --max-tokens >= 1500 or the answer is empty (script detects and says so);
kimi narrates its thinking inline in content at moderate budgets (answer still present).

## Why kimi-k3 from TWO providers (design note)

Provider diversity ≠ model diversity (same weights = correlated blind spots — model-level
diversity is why dissenter=kimi vs main=glm matters more). Provider spread buys three things:
(1) failure-domain separation — the channel measured fireworks/kimi-k3 slow (31 tps) and
504/503-prone while baseten stayed fast, so one provider's bad day can't take down both
pinned agents; (2) serving-stack differences (quantization, spec-decoding config) mean the
"same" model can differ in quality/behavior per provider — rr/ kimi felt degraded vs fireworks/
in one report; (3) throughput matching — baseten measured consistently higher tok/s for kimi,
so the bursty reviewer (dissenter) sits there while the planner (spec-distiller) holds fireworks.

## Our benchmark loop (adapting their PoC methodology)

Their method: frozen prompts (hash-recorded), real tasks pinned to pre-fix commits, judged by
behavioral tests, 1-10 score vs Claude Code baseline, >=3 runs, cost + TPS captured.
Ours: reuse regression fixtures (canon) + wt fixture runs as eval tasks; a bench script hits
/v1/chat/completions per model for TPS/cost; results appended to a models-eval ledger; nightly
optional. Evals to steal: github.com/workato/workbench-evals, github.com/workato-devops/testing-harness-and-models,
github.com/swe-bench/SWE-bench, artificialanalysis.ai/evaluations/terminalbench-v4-0.
Key resources: guide doc https://docs.google.com/document/d/1epMKXigphAM4XdeNBqPGB9ragL7R_rZabwksaq9k0Zc
· eval sheet https://docs.google.com/spreadsheets/d/1VRcugJRkVjIH2YQbKYLyPqautYqsHqx7sjD1EHJWeRM
· config builder https://ideal-adventure-2yrl8kw.pages.github.io/ai-gateway-preview/
· ops wiki https://workato.atlassian.net/wiki/spaces/PEAI/pages/2785968260

## Session-cost watcher (2026-10-13, LIVE)

- claude-statusline.mjs (in .fireconnect setup-cli/bin) now fires cost alerts:
  reads cost.total_cost_usd from the statusline payload each render; FIRST
  crossing per session of $25 (WARN) / $50 (ALERT) -> macOS notification +
  ~/.claude/cost-alerts.log + per-session state ~/.claude/cost-alerts/<sid>.json
  (fired-thresholds array; no spam). Fast/local, never blocks the render.
- LIVE-PROVEN on first render: the real statusline payload reported THIS
  session at $959.08 (the $68 Josh saw was a different counter) — both
  thresholds fired. Statusline cost = total_cost_usd from CC's statusline
  stdin JSON (authoritative per-session).

## OFFICIAL RATE CARD (Josh 2026-10-13 — use these, not estimates)

Sources: app.fireworks.ai/models + baseten.co/library/<slug>/ (fetched live 2026-10-13; USD per 1M tokens, in / cache-hit / out):

| model | provider | input | cache-hit | output |
|---|---|---|---|---|
| glm-5.3-flash | fireworks | 0.15 | 0.03 | 0.50 |
| glm-5.3-flash | baseten | 0.15 | 0.03 | 0.50 |
| glm-5.3 | fireworks | 1.40 | 0.26 | 4.40 |
| glm-5.3 | baseten | 1.40 | 0.14 | 4.40 |
| kimi-k3 | fireworks | 3.00 | 0.30 | 15.00 |
| kimi-k3 | baseten | 3.00 | 0.30 | 15.00 |
| deepseek-v4-pro(-0813) | fireworks | 1.32 | 0.044 | 3.96 |
| deepseek-v4-pro(-0813) | baseten | 1.32 | 0.132 | 3.96 |
| deepseek-v4-flash-0731 | fireworks | 0.22 | 0.007 | 0.66 |

- The fireconnect statusline's FIREWORKS_MODEL_SPECS table VERIFIED against the live models page — zero drift (it also auto-refreshes from the serverless catalog hourly).
- Baseten refs now price from an official BASETEN_PRICING table in usage/pricing.mjs (basetenPriceFor checked before fireworks fallback) — the deltas that made it matter: deepseek cache-hit 0.132 vs 0.044 (3x), glm-5.3 cache-hit 0.14 vs 0.26. Live-probed 4 paths.
- Recalibration note: kimi-k3's real blended cost at 93% cache hit ≈ 0.07×3.00 + 0.93×0.30 = $0.49/M prompt tokens + output at $15/M — the old "~$1/M" estimate was output-heavy; kimi OUTPUT is 5x glm's — batch/governance output economy matters more than prompt economy on kimi.
