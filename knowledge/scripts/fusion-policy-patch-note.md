# PATCH NOTE for fusion-run.py — outcome labeling (integrator applies)

Builder: fusion-policy.py (wave-3, amendment 6b). fusion-run.py was NOT edited
(read-only under the Agent A contract); the integrator applies this patch.

## Why

models-evals/fusion.jsonl rows carry only execution metadata (model, ts,
prompt_sha, wall_s, tokens, execution error). Co-failure kappa (the >=30-joint
panel-invariant gate in fusion-policy.py) needs OUTCOME labels — was the
model's answer right? — which nothing writes today. Without labels the kappa
gate stays deferred forever and panels can only be policed by the static
same-family ban.

## Change (add to the per-row dict in fusion-run.py's ledger loop, line ~70)

After the panel completes and the operator/caller names the correct answer(s), append
an OUTCOME row (keeps the ledger append-only, one row per model per run):

```python
# outcome labeling (wave-3 amendment 6b) — run AFTER the caller judges
# FUSION_OUTCOME_FILE: /tmp/fusion-outcome-<runid>.json = {"prompt_sha": ...,
#   "correct_models": ["fireworks/kimi-k3", ...], "labeled_by": "josh|session-id"}
outcome_file = os.environ.get("FUSION_OUTCOME_FILE")
if outcome_file and os.path.exists(outcome_file):
    oc = json.load(open(outcome_file))
    for m in models:
        with open(LEDGER, "a") as f:
            f.write(json.dumps({
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "model": m,
                "prompt_sha": oc["prompt_sha"],
                "outcome": "correct" if m in oc["correct_models"]
                           else "incorrect",
                "labeled_by": oc.get("labeled_by", "unknown"),
            }) + "\n")
```

Field contract consumed by fusion-policy.py --kappa-table:
- `outcome`: "correct" | "incorrect" | "abstain" (label semantics, NOT the
  execution `error` field — that one stays as-is)
- `labeled_by`: who judged (audit trail; unlabeled rows keep kappa deferred)

## After landing

Once any pair has >= 30 labeled joint observations
(models-evals/kappa-table.jsonl gate_status flips), implement the kappa ->
rejection path in fusion-policy.py's kappa_gate stub (currently raises
NotImplementedError) and enforce: no two models with co-failure kappa > 0.5
on one panel; fusion-promoted claims carry evidentiary weight N_eff, not N.
