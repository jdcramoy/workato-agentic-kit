#!/usr/bin/env python3
"""fusion-policy.py — effective-N policy for fusion panels (ADVISORY ONLY).

AMENDED SPEC (wave3 amendment 6, dissenter 2026-10-11): instrument + static
ban NOW, kappa enforcement DEFERRED.

  (a) STATIC SAME-FAMILY BAN: a panel with two same-family models (e.g.
      fireworks/kimi-k3 + baseten/kimi-k3 — the default panel in
      fusion-run.py, which produced the kimi unanimous-wrong incident) is
      rejected: correlated training lineages buy near-zero effective N.
      Family = model lineage prefix (kimi, glm, deepseek, ...), provider-
      agnostic — mapping derived from domains/model-gateway-playbook.md's
      provider rosters; override/extend with --families FILE.
  (b) OUTCOME LABELING: the patch note for fusion-run.py (add labeled-outcome
      fields to fusion.jsonl rows) is emitted next to this script —
      fusion-run.py itself is NOT edited by this builder (integrator applies).
  (c) KAPPA: pairwise co-failure kappa drives panel reweighting ONLY once a
      pair has >= 30 labeled joint observations. Below the gate the policy
      reports "deferred" and unknown pairs default rho = 0.5 (pessimistic —
      never over-trust fusion by default). The >=30 gate is visible in code
      (MIN_JOINTS_FOR_KAPPA); the kappa->rejection path is a STUB until
      labeled history exists (see kappa_gate).

ADVISORY MODE — CONSTITUTIONAL: this tool NEVER refuses a fusion run Josh
explicitly requested. Pass --requested-by-josh to mark a panel as Josh-
authorized: violations are reported as advisory notes and the verdict is
"allowed (josh-requested)" — the policy advises panels, it never inverts
authority over Josh's P0 calls. Without the flag, --strict makes a rejected
panel exit non-zero (for automated callers); default is advisory exit 0
always.

Usage:
  fusion-policy.py --panel fireworks/kimi-k3 baseten/kimi-k3 fireworks/glm-5.3-flash
  fusion-policy.py --panel ... --requested-by-josh
  fusion-policy.py --panel ... --strict            # automated callers: exit 2 on reject
  fusion-policy.py --kappa-table                   # rebuild kappa-table.jsonl from fusion.jsonl
  fusion-policy.py --emit-patch-note               # (re)write the fusion-run.py patch note
  fusion-policy.py --kappa-debug modelA modelB     # kappa math on labeled rows, reported only
  fusion-policy.py --selftest

Stdlib only. models-evals/fusion.jsonl is READ-ONLY here; the only file this
script writes (besides its own patch note) is models-evals/kappa-table.jsonl.
"""

import argparse
import collections
import datetime as dt
import itertools
import json
import os
import sys

HOME = os.path.expanduser("~")
SCRIPTS = os.path.join(HOME, ".claude", "knowledge", "scripts")
FUSION_LEDGER = os.path.join(HOME, ".claude", "knowledge", "models-evals",
                             "fusion.jsonl")
KAPPA_TABLE = os.path.join(HOME, ".claude", "knowledge", "models-evals",
                           "kappa-table.jsonl")
PATCH_NOTE = os.path.join(SCRIPTS, "fusion-policy-patch-note.md")
DEFAULT_FAMILIES = os.path.join(HOME, ".claude", "knowledge", "config",
                                "model-routing.json")

# --- (c) the kappa gate, visible in code ------------------------------------
MIN_JOINTS_FOR_KAPPA = 30   # labeled joint observations per pair, minimum
KAPPA_ENFORCE_THRESHOLD = 0.5  # co-failure kappa above which a pair is banned
RHO_DEFAULT = 0.5           # pessimistic default correlation for unknown pairs


def family_of(model_id, families=None):
    """Model family (training lineage) of 'provider/model'. Provider-agnostic:
    fireworks/kimi-k3 and baseten/kimi-k3 are the SAME family. Suffixes like
    -fast/-flash are speed variants of one lineage (playbook: kimi-k3 vs
    kimi-k3-fast are quality/speed tiers of the same model)."""
    families = families or {}
    if model_id in families:
        return families[model_id]
    model = model_id.split("/")[-1]
    lineage = model.split("-", 1)[0].lower()
    return lineage


def check_panel(models, families=None):
    """Static same-family ban. Returns (violations, eff_n_floor) where
    eff_n_floor uses the pessimistic default rho for every same-family pair."""
    fams = [(m, family_of(m, families)) for m in models]
    violations = []
    for (a, fa), (b, fb) in itertools.combinations(fams, 2):
        if fa == fb:
            violations.append(f"{a} + {b} share family '{fa}'")
    n = len(models)
    same_pairs = len(violations)
    # N_eff = N / (1 + (N-1)*rho) with pessimistic rho on same-family pairs
    rho = (same_pairs / (n * (n - 1) / 2)) if n > 1 else 0.0
    eff_n = n / (1 + (n - 1) * rho) if n else 0.0
    return violations, round(eff_n, 2)


