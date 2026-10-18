# Frontier stack — the 10-idea build (2026-10-11)

Fusion-panel design (kimi-k3 + glm-5.3-flash + main), built same day by 6 parallel
agents with disjoint ownership contracts (scripts/frontier/CONTRACTS.md — the
pattern that made 6 agents not collide: shared schema file + hard path blocks).

## What exists (all zero-LLM python, stdlib only, JSONL append-only)
- Estate Twin: scripts/twin-snapshot.py + twin-query.py → knowledge/twin/v1/
  (recipes/connections/schedulers + meta.json written LAST so the twin is atomic;
  deps derived from recipe DSL providers joined to connections — the list API does
  not carry connection refs; prod guarded by --confirm; staleness gate 24h)
- Integrity Mesh: claim-submit.py (receipt schema, tier proved|asserted, backfill
  of legacy claims/ — 15 orphans caught day one) + reconcile.py (orphan/ghost/
  unfetchable; Jira needs --jira-status-cache until a token path exists)
- Denominator Oracle: coverage.py (declare/report; "green" = coverage >= 0.95)
- Calibration: prediction-submit.py + brier-resolve.py (resolver grammar
  wt-health:recipe=<id>:expect=...; append-only resolution lines joined on id;
  Brier per agent; first table: watchdog n=3 mean 0.127 vs coin-flip 0.25)
- Precursor Radar: z>2 over trailing-90d sweeps, requires >=14 distinct days of
  history before alarming (honest INSUFFICIENT until then)
- Saga: saga.py (hash-chained journals, genesis fingerprint, tamper detection,
  WORLD CHANGED guard) — knowledge/sagas/
- Standing Orders: standing-orders.py (policy match/draft/add — match-only, never
  executes; ratchet auto-expires on breach) — knowledge/policies/; the 3 draft
  policies were printed to stdout only, never persisted to disk (no policy files
  exist; recoverability from session logs unconfirmed — corrected 2026-10-12
  after audit caught the overclaim)
- Skill League: skill-fitness.py (backfill from session transcripts — cheap
  prefilter '"Skill"' then parse; quarantine flag only when applied-ratio < 1.0)
- Chaos Canary: chaos-canary.py (twin-local fault injection + detection scoring)
- Shadow Estate: shadow-estate.py (read-only counterfactuals on deferred
  decisions → regret ledger; 21 yes / 0 no / 19 stale on first run)

## Nightly driver
com.josh.fleet.frontier-nightly.plist (04:43): twin → brier → radar → skill
fitness. Zero-LLM (no claude spawn). Canonical script in
knowledge/config/fleet/jobs/frontier-nightly.sh; log
~/.local/state/fleet/frontier-nightly.log.

## Lessons
- Parallel build with a shared CONTRACTS.md + hard disjoint-ownership blocks:
  6 agents, zero collisions, each shipped live-verified the same session.
- fusion-run.py now saves full answers to models-evals/answers/ (the [:4000]
  print cap was silently discarding panelist tails; never pipe fusion output
  through `tail`).
- call-recipe pattern: shell out to `wt api` (keychain auth) beats reimplementing
  gateway auth per script.
- Backfilled same-day predictions need forward-scoped windows ("recurs within N
  days" counted from submit moment), else they resolve on pre-submit history.
- coverage.py found the build ledger only 90% actionable-attributed; reconciler
  found 15/16 legacy claims unproved — both real integrity findings on day one.

## Chaos Canary (added last, 2026-10-11)
chaos-canary.py: inject (twin-copy + mutation, ground truth in scenario.json) /
detect (baseline-diff reference detector + honest real-surface scan) / report.
First runs: 3/3 faults detected (connection_failure on a 99-recipe fanout,
25-scheduler stall, recipe hash corruption), est. latency = one sweep cycle
(3632s). KEY TECHNIQUE — frozen baseline: the twin's nightly refresh races any
concurrent diff reader; scenarios freeze a pristine baseline/ copy at inject
time and verify its hashes. Schedulers live only in schedulers.jsonl (764 ids
not in recipes.jsonl) — stall detection must use the scheduler roster.
Next step: wire canary signals into the real watchdog sweep for end-to-end
latency measurement.
