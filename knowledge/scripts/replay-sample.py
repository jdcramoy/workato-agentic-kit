#!/usr/bin/env python3
"""replay-sample.py — salience-weighted interleaved replay sampler (#9,
harness-next10 review 2026-10-11). Zero-LLM, stdlib only.

The harness dreamer mines ONLY its recency window (config mine_days_back,
currently 3 days), so older consolidation is never revisited — the
VUA-revert failure class recurred 3x across 5 weeks precisely because no
surface re-looked at old sessions. This sampler picks ~3 OLD Claude
session transcripts (mtime older than the dreamer window) for a re-mine,
weighted by:

  correction density   crude file-level proxy: byte-counts of correction
                       markers ("I said", "not that", "revert", "undo",
                       "that's wrong", "you broke", "why did you",
                       "I meant") per MB scanned. NOT a parse — Josh
                       phrases and code both hit these; it is a density
                       signal, not a verdict.
  tool-error density   byte-counts of error signatures ("Error:", "error:",
                       "ERROR", "failed", "Traceback", "permission",
                       "denied", "EACCES", "EPERM") per MB scanned.
  spacing              days since the session was last sampled for replay
                       (state: garden-reports/replay-state.json); never-
                       sampled sessions cap the credit at RECENCY_CAP days.
  incident proximity   +INCIDENT_BONUS if the session's mtime falls within
                       +/-48h of any gossip-bus thread tagged incident/P1
                       (bus subjects/threads containing 'incident', '-p1'
                       or 'p1-').

  weight = 50*corr_density/(corr_density+CORR_SQUASH_K)   (half-sat 25/MB)
         + 50*err_density/(err_density+ERR_SQUASH_K)      (half-sat 200/MB)
         + WEIGHT_PER_DAY * min(days_since_last_replay, RECENCY_CAP)
         + (INCIDENT_BONUS if incident-proximate else 0)

  The two squashes are half-saturation curves calibrated to the 2026-10-11
  pool distribution (corr/MB p50=6 p99=79; err/MB p50=107 p99=409) so both
  terms spread across the pool instead of pinning at a hard cap.

Cost bound: at most SCAN_CAP_BYTES of each file is read (byte counting in
chunks, no JSON parsing) and densities normalize by MB actually scanned.

Output:
  dreams/data/<date>-replay.json   the manifest (3 sessions, weights, one-
                                   line reasons, eligible-pool size)
  garden-reports/replay-state.json sampled-session guard (30-day no-repeat)
  dreams/bus/replay-sampler.jsonl  one 'finding' row announcing the manifest

REPORTS ONLY. It does NOT rewire the dreamer, touch config, crons, plists,
or any schedule (never_auto constitutional — wiring is Josh's call after he
reads the manifest).

Usage: replay-sample.py [--n 3] [--dry-run]
"""

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atomic_io import atomic_write          # noqa: E402

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, ".claude", "projects")
K = os.path.join(HOME, ".claude", "knowledge")
CONFIG = os.path.join(K, "dreams", "config.json")
BUS = os.path.join(K, "dreams", "bus")
OUT_DIR = os.path.join(K, "dreams", "data")
STATE = os.path.join(K, "garden-reports", "replay-state.json")

# tunables (documented in the module docstring)
SCAN_CAP_BYTES = 20_000_000      # per-file scan cap; density normalizes to this
CORR_SQUASH_K = 25.0             # corr-density half-saturation point (per MB)
ERR_SQUASH_K = 200.0             # err-density half-saturation point (per MB)
WEIGHT_PER_DAY = 0.02            # spacing credit per day since last replay
RECENCY_CAP_DAYS = 90            # never-sampled sessions get this credit max
INCIDENT_BONUS = 2.0
INCIDENT_HALO_H = 48             # +/- hours around an incident-tagged thread
REPEAT_GUARD_DAYS = 30           # never sample the same session twice in 30d
N_DEFAULT = 3

ERROR_SIGS = [b"Error:", b"error:", b"ERROR", b"failed", b"Failed",
              b"FAILED", b"Traceback", b"permission", b"denied",
              b"EACCES", b"EPERM"]
