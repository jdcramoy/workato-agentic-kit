#!/usr/bin/env python3
"""spore-router.py — bet-hedging spore portfolio, SHADOW MODE ONLY.

Wave-3 proposal (spore-portfolio, AMENDED 2026-10-11 amendment #9). Genotypes
maximizing the GEOMETRIC mean of fitness win in unpredictable environments;
a small stochastic switching rate epsilon maintains viable variants (spores)
so a regime shift in "best model" never strands the whole fleet. Monoculture
fragility is the killed failure class.

AMENDMENT #9 SCOPE (hard):
  - SHADOW MODE ONLY: this script writes/reads NO routing decision. It defines
    (a) the per-session returns series schema, (b) the epsilon-routing CONFIG
    (knowledge/config/spores.json), (c) the spore-vs-dominant divergence
    detector. Shadow logging and config only.
  - NO objective change to cost-governor.py (READ-ONLY to this script): the
    flywheel outcome ledger is absent today, so GM over a nonexistent series
    is decoration. The integration patch note is emitted as a FILE next to
    this script (spore-router-integration-patch-note.md) for the integrator.
  - NO third routing authority: enforcement is the integrator's decision
    after the returns series has real data.

Per-session returns series schema (JSONL, one row per agent session):
  session       str  unique session id (agent + timestamp or session key)
  config        str  the config id actually used (gateway model id, or
                     "model@prompt-variant" for prompt A/B spores)
  model_family  str  correlation family: glm|kimi|deepseek|gpt|minimax|
                     gemini|haiku|sonnet — the decorrelation key for the
                     fusion-N_eff cross-pollination
  task_class    str  routing class (sweep, lookup, autopsy-investigation,
                     triage-lane, build, judgment, backup)
  value_proxy   float >= 0  task's value proxy for the session (pass/fail
                     signal, output score — the honest proxy the writer logs)
  cost          float >= 0  cost proxy (bytes, tokens, or $ — one unit per
                     series, declared by the writer)
  routing       enum "dominant"|"spore"  (spore rows distinguishable — the
                     card's acceptance requirement)
  ts            ISO-8601 WITH timezone offset (atomic_io-validated)

Per-session return = max(RETURN_FLOOR, value_proxy - cost); the geometric
mean is taken over the floored returns (floored so logs exist — a zero
return must never zero out a whole arm's history).

Zero-LLM. stdlib only. Reuses scripts/atomic_io.py (read-only import).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from atomic_io import atomic_write, validate_row  # noqa: E402

HOME = Path(os.path.expanduser("~"))
K = HOME / ".claude" / "knowledge"
SPORES = K / "config" / "spores.json"
SERIES_DEFAULT = K / "models-evals" / "spore-returns.jsonl"
PATCH_NOTE = Path(__file__).parent / "spore-router-integration-patch-note.md"

RETURN_FLOOR = 0.01          # per-session return floor (GM-safe)
DEFAULT_EPSILON = 0.10       # the insurance premium
DEFAULT_THRESHOLD = 0.25     # divergence alarm margin (relative, both ways)
DEFAULT_MIN_SESSIONS = 5     # min rows per arm before any verdict

RETURNS_SCHEMA = {
    "required": ["session", "config", "model_family", "task_class",
                 "value_proxy", "cost", "routing", "ts"],
    "enums": {"routing": {"dominant", "spore"}},
    "timestamps": ["ts"],
}


def row_return(row):
    return max(RETURN_FLOOR, float(row["value_proxy"]) - float(row["cost"]))


def geo_mean(rows):
    if not rows:
        return None
    vals = [row_return(r) for r in rows]
    return math.exp(sum(math.log(v) for v in vals) / len(vals))


def load_series(path):
    rows = []
    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # never crash the detector on a corrupt line
    except FileNotFoundError:
        pass
    return rows


def divergences(rows, spores, min_sessions=None, threshold=None):
    """Spore-vs-dominant divergence verdicts per task class.

    Returns dicts: task_class, dominant_config, n_dom, n_spore,
    gm_dom, gm_spore, ratio (gm_spore/gm_dom), verdict.
    """
    if min_sessions is None:
        min_sessions = spores.get("min_sessions_per_arm", DEFAULT_MIN_SESSIONS)
    if threshold is None:
        threshold = spores.get("divergence_threshold", DEFAULT_THRESHOLD)
    out = []
    for cls, cfg in sorted(spores.get("agent_classes", {}).items()):
        dom_cfg = cfg.get("dominant")
        spore_cfgs = set(cfg.get("off_policy", []))
        dom = [r for r in rows if r.get("task_class") == cls
               and r.get("routing") == "dominant"]
        spo = [r for r in rows if r.get("task_class") == cls
               and r.get("routing") == "spore"
               and r.get("config") in spore_cfgs]
        gm_dom, gm_spo = geo_mean(dom), geo_mean(spo)
        rec = {
            "task_class": cls, "dominant_config": dom_cfg,
            "spore_configs": sorted(spore_cfgs),
            "n_dominant": len(dom), "n_spore": len(spo),
            "gm_dominant": round(gm_dom, 4) if gm_dom else None,
            "gm_spore": round(gm_spo, 4) if gm_spo else None,
        }
        if gm_dom is None or gm_spo is None or len(dom) < min_sessions \
                or len(spo) < min_sessions:
            rec["verdict"] = "insufficient-data"
            rec["ratio"] = None
        else:
            ratio = gm_spo / gm_dom
            rec["ratio"] = round(ratio, 3)
            if abs(1 - ratio) > threshold:
                rec["verdict"] = (
                    "ALARM-spore-outperforming" if ratio > 1
                    else "ALARM-dominant-outperforming")
            else:
                rec["verdict"] = "in-band"
        out.append(rec)
    return out


def check_series(rows):
    """Validate every row against the schema; return (ok_rows, errors)."""
    ok, errs = [], []
    for i, r in enumerate(rows):
        v = validate_row(r, RETURNS_SCHEMA)
        if v:
            errs.append(f"row {i}: " + "; ".join(v))
        else:
            ok.append(r)
    return ok, errs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--series", metavar="FILE",
                    help=f"returns series JSONL (default {SERIES_DEFAULT})")
    ap.add_argument("--config", metavar="FILE", default=str(SPORES),
                    help="spores.json (default)")
    ap.add_argument("--min-sessions", type=int, default=None)
    ap.add_argument("--threshold", type=float, default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    spores = json.loads(Path(args.config).read_text())
    if spores.get("mode") != "shadow":
        print("refusing: spores.json mode is not 'shadow' — this script is "
              "shadow-only by amendment #9", file=sys.stderr)
        return 1
    path = Path(args.series) if args.series else SERIES_DEFAULT
    rows, errs = check_series(load_series(path))
    for e in errs:
        print(f"schema violation (row skipped): {e}", file=sys.stderr)
    recs = divergences(rows, spores, args.min_sessions, args.threshold)
    for r in recs:
        print(json.dumps(r))
    n_alarm = sum(1 for r in recs if r["verdict"].startswith("ALARM"))
    print(f"# series={path} rows_ok={len(rows)} rows_bad={len(errs)} "
          f"classes={len(recs)} alarms={n_alarm} mode=shadow", file=sys.stderr)
    return 0


def selftest():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="spore-selftest-"))
    series = tmp / "series.jsonl"
    spores = {
        "mode": "shadow", "epsilon": 0.10, "min_sessions_per_arm": 5,
        "divergence_threshold": 0.25,
        "agent_classes": {
            "sweep": {"dominant": "fireworks/glm-5.3-flash",
                      "off_policy": ["fireworks/deepseek-v4.1-flash"]},
        },
    }
    ts = "2026-10-11T22:43:00+00:00"
    rows = []
    # dominant arm humming along at return ~1.0
    for i in range(10):
        rows.append({"session": f"dom-{i}", "config": "fireworks/glm-5.3-flash",
                     "model_family": "glm", "task_class": "sweep",
                     "value_proxy": 1.0, "cost": 0.0, "routing": "dominant",
                     "ts": ts})
    # spore arm clearly outperforming -> ALARM-spore-outperforming
    for i in range(6):
        rows.append({"session": f"spo-{i}",
                     "config": "fireworks/deepseek-v4.1-flash",
                     "model_family": "deepseek", "task_class": "sweep",
                     "value_proxy": 2.0, "cost": 0.0, "routing": "spore",
                     "ts": ts})
    # one deliberately malformed row (naive timestamp) — must be refused loudly
    rows.append({"session": "bad-1", "config": "x", "model_family": "glm",
                 "task_class": "sweep", "value_proxy": 1.0, "cost": 0.0,
                 "routing": "dominant", "ts": "2026-10-11 22:43:00"})
    series.write_text("".join(json.dumps(r) + "\n" for r in rows))
    ok, errs = check_series(load_series(series))
    assert len(ok) == 16 and len(errs) == 1, (len(ok), errs)  # naive ts caught
    recs = divergences(ok, spores)
    assert recs[0]["verdict"] == "ALARM-spore-outperforming", recs
    assert recs[0]["n_dominant"] == 10 and recs[0]["n_spore"] == 6
    # floor: a zero-value session must not zero the arm's GM
    zeroed = dict(rows[0], session="z", value_proxy=0.0)
    assert geo_mean([rows[0], zeroed]) > RETURN_FLOOR
    # insufficient data path
    thin = {"mode": "shadow", "min_sessions_per_arm": 100,
            "divergence_threshold": 0.25,
            "agent_classes": spores["agent_classes"]}
    assert divergences(ok, thin)[0]["verdict"] == "insufficient-data"
    # schema is enforced on writes too (used by the integrator's logger)
    from atomic_io import atomic_append_validated, SchemaViolation
    try:
        atomic_append_validated(tmp / "ledger.jsonl",
                                {"session": "s1"}, RETURNS_SCHEMA)
        raise AssertionError("schema refusal did not fire")
    except SchemaViolation:
        pass
    print(f"selftest PASS ({tmp}) — divergence ALARM demonstrated on "
          f"synthetic data (spore 2.0 vs dominant 1.0), naive-timestamp row "
          f"refused, floor + insufficient-data paths verified, "
          f"schema-gated append verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