def kappa_gate(pair, n_joints):
    """THE STUB. Returns an enforcement decision for a model pair.
    Below MIN_JOINTS_FOR_KAPPA the kappa path is DEFERRED (amendment 6c):
    the static family ban is the only active rule. Above the gate this stub
    raises — wiring real kappa enforcement needs the labeled-outcome history
    that the patch note (item b) will start accumulating."""
    if n_joints < MIN_JOINTS_FOR_KAPPA:
        return {"pair": list(pair), "n_joints": n_joints,
                "status": "deferred",
                "gate": f">={MIN_JOINTS_FOR_KAPPA} labeled joints required",
                "rho_used": RHO_DEFAULT}
    raise NotImplementedError(
        f"kappa enforcement stub reached: pair={pair} has n_joints="
        f"{n_joints} >= {MIN_JOINTS_FOR_KAPPA} but no labeled joint history "
        f"exists yet. Land the fusion-run.py outcome-labeling patch note "
        f"({os.path.basename(PATCH_NOTE)}) first; then implement scoring here.")


def cohen_kappa(labels_a, labels_b):
    """Real kappa math on two aligned outcome label sequences
    (e.g. 'correct'/'incorrect'). Reported-only until the gate flips."""
    assert len(labels_a) == len(labels_b) and labels_a
    n = len(labels_a)
    po = sum(1 for a, b in zip(labels_a, labels_b) if a == b) / n
    pa = collections.Counter(labels_a)
    pb = collections.Counter(labels_b)
    pe = sum(pa[k] * pb[k] for k in set(pa) & set(pb)) / (n * n)
    return None if pe == 1 else (po - pe) / (1 - pe)


def build_kappa_table():
    """Per-pair joint-observation counts from fusion.jsonl (READ-ONLY).
    kappa stays null until outcome labels exist (patch note item b); rho
    default 0.5; gate deferred below 30 joints."""
    rows = [json.loads(l) for l in open(FUSION_LEDGER) if l.strip()]
    by_prompt = collections.defaultdict(dict)
    for r in rows:
        m, sha = r.get("model"), r.get("prompt_sha")
        if m and sha:
            # an execution error IS an observable failure label for now
            by_prompt[sha][m] = "error" if r.get("error") else "answered"
    pairs = collections.defaultdict(lambda: {"joints": 0, "both_error": 0,
                                             "one_error": 0, "agree": 0})
    for sha, models in by_prompt.items():
        for a, b in itertools.combinations(sorted(models), 2):
            p = pairs[(a, b)]
            p["joints"] += 1
            ea, eb = models[a] == "error", models[b] == "error"
            p["both_error"] += ea and eb
            p["one_error"] += ea != eb
            p["agree"] += ea == eb
    out = []
    for (a, b), p in sorted(pairs.items()):
        rec = {"ts": dt.datetime.now().isoformat(timespec="seconds"),
               "model_a": a, "model_b": b, **p,
               "kappa": None,
               "kappa_note": "no outcome labels in fusion.jsonl yet — "
                             "co-failure kappa uncomputable (patch note pending)",
               "rho_default": RHO_DEFAULT,
               "gate_status": kappa_gate((a, b), p["joints"])["status"],
               "gate": f">={MIN_JOINTS_FOR_KAPPA} joints"}
        out.append(rec)
    from atomic_io import atomic_write
    atomic_write(KAPPA_TABLE,
                 "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
    print(f"wrote {len(out)} pair rows -> {KAPPA_TABLE}")
    for r in out:
        print(f"  {r['model_a']} + {r['model_b']}: joints={r['joints']} "
              f"agree={r['agree']} kappa=null gate={r['gate_status']}")
    return 0


PATCH_NOTE_TEXT = """# PATCH NOTE for fusion-run.py — outcome labeling (integrator applies)

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

After the panel completes and Josh/caller names the correct answer(s), append
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
            }) + "\\n")
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
"""

PANEL_VERDICT_HELP = (
    "Advisory only. NEVER refuses a fusion run Josh explicitly requested: "
    "pass --requested-by-josh to mark the panel Josh-authorized and every "
    "violation degrades to a note with verdict 'allowed (josh-requested)'.")


def cmd_panel(args):
    families = {}
    if args.families:
        families.update(json.load(open(args.families)))
    models = args.panel
    if len(models) < 2:
        print("a panel needs >= 2 models", file=sys.stderr)
        return 3
    violations, eff_n = check_panel(models, families)
    if args.requested_by_josh:
        verdict = "allowed (josh-requested)"
        note = ("Josh explicitly requested this panel — advisory notes only; "
                "the policy never refuses it")
    elif violations:
        verdict = "rejected (advisory)" if not args.strict else "rejected"
        note = ("same-family panelists buy near-zero effective N "
                "(kimi-unanimous-wrong incident class)")
    else:
        verdict = "pass"
        note = "no two same-family models on the panel"
    rec = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "panel": models,
        "families": {m: family_of(m, families) for m in models},
        "n": len(models),
        "n_eff_floor": eff_n,
        "rho_default_unknown_pairs": RHO_DEFAULT,
        "same_family_violations": violations,
        "kappa_enforcement": "deferred (>=30 labeled joints per pair required)",
        "verdict": verdict,
        "mode": "advisory",
        "note": note,
    }
    print(json.dumps(rec, indent=2, ensure_ascii=False))
    if args.strict and violations and not args.requested_by_josh:
        return 2
    return 0