CORRECTION_SIGS = [b"I said", b"not that", b"revert", b"undo",
                   b"that's wrong", b"thats wrong", b"you broke",
                   b"why did you", b"I meant"]


def load_config():
    try:
        with open(CONFIG) as f:
            return json.load(f)
    except Exception:
        return {}


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {"sampled": {}, "manifest_history": []}


def incident_dates():
    """Dates (datetime) of bus rows whose subject/thread is tagged
    incident/P1: contains 'incident', '-p1' or 'p1-' (lowercased)."""
    out = []
    if not os.path.isdir(BUS):
        return out
    for name in os.listdir(BUS):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(BUS, name), errors="replace") as f:
            for line in f:
                if "incident" not in line and "p1" not in line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tagfield = str(r.get("subject", "")) + " " + str(r.get("thread", ""))
                low = tagfield.lower()
                if "incident" in low or "-p1" in low or "p1-" in low:
                    try:
                        t = dt.datetime.fromisoformat(
                            str(r.get("ts", "")).replace("Z", "+00:00"))
                        out.append(t.replace(tzinfo=None))  # normalize naive-UTC
                    except ValueError:
                        continue
    return out


def cheap_counts(path):
    """One bounded binary pass; returns (err_hits, corr_hits, mb_scanned).
    Byte .count on raw chunks — no JSON parsing, no line iteration."""
    err = corr = 0
    scanned = 0
    try:
        size = os.path.getsize(path)
    except OSError:
        return 0, 0, 0.0
    n = min(size, SCAN_CAP_BYTES)
    try:
        with open(path, "rb") as f:
            CH = 1 << 20
            left = n
            while left > 0:
                chunk = f.read(min(CH, left))
                if not chunk:
                    break
                left -= len(chunk)
                scanned += len(chunk)
                for s in ERROR_SIGS:
                    err += chunk.count(s)
                for s in CORRECTION_SIGS:
                    corr += chunk.count(s)
    except OSError:
        return 0, 0, 0.0
    return err, corr, scanned / 1_000_000.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=N_DEFAULT)
    ap.add_argument("--dry-run", action="store_true",
                    help="print the manifest, write nothing (not even state)")
    args = ap.parse_args()

    cfg = load_config()
    window_days = int(cfg.get("mine_days_back", 3))
    cutoff = dt.datetime.now() - dt.timedelta(days=window_days)

    state = load_state()
    now = dt.datetime.now(dt.timezone.utc)
    sampled = state.get("sampled", {})
    guard_cutoff = now - dt.timedelta(days=REPEAT_GUARD_DAYS)

    incidents = incident_dates()

    # ---- eligible pool: old enough to be outside the dreamer window AND
    # not sampled within REPEAT_GUARD_DAYS
    eligible = []
    skipped_recently_sampled = 0
    for proj in sorted(os.listdir(PROJECTS)):
        pdir = os.path.join(PROJECTS, proj)
        if not os.path.isdir(pdir):
            continue
        for name in os.listdir(pdir):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(pdir, name)
            try:
                mtime = dt.datetime.fromtimestamp(
                    os.path.getmtime(path), dt.timezone.utc)
            except (OSError, ValueError):
                continue
            if mtime.replace(tzinfo=None) >= cutoff.replace(tzinfo=None):
                continue                                  # inside dreamer window
            last = sampled.get(path)
            if last:
                try:
                    if dt.datetime.fromisoformat(last) > guard_cutoff:
                        skipped_recently_sampled += 1
                        continue                          # 30-day guard
                except ValueError:
                    pass                                  # corrupt guard row: ignore
            eligible.append((path, mtime))

    # ---- score every eligible session (cheap bounded scan)
    scored = []
    for path, mtime in eligible:
        err, corr, mb = cheap_counts(path)
        corr_d = corr / mb if mb else 0.0
        err_d = err / mb if mb else 0.0
        last = sampled.get(path)
        if last:
            try:
                days_since = (now - dt.datetime.fromisoformat(last)).days
            except ValueError:
                days_since = RECENCY_CAP_DAYS
        else:
            days_since = RECENCY_CAP_DAYS                 # never replayed
        mtime_naive = mtime.replace(tzinfo=None)
        near_incident = any(
            abs((mtime_naive - i).total_seconds()) <= INCIDENT_HALO_H * 3600
            for i in incidents)
        weight = (50 * corr_d / (corr_d + CORR_SQUASH_K)
                  + 50 * err_d / (err_d + ERR_SQUASH_K)
                  + WEIGHT_PER_DAY * min(days_since, RECENCY_CAP_DAYS)
                  + (INCIDENT_BONUS if near_incident else 0.0))
        scored.append({
            "session": path,
            "project": os.path.basename(os.path.dirname(path)),
            "mtime": mtime.strftime("%Y-%m-%d %H:%MZ"),
            "age_days": (now - mtime).days,
            "size_mb": round(mb, 1),
            "corr_hits": corr, "corr_density_per_mb": round(corr_d, 2),
            "err_hits": err, "err_density_per_mb": round(err_d, 2),
            "days_since_last_replay": days_since,
            "incident_proximate": near_incident,
            "weight": round(weight, 3),
        })

    scored.sort(key=lambda s: -s["weight"])
    picked = scored[:args.n]
    under_pool = len(eligible) < args.n

    for s in picked:
        bits = []
        if s["corr_hits"]:
            bits.append(f"{s['corr_hits']} correction-marker hits "
                        f"({s['corr_density_per_mb']}/MB)")
        if s["err_hits"]:
            bits.append(f"{s['err_hits']} error-signature hits "
                        f"({s['err_density_per_mb']}/MB)")
        bits.append(f"unreplayed {s['days_since_last_replay']}d")
        if s["incident_proximate"]:
            bits.append("within +/-48h of an incident/P1 bus thread")
        s["reason"] = "; ".join(bits) or "old and never replayed"

    manifest = {
        "generated": now.isoformat(timespec="seconds"),
        "kind": "replay-manifest",
        "note": ("REPORT ONLY — names old sessions for a re-mine; the "
                 "dreamer is NOT rewired by this tool (never_auto)."),
        "dreamer_window_days": window_days,
        "eligible_pool": len(eligible),
        "skipped_within_30d_guard": skipped_recently_sampled,
        "under_pool": under_pool,
        "weights_formula": ("50*corr_d/(corr_d+25) + 50*err_d/(err_d+200)"
                            " + 0.02*min(days_since_last_replay,90)"
                            " + 2.0 if incident +/-48h"),
        "sampled": picked,
    }

    stamp = dt.date.today().isoformat()
    out_path = os.path.join(OUT_DIR, f"{stamp}-replay.json")
    if under_pool:
        print(f"NOTE: only {len(eligible)} eligible old sessions exist "
              f"(< {args.n} requested) — sampled fewer, as specified.")
    if args.dry_run:
        print(json.dumps(manifest, indent=1))
        return 0

    os.makedirs(OUT_DIR, exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(manifest, f, indent=1)
    os.replace(tmp, out_path)

    # ---- state guard update (atomic whole-file write)
    for s in picked:
        sampled[s["session"]] = now.isoformat(timespec="seconds")
    state["sampled"] = sampled
    state["manifest_history"] = (
        state.get("manifest_history", [])[-59:]
        + [{"date": stamp, "manifest": out_path, "n": len(picked)}])
    atomic_write(STATE, json.dumps(state, indent=1))

    # ---- announce on the gossip bus (kind: finding, refs the manifest)
    try:
        import bus_post
        rec = bus_post.post(
            agent="replay-sampler", type_="finding",
            subject=f"replay-manifest-{stamp}",
            fields={
                "claim": (f"replay manifest {stamp}: {len(picked)} old "
                          f"sessions selected for re-mining "
                          f"(pool {len(eligible)}, guard-skipped "
                          f"{skipped_recently_sampled}); dreamer NOT rewired"),
                "confidence": "observed",
                "refs": [out_path],
            })
        bus_row = rec.get("ts", "")
    except Exception as e:
        bus_row = f"FAILED: {e!r}"

    print(out_path)
    for s in picked:
        print(f"  w={s['weight']:7.3f}  {s['mtime']}  "
              f"{s['project'][-45:]}  {os.path.basename(s['session'])[:14]}")
    print(f"  bus: {bus_row}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
