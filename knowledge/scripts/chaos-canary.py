#!/usr/bin/env python3
"""Chaos Canary — observability red team for Josh's Workato harness.

Injects faults into LOCAL copies of the Estate Twin (knowledge/twin/v1/),
then measures whether the detection chain would see them. HARD RULE: this
tool NEVER touches live Workato — no network calls at all. Everything runs
against the local twin snapshot and scenario copies.

Honesty note: detection latency is measured against a REFERENCE DETECTOR
(the baseline-diff check implemented here — what the watchdog WOULD see on
one sweep), not the live fleet. Wiring canary alarms into the real watchdog
sweep is the documented next step.

Commands:
  inject  --fault <connection_failure|scheduler_stall|recipe_corruption>
  detect  --scenario <dir>
  report

Ownership (frontier CONTRACTS.md): scripts/chaos-canary.py + knowledge/chaos/
Only. Reads twin/, watchdog-reports/, cortex/, workato-health/ read-only.
Stdlib only, exit 0 ok / 1 failure.
"""

import argparse
import hashlib
import json
import random
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

KNOWLEDGE = Path.home() / ".claude" / "knowledge"
TWIN = KNOWLEDGE / "twin" / "v1"
CHAOS = KNOWLEDGE / "chaos"
WATCHDOG_REPORTS = KNOWLEDGE / "watchdog-reports"
CORTEX_DISPATCHES = KNOWLEDGE / "cortex" / "dispatches.jsonl"
WORKATO_HEALTH = KNOWLEDGE / "workato-health"

