# Wave-3 build contracts — HARD file ownership (2026-10-11)

Pattern proven in wave-1 (scripts/frontier/CONTRACTS.md): shared schema conventions +
hard disjoint-ownership blocks + one builder per group = zero collisions.

## Global rules (all builders)

- Python stdlib ONLY. JSONL append-only ledgers. Reuse `scripts/atomic_io.py` via
  import (read-only import; never edit it). Atomic writes for any whole-file write.
- Every script: `--help` works, exit 0 on success, non-zero + clear stderr on failure,
  and a self-test mode (`--selftest`) using synthetic data.
- LIVE-VERIFY on real data before reporting done — cite the command and the output
  line. No claim without a citation.
- READ-ONLY on everything not in your owned list. If you need a change outside your
  block, note it in your report for the integrator — do not make it.
- Zero-LLM by default; where an LLM call is unavoidable (none should be in wave 3),
  stub it and note it.

## Agent A — "epistemics" (trials-factor, fdt-gate, fusion-neff)

OWNS (write):
- `knowledge/scripts/null-miner.py`
- `knowledge/dreams/calibration/` (new dir + permutation-null.jsonl)
- `knowledge/scripts/fdt-gate.py`
- `knowledge/scripts/fusion-policy.py`
- `knowledge/models-evals/kappa-table.jsonl` (new file only; existing fusion.jsonl
  READ-ONLY)
FORBIDDEN: `scripts/frontier/`, `scripts/wave3/` (other agents' files), any plist.

## Agent B — "evolution" (ratchet-recombination, qd-archive, affinity-maturation)

OWNS (write):
- `knowledge/scripts/patch-genome.py` + `knowledge/patches/patch-genome.jsonl`
- `knowledge/scripts/ratchet-watch.py`
- `knowledge/scripts/elites.py` + `knowledge/dreams/elites/` (elites.jsonl)
- `knowledge/scripts/affinity-mature.py` + `knowledge/claims/maturations/` (new dir)
FORBIDDEN: editing the dreamer agent file or any prompt — produce the prompt-
augmentation text as a file (`knowledge/dreams/elites/prompt-augmentation.md`) for the
integrator to wire.

## Agent C — "attention" (trigger-hierarchy, coincidence-bus)

OWNS (write):
- `knowledge/scripts/trigger.py` + `knowledge/config/trigger/` (prescales.json, menu)
- `knowledge/events/` (novel-stream.jsonl, trigger-log.jsonl)
- `knowledge/scripts/coincidence.py`
- `knowledge/bus/channels-registry.jsonl` (new file; existing bus maildirs READ-ONLY)
FORBIDDEN: editing `gossip-read.py` — emit a patch note instead.

## Agent D — "knowledge/config" (pleiotropy, cryptic-variation-bank, spore-portfolio)

OWNS (write):
- `knowledge/scripts/pleiotropy.py` + `knowledge/reports/pleiotropy/` (graph output)
- `knowledge/scripts/rg-coarsen.py` + `knowledge/archive/` (the bank)
- `knowledge/scripts/spore-router.py` + `knowledge/config/spores.json`
  (cost-governor.py itself is READ-ONLY — emit the integration patch note for the
  integrator)
FORBIDDEN: editing any domain file in the knowledge tree — the bank COPIES, never
moves; coarse-graining runs in dry-run report mode only on first build.

## Integrator (main session, after all agents land)

- Plists: one `com.josh.fleet.wave3-nightly` (+ weekly) job wiring: null-miner
  (monthly), ratchet-watch, coincidence, pleiotropy (weekly), fdt-gate (hook into
  value-ledger derive), trigger L0.
- Prompt wiring: dreamer augmentation text, κ>0.5 panel invariant into fusion docs.
- cost-governor ε patch note application.
- proposal-decide.py `build` statuses + mission-control closeout + knowledge deposit.