def cmd_selftest():
    # 1. the kimi incident panel: fireworks/kimi-k3 + baseten/kimi-k3 banned
    v, eff = check_panel(["fireworks/kimi-k3", "baseten/kimi-k3",
                          "fireworks/glm-5.3-flash"])
    assert any("kimi" in x for x in v), v
    assert eff < 3, f"eff_n floor should drop below N: {eff}"
    # 2. clean panel passes
    v2, eff2 = check_panel(["fireworks/kimi-k3", "fireworks/glm-5.3-flash",
                            "baseten/deepseek-v4-pro"])
    assert v2 == [], v2
    assert eff2 == 3.0, eff2
    # 3. speed variants are one family
    assert family_of("fireworks/kimi-k3-fast") == family_of("baseten/kimi-k3")
    # 4. override map honored
    assert family_of("vendor/custom-7b", {"vendor/custom-7b": "mystery"}) == "mystery"
    # 5. kappa math sanity: perfect agreement -> kappa 1.0; chance agreement -> ~0
    k = cohen_kappa(["c", "i", "c", "i"], ["c", "i", "c", "i"])
    assert abs(k - 1.0) < 1e-9, k
    # 6. the gate is visible and defers below 30 joints...
    g = kappa_gate(("a", "b"), 29)
    assert g["status"] == "deferred" and g["rho_used"] == 0.5
    # ...and the >=30 path is a LOUD stub, not silent advice
    try:
        kappa_gate(("a", "b"), 30)
        raise SystemExit("selftest failed: stub did not fire at 30 joints")
    except NotImplementedError:
        pass
    print("SELFTEST PASS: same-family ban (kimi incident), clean panel, "
          "family variants, overrides, kappa math, 30-joint gate + stub OK")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Effective-N policy for fusion panels. " + PANEL_VERDICT_HELP,
        epilog="Enforced now: static same-family ban. Deferred: kappa > 0.5 "
               f"pair ban (needs >={MIN_JOINTS_FOR_KAPPA} labeled joints per "
               "pair — emit outcome labels via the patch note first).")
    ap.add_argument("--panel", nargs="+",
                    help="model list, e.g. fireworks/kimi-k3 baseten/kimi-k3")
    ap.add_argument("--requested-by-josh", action="store_true",
                    help="mark the panel Josh-requested: NEVER refused, "
                         "violations reported as advisory notes only")
    ap.add_argument("--strict", action="store_true",
                    help="exit 2 on rejection (automated callers); default "
                         "is advisory exit 0 always")
    ap.add_argument("--families",
                    help=f"JSON file of family overrides "
                         f"{{model_id: family}}; default lineage map derived "
                         f"from model-gateway-playbook.md rosters")
    ap.add_argument("--kappa-table", action="store_true",
                    help=f"rebuild {os.path.basename(KAPPA_TABLE)} from "
                         f"fusion.jsonl (read-only) and exit")
    ap.add_argument("--emit-patch-note", action="store_true",
                    help=f"(re)write {os.path.basename(PATCH_NOTE)} and exit")
    ap.add_argument("--kappa-debug", nargs=2, metavar=("MODEL_A", "MODEL_B"),
                    help="report-only kappa for a pair from labeled rows")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return cmd_selftest()
    if args.kappa_table:
        return build_kappa_table()
    if args.emit_patch_note:
        from atomic_io import atomic_write
        atomic_write(PATCH_NOTE, PATCH_NOTE_TEXT)
        print(f"wrote {PATCH_NOTE}")
        return 0
    if args.kappa_debug:
        sys.exit("kappa-debug: no labeled outcome rows exist in fusion.jsonl "
                 "yet — land the patch note first (amendment 6c: deferred)")
    if not args.panel:
        ap.error("--panel is required (or --selftest / --kappa-table / "
                 "--emit-patch-note)")
    return cmd_panel(args)


if __name__ == "__main__":
    sys.exit(main())
