#!/usr/bin/env python3
"""fdt-gate.py — fluctuation-dissipation gate on improvement claims.

AMENDED SPEC (wave3 amendment 2, dissenter 2026-10-11): INSTRUMENT-FIRST.
The gate ships as the claim RECORD FORMAT + a CLI that verdicts claims
supplied to it against a real series that exists today. value-ledger wiring
is the integrator's job — this script does NOT touch the value ledger.

The failure it kills: claims of the form "change X improved metric M by
delta" where delta is smaller than M's natural day-to-day wiggle. Rule:
accept only if |delta| > 2*sigma, where sigma is M's stationary noise floor
estimated from PRE-change history (MAD x 1.4826, robust to outliers), with
an adequate post-change sample size. A metric whose sigma already exceeds
the claimed effect is flagged a BAD INSTRUMENT — it cannot measure
improvements of that size at all.

Record format (JSONL — one improvement-claim verdict per line):
  claim_id        str   stable id of the claim
  ts              str   when verdicted (ISO-8601 with tz offset)
  metric          str   human name of the metric
  metric_series   str   series ref used for the verdict (e.g.
                        "predictions-hitrate", "heartbeat:cortex", "values:...")
  changed_at      str   change point (ISO-8601 with tz) or null
  delta           num   CLAIMED improvement (pre -> post)
  n_pre           int   pre-change sample size used for sigma
  n_post          int   post-change sample size
  sigma           num   estimated noise floor (MAD-based)
  method          str   sigma estimator tag, e.g. "MADx1.4826"
  observed_shift  num   actually measured post-pre shift (null if n too small)
  threshold_sigma num   acceptance multiple (default 2.0)
  verdict         enum  confirmed | within_noise_floor | refuted |
                        insufficient_data
  bad_instrument  bool  sigma >= |delta|: noise floor exceeds the claimed
                        effect — metric flagged for improvement measurement
  reason          str   plain-English verdict rationale

Series sources wired today (all real, all read-only):
  predictions-hitrate   per-prediction hit/miss (Bernoulli) points from
                        knowledge/dreams/predictions.jsonl
  heartbeat:JOB         beats-per-hour for one fleet job in
                        knowledge/garden-reports/heartbeat.jsonl
  file:PATH:FIELD       numeric FIELD per line of a JSONL file
  values:a,b,c          literal numbers (selftests, ad-hoc checks)

Usage:
  fdt-gate.py --claim-file CLAIM.json --series predictions-hitrate \
              --changed-at 2026-10-10T00:00:00+00:00
  fdt-gate.py --claim-file CLAIM.json --series heartbeat:session-shadow \
              --changed-at 2026-10-10T00:00:00+00:00 --append LEDGER.jsonl
  fdt-gate.py --series values:3.1,2.9,3.0,3.2,4.8,5.1 --changed-index 4 ...
  fdt-gate.py --schema
  fdt-gate.py --selftest

NEVER books to the value ledger itself (integrator wires the derive path).
Stdlib only. Exit 0 = the gate produced a verdict (ANY verdict, including
within_noise_floor); exit 2 = rejected; exit 3 = gate itself failed.
"""

import argparse
import datetime as dt
import json
import os
import statistics
import sys

HOME = os.path.expanduser("~")
SCRIPTS = os.path.join(HOME, ".claude", "knowledge", "scripts")
PREDICTIONS = os.path.join(HOME, ".claude", "knowledge", "dreams",
                           "predictions.jsonl")
HEARTBEAT = os.path.join(HOME, ".claude", "knowledge", "garden-reports",
                         "heartbeat.jsonl")

VERDICTS = {"confirmed", "within_noise_floor", "refuted", "insufficient_data"}
SCHEMA = {
    "required": ["claim_id", "metric_series", "delta", "n_pre", "n_post",
                 "sigma", "verdict"],
    "enums": {"verdict": VERDICTS},
    "timestamps": ["ts"],
}


def parse_ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).replace(
        tzinfo=None)


# --- series extractors: each returns [(ts_or_None, value), ...] -------------

def series_predictions_hitrate():
    """Per-prediction Bernoulli points: 1.0 if the closed prediction matched,
    0.0 otherwise. One point per CLOSED prediction — the hit-rate claim unit."""
    pts = []
    if not os.path.exists(PREDICTIONS):
        sys.exit(f"missing real series file: {PREDICTIONS}")
    for line in open(PREDICTIONS):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        v, closed = r.get("verdict"), r.get("closed")
        if v not in ("matched", "deviated", "failed") or not closed:
            continue
        pts.append((closed, 1.0 if v == "matched" else 0.0))
    return sorted(pts)


def series_heartbeat(job):
    """Beats-per-hour for one fleet job (per-day is too coarse: the ledger
    spans ~2 days at wave-3 build time)."""
    if not os.path.exists(HEARTBEAT):
        sys.exit(f"missing real series file: {HEARTBEAT}")
    per_hour = {}
    for line in open(HEARTBEAT):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        if r.get("job") != job:
            continue
        t = parse_ts(r["ts"])
        hour = t.replace(minute=0, second=0, microsecond=0).isoformat()
        per_hour[hour] = per_hour.get(hour, 0) + 1
    if not per_hour:
        sys.exit(f"heartbeat has no beats for job {job!r} — known jobs: "
                 f"session-shadow, ops-visibility, cortex, workato-health")
    return sorted(per_hour.items())


