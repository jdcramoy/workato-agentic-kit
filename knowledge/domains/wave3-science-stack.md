# Wave-3 science stack — physics × evolution build (2026-10-11)

Fusion panel (deepseek-v4-pro + glm-5.3-flash + kimi-signal + adjudicator) → 11
proposals → dissenter pass (10 MATERIAL amendments, 1 clean) → 4-builder swarm (A
epistemics / B evolution / C attention / D knowledge-config, contracts in
scripts/wave3/CONTRACTS.md — zero collisions) → all built + live-verified + integrated
same session. Design canon: reviews/harness-wave3-science-2026-10-11.md; dissent:
reviews/wave3-dissenter-2026-10-11.md; amendments: reviews/wave3-amendments-2026-10-11.md.

## What exists (all stdlib, JSONL, atomic via atomic_io)

- **null-miner.py** (trials-factor): dream-mine enumeration over session-intact
  day-swap permutations → dreams/calibration/permutation-null.jsonl. LIVE FINDING: the
  dreamer's real best pattern sits WITHIN the permutation null (observed 1617/1962 vs
  p95 1862/2099 on two runs) — the confabulation class was real, now it's measurable.
  Per-session counts are permutation-invariant → one content pass + cheap merges.
- **fdt-gate.py**: improvement-claim record format + CLI; σ = MAD×1.4826; verdicts
  confirmed/within_noise_floor/refuted/insufficient_data; wired to predictions-hitrate
  (heartbeat series ages in). Retroactive proof was CONSOLE-ONLY at build time (audit
  correction 2026-10-12: no verdict row persisted — the CLI printed it; a real
  recorded verdict needs a --record run).
- **fusion-policy.py**: static same-family ban (fireworks+kimi = one family, the
  kimi-incident class), advisory-only (never refuses a Josh-requested fusion), κ math
  gated at ≥30 labeled joints; --kappa-table from fusion.jsonl.
- **trigger.py** (LHC L0): config-driven globs over fleet JSONL, 4 signature classes,
  prescale menu versioned per-row, express line (prod/P0 never prescaled), count-floor
  minimum-bias (≥10/day or whole stream bypasses + random top-up), novel stream
  (events/novel-stream.jsonl, cap 50/run). First run: 1194 unknown-error raw → n=332
  sampled → 4776 unfolded; 50 novel events banked.
- **coincidence.py** (multimessenger, READ-ONLY): cadence-aware windows
  (max(10min, 1.5×per-channel interval) — fixed ±10min was dead: measured watchdog
  interval 113.1 min), union-find collapse so shared-upstream channels count once,
  reuses gossip-read.py imports; registry dreams/bus/channels-registry.jsonl
  (24 channels, measured intervals). Time-to-confirm median 543 min.
- **patch-genome.py + ratchet-watch.py**: lineage ledger (schema-gated, backfill
  mode) + stateless ratchet counter over 3 real outcome surfaces; trip = exit 3.
  instruction-patch.py now mirrors every apply into the genome (non-fatal).
- **elites.py** (MAP-Elites): 168-cell archive (failure-class × loop × blast-radius),
  fitness = benchmarkable only (runtime/assertions/coverage), P(accept) BANNED twice
  (argparse + payload linter), replay-gym pass = binary floor, `augment` regenerates
  the dreamer's prompt-augmentation (empty cells + 3 distant champions).
- **affinity-mature.py** (instruments only, loop = wave 4): claim slot-parser
  (live: 15/15 claims are prose — flagged, honest), grep usage counter (clm-001 = 19
  files = top maturation priority), negative-fixture registry seeded with 4 REAL
  class negatives.
- **pleiotropy.py**: reuses synaptic-strength.py's graph + extends it; degree→rung
  policy; interface-stability exemption (atomic_io.py class); prompt-embedded =
  maximal. Live: 141 items → 103 josh-gate / 25 propose / 13 auto-safe.
- **rg-coarsen.py** (cryptic-variation bank): decision-relevance scoring off the
  synaptic join, dry-run report only; bank copies to knowledge/archive/<stem>/ with
  `micro: ...@<sha>` pointers; regret tuner floored at 5 events.
- **spore-router.py + config/spores.json** (SHADOW ONLY): returns-series schema +
  ε=0.10 per-class config + geometric-mean divergence detector; cost-governor
  UNTOUCHED (3-patch note: logging → ε-reserve Josh-gated → objective LAST).

## Integration (2026-10-11 night)

- fusion-run.py: prompt_sha switched to sha256[:16] — **builtin hash() is
  process-randomized, every pre-wave3 prompt_sha row was unjoinable** (integration
  find); + `--label-outcome <json>` one-shot labeling CLI (patch-note's env-file
  design couldn't work: judgment happens after the run in a different process).
  Labeled rows land via the CLI after fusion answers are judged.
- brain-mcp search scope + `archive/*/*.md` — bank is findable next session.
- harness-dreamer.md §Wave-3 wiring: read prompt-augmentation.md, mine the novel
  stream first for empty cells, per-pattern survived-the-null line mandatory.
- instruction-patch.py: genome mirror on every apply (best-effort, non-fatal).
- **Fleet job** com.josh.fleet.wave3-nightly (05:07 daily; Sundays + null-miner
  --permute 30, pleiotropy, elites augment); job script
  config/fleet/jobs/wave3-nightly.sh; appends its own spore shadow row
  (models-evals/spore-returns.jsonl, dominant-only until ε-routing is Josh-gated).
  First fire was a MANUAL run 2026-10-12T01:51Z incl. Sunday passes (audit
  correction: not a scheduled fire — the 05:07 launchd fire is still upcoming).
  **Audit fix 2026-10-12**: the spore row was a silent no-op (hasattr guard on a
  nonexistent function + tilde-form config path writing into a literal "~" dir);
  fixed to atomic_append_validated + expanduser, verified the row lands at the real
  path. Caught by all 3 fusion auditors independently.

## Deferred (Josh-gated, on purpose)

- rg-coarsen apply-mode (real domain-file moves) — dry-run only until Josh says bank
  cadence.
- Spore ε-reserve enforcement (patch 2) + cost-governor objective (patch 3) — need
  ≥1 week of real returns series.
- Affinity-maturation mutation loop (wave 4) — needs structured claims + negative
  fixtures to mature against.
- κ enforcement above 30 labeled joints + fusion claims carrying N_eff weight.
- L1/L2 trigger levels (cheap-model + full dreamer on L0 survivors).
- Ratchet recombination passes — needs a clause→oracle registry that doesn't exist.
