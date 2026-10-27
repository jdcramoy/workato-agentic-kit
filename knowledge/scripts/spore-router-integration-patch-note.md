# Integration patch note — spore-portfolio (wave-3, amendment #9)

Builder D, 2026-10-11. FOR THE INTEGRATOR — nothing in this note has been
applied. `cost-governor.py` was READ-ONLY to this builder (contract).
`spore-router.py` is shadow-only; the enforcement point below is the
integrator's decision after the returns series has real data.

## State today

- cost-governor.py's own docstring admits the attribution gap: fleet jobs
  carry "invocation count" as cost proxy with NO job/class/model attribution;
  the flywheel outcome ledger (`dream_math/flywheel/outcomes*.jsonl`) is
  ABSENT (searched, noted in its report).
- Therefore no routing objective change is justified yet. What ships now:
  schema + config + detector (all built), and ONE new logging row (below).

## Patch 1 (when the series should start collecting — no behavior change)

Add to the nightly runner / job wrapper (the place that already knows
`task_class` — cost-governor's JOB_TO_CLASS map is the reference):

```python
# spore shadow logging (spore-router.py RETURNS_SCHEMA) — append-only,
# via atomic_io.atomic_append_validated with the schema from spore-router.py
import importlib.util, sys, json
_spec = importlib.util.spec_from_file_location(
    "spore_router", str(KNOWLEDGE / "scripts" / "spore-router.py"))
spore_router = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spore_router)
from atomic_io import atomic_append_validated
row = {
    "session":  f"{job_name}-{start_ts}",       # unique per run
    "config":   resolved_model_id,              # gateway id actually used
    "model_family": family_of(resolved_model_id),
    "task_class": JOB_TO_CLASS[job_name],
    "value_proxy": float(value_signal),         # pass=1.0/fail=0.0 or score
    "cost": float(cost_signal),                 # bytes or invocation count
    "routing": "spore" if config_in_spores_off_policy else "dominant",
    "ts": now_iso_with_tz(),
}
atomic_append_validated(SERIES_PATH, row, spore_router.RETURNS_SCHEMA)
```

Until an epsilon-router actually assigns configs, `resolved_model_id` is
whatever the job would have used anyway, so every row is "dominant" and the
series is pure instrumentation. Spore rows begin only when the integrator
wires the epsilon assignment.

## Patch 2 (the epsilon reserve — ONLY after >= 1 week of real series data)

In the job dispatcher: with probability `spores.json:epsilon`, select a config
from `agent_classes[task_class].off_policy` (seeded per session for
reproducibility) and set `routing: "spore"`. NO prod-facing task class
participates until the operator signs off. epsilon=0 restores exact current routing.

## Patch 3 (the objective change the card wanted — LAST, gated)

When `models-evals/spore-returns.jsonl` has real spore + dominant rows:
cost-governor may ADD a section comparing per-class geometric-mean returns
(spore-router.divergences() output is importable and reusable) and PROPOSE
dominant-config changes when a sustained `ALARM-spore-outperforming` fires.
Cost-governor keeps its propose-never-edit contract; promotion of a spore
config is the operator's call. Divergence alarms also surface to the cortex attention
queue via the same report path cost-governor already uses.

## Wiring checklist for the integrator

- [ ] Patch 1 logging row into the nightly runner (shadow-dominant only)
- [ ] After ~1 week of rows: run `python3 scripts/spore-router.py --series
      knowledge/models-evals/spore-returns.jsonl` and review the divergence table
- [ ] Patch 2 epsilon reserve: the operator sign-off required (routing enforcement)
- [ ] Patch 3 objective section in cost-governor: separate the operator sign-off