FAULTS = ("connection_failure", "scheduler_stall", "recipe_corruption")
STALL_SAMPLE_DEFAULT = 25
HISTORY = CHAOS / "history.jsonl"


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ts_slug():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def sha256_line(s):
    if isinstance(s, bytes):
        return hashlib.sha256(s).hexdigest()
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def read_jsonl(path):
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_twin(root):
    root = Path(root)
    twin = {
        "recipes": read_jsonl(root / "recipes.jsonl"),
        "connections": read_jsonl(root / "connections.jsonl"),
        "schedulers": read_jsonl(root / "schedulers.jsonl"),
        "meta": json.loads((root / "meta.json").read_text()),
    }
    twin["recipe_idx"] = {r["id"]: r for r in twin["recipes"]}
    twin["conn_by_name"] = {c["name"]: c for c in twin["connections"]}
    return twin


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def append_history(rec):
    CHAOS.mkdir(parents=True, exist_ok=True)
    with open(HISTORY, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- inject

def running_recipe_ids(twin):
    return {r["id"] for r in twin["recipes"] if r.get("running")}


def inject_connection_failure(scen_dir, rng):
    """Delete the highest-fanout connection (by running recipes) from the copy."""
    scen = load_twin(scen_dir)
    rids = running_recipe_ids(scen)
    fanout = {}
    for r in scen["recipes"]:
        if r["id"] not in rids:
            continue
        for name in r.get("connection_names") or []:
            fanout[name] = fanout.get(name, 0) + 1
    if not fanout:
        raise RuntimeError("no connection references found in scenario copy")
    name = max(fanout, key=lambda n: (fanout[n], n))
    conn = scen["conn_by_name"].get(name)
    before = len(scen["connections"])
    scen["connections"] = [c for c in scen["connections"] if c["name"] != name]
    write_jsonl(scen_dir / "connections.jsonl", scen["connections"])
    referencing = sorted(
        r["id"] for r in scen["recipes"]
        if r["id"] in rids and name in (r.get("connection_names") or [])
    )
    return {
        "connection_name": name,
        "connection_id": conn["id"] if conn else None,
        "running_recipes_referencing": len(referencing),
        "referencing_recipe_ids_sample": referencing[:10],
        "connections_rows_before": before,
        "connections_rows_after": len(scen["connections"]),
    }


def inject_scheduler_stall(scen_dir, rng, sample):
    """Mark a random sample of running scheduler recipes stopped in the copy."""
    sched_rows = read_jsonl(scen_dir / "schedulers.jsonl")
    running = [r for r in sched_rows if r.get("running")]
    if not running:
        raise RuntimeError("no running schedulers in scenario copy")
    picked = rng.sample(running, min(sample, len(running)))
    picked_ids = {r["id"] for r in picked}
    for r in sched_rows:
        if r["id"] in picked_ids:
            r["running"] = False
    write_jsonl(scen_dir / "schedulers.jsonl", sched_rows)

    rec_rows = read_jsonl(scen_dir / "recipes.jsonl")
    for r in rec_rows:
        if r["id"] in picked_ids:
            r["running"] = False
    write_jsonl(scen_dir / "recipes.jsonl", rec_rows)
    return {
        "sample_size": len(picked),
        "stalled_recipe_ids": sorted(picked_ids),
        "stalled_names_sample": [r["name"] for r in picked[:5]],
    }


def inject_recipe_corruption(scen_dir, rng):
    """Corrupt one recipe's DSL field in the copy; record pristine hash.

    The twin snapshot does not carry the raw recipe DSL, so the serialized
    recipe record stands in for it: the pristine line is hashed, then a
    synthetic `dsl` field is grafted on with tampered content. Hash
    comparison against scenario.json is the corruption signal.
    """
    rows = read_jsonl(scen_dir / "recipes.jsonl")
    target = rng.choice(rows)
    idx = rows.index(target)
    pristine_line = json.dumps(target, ensure_ascii=False, sort_keys=True)
    pristine_sha = sha256_line(pristine_line)
    dsl_marker = f"CHAOS-CORRUPTED dsl opcodes clobbered by chaos-canary at {now_iso()}"
    target["dsl"] = dsl_marker
    rows[idx] = target
    write_jsonl(scen_dir / "recipes.jsonl", rows)
    return {
        "recipe_id": target["id"],
        "recipe_name": target["name"],
        "pristine_sha256": pristine_sha,
        "dsl_marker": dsl_marker,
        "note": "twin carries no raw DSL; serialized record + grafted dsl field used as corruption surface",
    }


def cmd_inject(args):
    fault = args.fault
    if fault not in FAULTS:
        print(f"unknown fault {fault!r}; choose one of {', '.join(FAULTS)}")
        return 1
    if not TWIN.exists():
        print(f"baseline twin missing at {TWIN}")
        return 1
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    slug = ts_slug()
    scen_dir = CHAOS / f"scenario-{slug}"
    if scen_dir.exists():
        print(f"scenario dir already exists: {scen_dir}")
        return 1
    CHAOS.mkdir(parents=True, exist_ok=True)
    shutil.copytree(TWIN, scen_dir / "baseline")
    # Working copy = the pristine baseline copied out, then mutated in place.
    for fn in ("recipes.jsonl", "connections.jsonl", "schedulers.jsonl", "meta.json"):
        shutil.copy2(scen_dir / "baseline" / fn, scen_dir / fn)
    print(f"scenario copy: {scen_dir} (from {TWIN}; pristine baseline frozen at baseline/)")

    if fault == "connection_failure":
        detail = inject_connection_failure(scen_dir, rng)
    elif fault == "scheduler_stall":
        detail = inject_scheduler_stall(scen_dir, rng, args.sample)
    else:
        detail = inject_recipe_corruption(scen_dir, rng)

    scenario = {
        "scenario_id": f"scenario-{slug}",
        "fault": fault,
        "injected_at": now_iso(),
        "baseline_twin": str(TWIN),
        "baseline_snapshot_at": json.loads((TWIN / "meta.json").read_text())["snapshot_at"],
        "injected": detail,
        "ground_truth": True,
        "baseline_hashes": {
            fn: sha256_line((scen_dir / "baseline" / fn).read_bytes())
            for fn in ("recipes.jsonl", "connections.jsonl", "schedulers.jsonl")
        },
    }
    (scen_dir / "scenario.json").write_text(json.dumps(scenario, indent=2) + "\n")
    print(f"fault injected: {fault}")
    print(json.dumps(detail, indent=2)[:1400])
    print(f"ground truth recorded: {scen_dir / 'scenario.json'}")
    return 0


# ---------------------------------------------------------------- detect

def recent_real_surface_mentions(window_h=24):
    """Scan REAL watchdog/evidence/cortex outputs from the last 24h.
    Returns (window_start_iso, files_scanned, blob) for substring checks."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_h)
    files, blob = [], []
    for pat in ("*.md", "*.json", "*.jsonl"):
        for p in WATCHDOG_REPORTS.glob(pat):
            if datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) >= cutoff:
                files.append(str(p))
                try:
                    blob.append(p.read_text(errors="replace"))
                except OSError:
                    pass
    if CORTEX_DISPATCHES.exists():
        for line in CORTEX_DISPATCHES.read_text(errors="replace").splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = d.get("ts", "")
            try:
                if datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) >= cutoff:
                    files.append(str(CORTEX_DISPATCHES))
                    blob.append(line)
            except ValueError:
                continue
    if (WORKATO_HEALTH / "health-latest.json").exists():
        p = WORKATO_HEALTH / "health-latest.json"
        files.append(str(p))
        blob.append(p.read_text(errors="replace"))
    for p in (WORKATO_HEALTH / "sweeps").glob("*.jsonl"):
        if datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) >= cutoff:
            files.append(str(p))
            try:
                blob.append(p.read_text(errors="replace"))
            except OSError:
                pass
    return cutoff.strftime("%Y-%m-%dT%H:%M:%SZ"), sorted(set(files)), "\n".join(blob)


def sweep_cycle_seconds():
    """Mean interval between the last real health sweeps = one sweep cycle."""
    sweeps = sorted((WORKATO_HEALTH / "sweeps").glob("*.jsonl"))
    if len(sweeps) < 2:
        return 3600.0, "default (fewer than 2 sweeps on disk)"
    stamps = []
    for p in sweeps[-8:]:
        try:
            last = read_jsonl(p)[-1]
            stamps.append(datetime.strptime(last["ts"], "%Y-%m-%dT%H:%M:%SZ"))
        except (ValueError, KeyError, IndexError, OSError):
            stamps.append(datetime.fromtimestamp(p.stat().st_mtime, timezone.utc))
    stamps = sorted(stamps)
    gaps = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:]) if b > a]
    if not gaps:
        return 3600.0, "default (no parseable gaps)"
    return sum(gaps) / len(gaps), f"mean of {len(gaps)} gaps across last {len(stamps)} sweeps"


def detect_scheduler_stall(scen_meta, scen, base):
    # The scheduler roster is the source of truth: baseline schedulers that
    # were running but are not running in the scenario = stall signals.
    base_running = {r["id"] for r in base["schedulers"] if r.get("running")}
    stalled = set(scen_meta["injected"]["stalled_recipe_ids"])
    scen_sched = {r["id"]: r for r in scen["schedulers"]}
    found = {i for i in stalled
             if i in base_running
             and (i not in scen_sched or not scen_sched[i].get("running"))}
    return stalled, found


def detect_connection_failure(scen_meta, scen, base):
    rids = running_recipe_ids(scen)
    missing = set()
    for r in scen["recipes"]:
        if r["id"] not in rids:
            continue
        for name in r.get("connection_names") or []:
            if name not in scen["conn_by_name"]:
                missing.add(name)
    return {scen_meta["injected"]["connection_name"]}, missing


def detect_recipe_corruption(scen_meta, scen, base):
    rid = scen_meta["injected"]["recipe_id"]
    row = scen["recipe_idx"].get(rid)
    if row is None:
        return {rid}, set()
    line = json.dumps(row, ensure_ascii=False, sort_keys=True)
    if sha256_line(line) != scen_meta["injected"]["pristine_sha256"]:
        return {rid}, {rid}
    return {rid}, set()


def cmd_detect(args):
    scen_dir = Path(args.scenario)
    sfile = scen_dir / "scenario.json"
    if not sfile.exists():
        print(f"no scenario.json in {scen_dir}")
        return 1
    scen_meta = json.loads(sfile.read_text())
    scen = load_twin(scen_dir)
    base = load_twin(scen_dir / "baseline")
    baseline_frozen = True
    drift = []
    for fn, want in scen_meta.get("baseline_hashes", {}).items():
        have = sha256_line((scen_dir / "baseline" / fn).read_bytes())
        if have != want:
            baseline_frozen = False
            drift.append(fn)
    t0 = time.perf_counter()

    fault = scen_meta["fault"]
    if fault == "scheduler_stall":
        injected, found = detect_scheduler_stall(scen_meta, scen, base)
        expected_total = scen_meta["injected"]["sample_size"]
    elif fault == "connection_failure":
        injected, found = detect_connection_failure(scen_meta, scen, base)
        expected_total = 1
    else:
        injected, found = detect_recipe_corruption(scen_meta, scen, base)
        expected_total = 1
    compute_ms = (time.perf_counter() - t0) * 1000.0

    # Real-surface check: would any REAL watchdog/evidence/cortex output from
    # the last 24h mention an equivalent signal? Synthetic faults will not
    # appear there; report honestly.
    cutoff, files, blob = recent_real_surface_mentions()
    needle_set = {str(i) for i in injected}
    conn_name = scen_meta["injected"].get("connection_name")
    if conn_name:
        needle_set.add(conn_name)
    needles = sorted(needle_set)
    hits = [n for n in needles if n in blob]

    cycle_s, cycle_src = sweep_cycle_seconds()
    undetected = sorted(injected - found) if fault != "connection_failure" else sorted(injected - found)
    detected = len(found)
    ok = detected == expected_total and not undetected

    report_path = CHAOS / f"canary-report-{scen_meta['scenario_id']}.md"
    lines = [
        "# Chaos Canary report — " + now_iso(),
        "",
        f"Scenario: `{scen_dir}`  |  Fault: **{fault}**  |  Frozen baseline twin snapshot: {scen_meta['baseline_snapshot_at']}",
        "",
        "## Result (reference detector)",
        "",
        f"- Injected (ground truth): {expected_total} fault target(s); detected by reference detector: {detected}",
        f"- Verdict: {'DETECTED (reference detector)' if ok else 'MISSED or partial'}",
        f"- Undetected: {undetected if undetected else 'none'}",
        f"- Frozen baseline integrity: {'intact' if baseline_frozen else 'DRIFTED (' + ', '.join(drift) + ') — detect ran against the frozen baseline/ copy, not the live twin'}",
        f"- Reference-detector compute time: {compute_ms:.1f} ms",
        f"- One sweep cycle (real watchdog cadence): {cycle_s:.0f}s ({cycle_src})",
        f"- Estimated detection latency: ~{cycle_s + compute_ms / 1000.0:.0f}s "
        "(one sweep cycle + detector compute)",
        "",
        "## Real-surface check (honest)",
        "",
        f"- Window: real watchdog-reports/, cortex/dispatches.jsonl, workato-health/ outputs from {cutoff} onward "
        f"({len(files)} file(s) scanned).",
        f"- Signal strings searched: {needles}",
        f"- Mentions found in real surfaces: {hits if hits else 'NONE'}",
        "- Note: a hit means the id/name appears in real sweep output (e.g. a sweep roster), NOT that any real "
        "surface reported the fault. Faults are synthetic; no real fault-signal mention is expected.",
        "- Expected: NONE. Faults are synthetic copies; the live watchdog has no reason to see them. "
        "Detection latency above is therefore measured against the REFERENCE DETECTOR (the baseline-diff check "
        "representing what watchdog WOULD see), not the live fleet.",
        "- Documented next step: wire canary alarm signals into the real watchdog sweep so latency is measured end-to-end.",
        "",
        "## Method",
        "",
        "- All work against local copies only; no network, no live Workato (hard rule).",
        "- scheduler_stall: running-in-baseline but stopped-in-scenario = should-detect-as-stalled.",
        "- connection_failure: connection referenced by running recipes but absent from scenario connections = should-detect-as-broken.",
        "- recipe_corruption: sha256 of serialized recipe record vs pristine hash in scenario.json; mismatch = corruption.",
    ]
    report_path.write_text("\n".join(lines) + "\n")

    append_history({
        "ts": now_iso(),
        "fault": fault,
        "scenario_dir": str(scen_dir),
        "injected_n": expected_total,
        "detected_n": detected,
        "undetected_n": len(undetected),
        "compute_latency_ms": round(compute_ms, 1),
        "sweep_cycle_s": round(cycle_s, 1),
        "est_latency_s": round(cycle_s + compute_ms / 1000.0, 1),
        "real_surface_hits": hits,
        "verdict": "detected" if ok else "missed",
        "measured_against": "reference_detector",
        "baseline_frozen": baseline_frozen,
    })

    print("\n".join(lines))
    print(f"\nreport written: {report_path}")
    return 0 if ok else 1


# ---------------------------------------------------------------- report

def cmd_report(_args):
    if not HISTORY.exists():
        print("no history yet — run inject + detect first")
        return 1
    rows = [json.loads(l) for l in HISTORY.read_text().splitlines() if l.strip()]
    by_fault, latencies, missed = {}, [], []
    for r in rows:
        f = r["fault"]
        agg = by_fault.setdefault(f, {"n": 0, "det": 0})
        agg["n"] += 1
        agg["det"] += 1 if r["verdict"] == "detected" else 0
        latencies.append(r.get("est_latency_s"))
        if r["verdict"] != "detected":
            missed.append(r)
    lat = [x for x in latencies if x is not None]
    mean_lat = sum(lat) / len(lat) if lat else 0.0
    print("=== Chaos Canary history ===")
    print(f"runs: {len(rows)}  (all measured against the reference detector, not the live fleet)")
    for f, a in sorted(by_fault.items()):
        rate = a["det"] / a["n"] * 100 if a["n"] else 0
        print(f"  {f:22s} injected {a['n']:3d}  detected {a['det']:3d}  rate {rate:5.1f}%")
    print(f"mean estimated detection latency: {mean_lat:.0f}s "
          "(sweep cycle + detector compute)")
    print(f"undetected runs: {len(missed)}")
    for m in missed:
        print(f"  - {m['ts']} {m['fault']} scenario={m['scenario_dir']}")
    print(f"history: {HISTORY}")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Chaos Canary — fault-injection red team over LOCAL twin copies (never live Workato)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_in = sub.add_parser("inject", help="copy the twin and inject a fault into the copy")
    p_in.add_argument("--fault", required=True, choices=FAULTS)
    p_in.add_argument("--sample", type=int, default=STALL_SAMPLE_DEFAULT,
                      help=f"recipes to stall for scheduler_stall (default {STALL_SAMPLE_DEFAULT})")
    p_in.add_argument("--seed", type=int, default=None, help="deterministic RNG seed")
    p_in.set_defaults(func=cmd_inject)

    p_det = sub.add_parser("detect", help="run the reference detector against a scenario")
    p_det.add_argument("--scenario", required=True, help="scenario dir under knowledge/chaos/")
    p_det.set_defaults(func=cmd_detect)

    p_rep = sub.add_parser("report", help="fault counts, detection rates, mean latency")
    p_rep.set_defaults(func=cmd_report)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