def series_file(path, field):
    pts = []
    for line in open(path):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        v = r.get(field)
        if isinstance(v, (int, float)):
            pts.append((r.get("ts") or r.get("opened"), float(v)))
    return pts


def load_series(spec):
    if spec.startswith("values:"):
        vals = [float(x) for x in spec.split(":", 1)[1].split(",")]
        return [(None, v) for v in vals]
    if spec == "predictions-hitrate":
        return series_predictions_hitrate()
    if spec.startswith("heartbeat:"):
        return series_heartbeat(spec.split(":", 1)[1])
    if spec.startswith("file:"):
        parts = spec.split(":", 2)
        return series_file(parts[1], parts[2])
    sys.exit(f"unknown series spec {spec!r} — use predictions-hitrate | "
             f"heartbeat:JOB | file:PATH:FIELD | values:a,b,c")


def split_series(pts, changed_at=None, changed_index=None):
    """Split into (pre, post) by a change point ts or an index into the
    series. Pre = strictly before the change."""
    if changed_index is not None:
        vals = [v for _, v in pts]
        return vals[:changed_index], vals[changed_index:]
    c = parse_ts(changed_at)
    pre = [v for t, v in pts if t and parse_ts(t) < c]
    post = [v for t, v in pts if not (t and parse_ts(t) < c)]
    # ts-less points (values: spec) — user must use --changed-index
    unassigned = [v for t, v in pts if not t]
    if unassigned:
        sys.exit("series has untimestamped points — use --changed-index")
    return pre, post


def sigma_of(pre):
    """Stationary noise floor from pre-change history: MAD x 1.4826 (normal
    consistency), falling back to sample stdev, then 0."""
    if len(pre) >= 2:
        med = statistics.median(pre)
        mad = statistics.median(abs(x - med) for x in pre) * 1.4826
        if mad > 0:
            return mad, "MADx1.4826"
        sd = statistics.stdev(pre)
        if sd > 0:
            return sd, "stdev(MAD-degenerate)"
    return 0.0, "underdetermined"


def verdict_claim(claim, series_pts, changed_at=None, changed_index=None,
                  threshold=2.0, min_pre=6, min_post=3):
    pre, post = split_series(series_pts, changed_at, changed_index)
    n_pre, n_post = len(pre), len(post)
    rec = {
        "claim_id": claim.get("claim_id", "unnamed"),
        "metric": claim.get("metric", "?"),
        "metric_series": claim.get("metric_series", "?"),
        "changed_at": changed_at,
        "delta": claim.get("delta"),
        "n_pre": n_pre, "n_post": n_post,
        "threshold_sigma": threshold,
        "ts": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    delta = claim.get("delta")
    if delta is None:
        rec.update(verdict="insufficient_data", sigma=0.0, bad_instrument=False,
                   reason="claim carries no delta — nothing to gate")
        return rec
    delta = float(delta)
    if n_pre < min_pre or n_post < min_post:
        rec.update(verdict="insufficient_data", sigma=None, bad_instrument=False,
                   observed_shift=None,
                   reason=f"n_pre={n_pre} (<{min_pre}) or n_post={n_post} "
                          f"(<{min_post}) — gate refuses to bless on thin data")
        return rec
    sigma, method = sigma_of(pre)
    rec["sigma"], rec["method"] = round(sigma, 6), method
    observed = statistics.mean(post) - statistics.mean(pre)
    rec["observed_shift"] = round(observed, 6)
    bad_instrument = sigma >= abs(delta) > 0
    rec["bad_instrument"] = bad_instrument
    if abs(delta) > threshold * sigma:
        # claimed effect clears the noise floor — does the data move with it?
        if observed * delta < 0 and abs(observed) > threshold * sigma:
            rec.update(verdict="refuted",
                       reason=f"claimed delta {delta} clears {threshold}σ "
                              f"(σ={sigma:.4g}) but the post-change data moved "
                              f"the OPPOSITE way ({observed:.4g})")
            return rec
        rec.update(verdict="confirmed",
                   reason=f"delta {delta} > {threshold}σ (σ={sigma:.4g}, "
                          f"{method}, n_pre={n_pre}, n_post={n_post}); "
                          f"observed shift {observed:.4g}")
        return rec
    rec.update(verdict="within_noise_floor",
               reason=f"delta {delta} <= {threshold}σ (σ={sigma:.4g}, "
                      f"{method}) — books ZERO as within noise floor"
                      + ("; BAD INSTRUMENT: σ >= |delta|, this metric cannot "
                         "resolve improvements of the claimed size"
                         if bad_instrument else ""))
    return rec


def emit(rec, append_path):
    line = json.dumps(rec, ensure_ascii=False)
    if append_path:
        from atomic_io import atomic_append_validated
        atomic_append_validated(append_path, rec, SCHEMA)
    print(line)


def selftest():
    # 1. real effect above noise: pre jitters ~3.0±0.2, post ~5.0
    pts = [(None, 3.0), (None, 3.2), (None, 2.8), (None, 3.1), (None, 2.9),
           (None, 3.0), (None, 5.0), (None, 5.1), (None, 4.9)]
    rec = verdict_claim({"claim_id": "t1", "delta": 2.0},
                        pts, changed_index=6)
    assert rec["verdict"] == "confirmed", rec
    assert rec["method"] == "MADx1.4826"
    # 2. tiny effect inside the wiggle -> within_noise_floor + bad instrument
    pts2 = [(None, 3.0), (None, 3.4), (None, 2.6), (None, 3.2), (None, 2.8),
            (None, 3.1), (None, 3.25), (None, 3.05), (None, 3.2)]
    rec2 = verdict_claim({"claim_id": "t2", "delta": 0.05},
                         pts2, changed_index=6)
    assert rec2["verdict"] == "within_noise_floor", rec2
    assert rec2["bad_instrument"] is True, rec2
    # 3. insufficient data
    rec3 = verdict_claim({"claim_id": "t3", "delta": 1.0},
                         [(None, 1.0), (None, 2.0)], changed_index=1)
    assert rec3["verdict"] == "insufficient_data", rec3
    # 4. refuted: post moves opposite the claim, above noise
    pts4 = [(None, 1.0), (None, 1.1), (None, 0.9), (None, 1.0), (None, 1.1),
            (None, 0.9), (None, -3.0), (None, -3.1), (None, -2.9)]
    rec4 = verdict_claim({"claim_id": "t4", "delta": 2.0},
                         pts4, changed_index=6)
    assert rec4["verdict"] == "refuted", rec4
    # 5. validated append round-trips
    import tempfile
    tmp = os.path.join(tempfile.mkdtemp(), "claims.jsonl")
    emit(rec, tmp)
    emit(rec2, tmp)
    back = [json.loads(l) for l in open(tmp)]
    assert len(back) == 2 and back[0]["verdict"] == "confirmed"
    # schema violation is loudly refused
    from atomic_io import SchemaViolation, atomic_append_validated
    try:
        bad = dict(rec, verdict="sorta-worked")
        atomic_append_validated(tmp, bad, SCHEMA)
        raise SystemExit("selftest failed: bad verdict was accepted")
    except SchemaViolation:
        pass
    print("SELFTEST PASS: confirmed / within_noise_floor(+bad_instrument) / "
          "insufficient_data / refuted / validated-append all OK")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Fluctuation-dissipation gate: verdicts improvement "
                    "claims against a real metric series (amendment 2: "
                    "instrument-first; value-ledger wiring is the "
                    "integrator's job — this script never books hours).")
    ap.add_argument("--claim-file",
                    help="JSON file with the claim: claim_id, metric, "
                         "metric_series, delta")
    ap.add_argument("--claim-id", help="inline claim id (if no --claim-file)")
    ap.add_argument("--delta", type=float, help="inline claimed improvement")
    ap.add_argument("--metric", help="inline metric name")
    ap.add_argument("--series", help="series spec: predictions-hitrate | "
                                     "heartbeat:JOB | file:PATH:FIELD | "
                                     "values:a,b,c")
    ap.add_argument("--changed-at", help="change point (ISO-8601; ts-split)")
    ap.add_argument("--changed-index", type=int,
                    help="change point as series index (for values: specs)")
    ap.add_argument("--threshold-sigma", type=float, default=2.0)
    ap.add_argument("--min-pre", type=int, default=6)
    ap.add_argument("--min-post", type=int, default=3)
    ap.add_argument("--append", help="append the verdict record to this JSONL "
                                     "ledger (validated; schema-lock)")
    ap.add_argument("--schema", action="store_true",
                    help="print the record-format schema and exit")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if args.schema:
        print(json.dumps(SCHEMA, indent=2, default=sorted))
        print(__doc__.split("Record format", 1)[1].split("Series sources", 1)[0],
              file=sys.stderr)
        return 0
    if not args.series:
        ap.error("--series is required (or use --selftest / --schema)")

    if args.claim_file:
        claim = json.load(open(args.claim_file))
    elif args.delta is not None:
        claim = {"claim_id": args.claim_id or "inline-" + str(int(dt.datetime.now()
                 .timestamp())), "delta": args.delta,
                 "metric": args.metric or "?",
                 "metric_series": args.series}
    else:
        ap.error("need --claim-file or --delta")

    pts = load_series(args.series)
    rec = verdict_claim(claim, pts, changed_at=args.changed_at,
                        changed_index=args.changed_index,
                        threshold=args.threshold_sigma, min_pre=args.min_pre,
                        min_post=args.min_post)
    rec.setdefault("metric_series", args.series)
    emit(rec, args.append)
    return 0


if __name__ == "__main__":
    sys.exit(main())
