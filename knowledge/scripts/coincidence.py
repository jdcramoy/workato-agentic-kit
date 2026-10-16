#!/usr/bin/env python3
"""coincidence.py — cadence-aware multimessenger coincidence scorer for the
gossip bus + watchdog findings. (Wave-3, builder C, amendment 5.)

READ-ONLY TOOL. It writes NOTHING to the bus, makes NO trust-ladder
escalation, and mutates nothing (the single exception is the explicit
--bootstrap-registry flag, which writes only the owned registry file).

WHY CADENCE-AWARE
  The fleet's scheduled jobs are 100-130 minutes apart (watchdog 23:13,
  gardener 22:43, docs-watch 22:31, evidence 00:53). A fixed +/-10 min
  coincidence window is structurally dead for exactly the incident class
  this tool exists for (channels on different schedules catching the same
  condition). So the window is set by the SLOWER channel's time resolution:
  per channel, a background interval is estimated from ITS OWN history
  (median gap between consecutive same-class posts, falling back to the
  registry's interval_min), and the coincidence window for a pair is
  max(min_window, 1.5 x interval_A, 1.5 x interval_B).

SCORING (amendment 5)
  - Per-channel background rate lambda_i from that channel's own history
    (same-class events per day over the window).
  - p_i = 1 - exp(-lambda_i * w_days): probability of seeing >= 1 same-class
    event from channel i inside its cadence window by chance.
  - Same-class events from DIFFERENT channels inside the pairwise window
    form a candidate; connected candidates form a component.
  - SYSTEMATICS: channels sharing a dependency-registry upstream edge (same
    source doc, same upstream script, same data directory) are ONE group.
    Each systematic GROUP contributes ONCE to the joint score — two agents
    watching the same wt-health probe are one instrument, not two.
  - Joint score = SUM over independent groups of ln(p_group), where
    p_group = min p_i in the group. More negative = more significant.

REGISTRY
  knowledge/dreams/bus/channels-registry.jsonl (NOTE: dreams/bus/, not
  knowledge/bus/ — the dissenter's naming correction). One row per channel:
    {"channel": "bus:workato-watchdog", "interval_min": 1440,
     "upstreams": ["script:...", "dir:...", "doc:..."], "note": "..."}
  Channels absent from the registry are scored as independent and flagged
  "unregistered". --bootstrap-registry seeds it from measured history plus
  the builder's evidence-based seed edges.

SURFACES (amendment 5: high-frequency only)
  Bus outboxes (dreams/bus/*.jsonl, merged via gossip-read.py's loader —
  imported, not duplicated) + the watchdog's machine-readable findings
  ledger (predictions.jsonl, agent=watchdog). Scheduled-job heartbeats are
  deliberately OUT of scope.

HEALTH METRICS
  - time-to-confirm: per thread, first finding -> first evidence-bearing
    corroboration from a DIFFERENT agent (gossip-read's has_own_evidence).
  - coincidence starvation: a window with zero multi-channel coincidences
    is reported as starved (the guard, report-only).

Usage:
  coincidence.py [--since 7d] [--bus DIR] [--registry PATH] [--json]
                 [--min-window-min 10] [--cadence-mult 1.5]
                 [--bootstrap-registry] [--selftest]

Exit 0 on success; non-zero + stderr on failure.
"""

import argparse
import importlib.util
import json
import os
import re
import statistics
import sys
import tempfile
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atomic_io import atomic_write  # noqa: E402  (read-only import, contract)

KB = os.path.expanduser("~/.claude/knowledge")
BUS = os.path.join(KB, "dreams", "bus")
REGISTRY = os.path.join(KB, "dreams", "bus", "channels-registry.jsonl")
PREDICTIONS = os.path.join(KB, "predictions", "predictions.jsonl")

_gossip_spec = importlib.util.spec_from_file_location(
    "gossip_read", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "gossip-read.py"))
_gossip = importlib.util.module_from_spec(_gossip_spec)
_gossip_spec.loader.exec_module(_gossip)

# Seed upstream edges for --bootstrap-registry. Only edges visible in the
# knowledge tree itself — no invented infrastructure. Channels sharing an
# edge score as ONE systematic group.
SEED_EDGES = {
    "bus:workato-watchdog": ["script:launchd.com.josh.fleet.workato-watchdog",
                             "dir:knowledge/watchdog-reports",
                             "tool:wt-health"],
    "bus:workato-health": ["tool:wt-health",
                           "dir:knowledge/workato-health"],
    "predictions:watchdog": ["script:launchd.com.josh.fleet.workato-watchdog",
                             "dir:knowledge/watchdog-reports",
                             "tool:wt-health"],
    "bus:brain-gardener": ["script:launchd.brain-gardener",
                           "dir:knowledge/garden-reports"],
    "bus:harness-dreamer": ["script:dream-nightly.sh",
                            "dir:knowledge/dreams"],
    "bus:project-dreamer": ["dir:knowledge/dreams"],
    "bus:session-shadow": ["file:knowledge/now/josh-now.md",
                           "script:launchd.session-shadow"],
    "bus:dissenter": ["dir:knowledge/reviews"],
    "bus:cortex": ["consumes:knowledge/dreams/bus"],
    "bus:evidence": ["consumes:session-transcripts"],
    "bus:replay-sampler": ["dir:knowledge/dreams/data"],
    "bus:prediction-errors": ["script:predict.py-hook"],
}


def parse_ts(v):
    """Robust epoch for the ts formats actually on the bus:
    2026-10-07T22:30Z | 2026-10-09T00:24:16 | 2026-10-11T17:35:02-0400 | Z."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    t = s.replace("Z", "+0000")
    m = re.search(r"([+-])(\d{2})(\d{2})$", t)
    if m:
        t = t[:m.start()] + f"{m.group(1)}{m.group(2)}:{m.group(3)}"
    if len(t) == 16 and "T" in t:      # 2026-10-07T22:30
        t += ":00"
    for f in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
              "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(t, f)
            if dt.tzinfo is not None:
                # normalize to UTC before dropping tzinfo so offset formats
                # and Z formats land on the same epoch base
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt.timestamp()
        except Exception:
            continue
    try:
        return datetime.fromisoformat(t).timestamp()
    except Exception:
        return None


def class_of(ev):
    """Signal class: the event's kind (fallback: type)."""
    k = ev.get("kind") or ev.get("type")
    return k if isinstance(k, str) and k.strip() else "unclassified"


def load_channels(since, bus_dir, predictions_path):
    """Merge bus outboxes (via gossip-read's loader) + the watchdog findings
    ledger. Returns channel_id -> [(epoch, event)] and a counts dict."""
    cutoff = _gossip.parse_since(since)
    channels = {}
    n_bad_ts = 0

    def add(ch, ev):
        nonlocal n_bad_ts
        ts = parse_ts(ev.get("ts"))
        if ts is None:
            n_bad_ts += 1
            return
        channels.setdefault(ch, []).append((ts, ev))

    for ev in _gossip.load_events(bus_dir, since):
        add(f"bus:{ev.get('agent', '?')}", ev)
    if os.path.exists(predictions_path):
        with open(predictions_path, errors="replace") as fh:
            for ln, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                t = parse_ts(ev.get("ts"))
                if t is not None and t < cutoff:
                    continue
                add(f"predictions:{ev.get('agent', '?')}", ev)
    for ch in channels:
        channels[ch].sort(key=lambda x: x[0])
    return channels, n_bad_ts


def cadence(channels, registry):
    """Per (channel, class) background interval (min) + rate (events/day).
    interval = median gap of consecutive same-class posts; fallback to the
    channel's registry interval_min; fallback DEFAULT_INTERVAL."""
    DEFAULT = 1440.0
    out = {}
    now = datetime.now(timezone.utc).timestamp()
    for ch, evs in channels.items():
        span_days = max((now - evs[0][0]) / 86400.0, 0.5)
        reg = registry.get(ch, {})
        ch_default = float(reg.get("interval_min", DEFAULT))
        by_class = {}
        for ts, ev in evs:
            by_class.setdefault(class_of(ev), []).append(ts)
        for cls, tss in by_class.items():
            gaps = [(b - a) / 60.0 for a, b in zip(tss, tss[1:]) if b > a]
            interval = statistics.median(gaps) if gaps else ch_default
            out[(ch, cls)] = {
                "interval_min": max(interval, 1.0),
                "n": len(tss),
                "rate_per_day": len(tss) / span_days,
            }
    return out


def load_registry(path):
    reg = {}
    if not os.path.exists(path):
        return reg
    with open(path, errors="replace") as fh:
        for ln, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                print(f"warn: registry {os.path.basename(path)}:{ln} unparsable",
                      file=sys.stderr)
                continue
            ch = r.get("channel")
            if ch:
                reg[ch] = r
    return reg


def find_coincidences(channels, cad, registry, min_window_min, mult):
    """Same-class multi-channel components. Returns report structures."""
    min_w = float(min_window_min)
    by_class = {}
    for (ch, cls), _ in cad.items():
        pass  # (cad is derived; group events directly)
    for ch, evs in channels.items():
        for ts, ev in evs:
            by_class.setdefault(class_of(ev), []).append((ch, ts, ev))

    results = []
    for cls, items in sorted(by_class.items()):
        if len({ch for ch, _, _ in items}) < 2:
            continue
        parent = list(range(len(items)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            parent[find(x)] = find(y)

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                (ca, ta, _), (cb, tb, _) = items[i], items[j]
                if ca == cb:
                    continue
                wa = mult * cad.get((ca, cls), {}).get("interval_min", 1440)
                wb = mult * cad.get((cb, cls), {}).get("interval_min", 1440)
                w = max(min_w, wa, wb)
                if abs(ta - tb) <= w * 60.0:
                    union(i, j)

        comps = {}
        for i, item in enumerate(items):
            comps.setdefault(find(i), []).append(item)

        for members in comps.values():
            chans = sorted({ch for ch, _, _ in members})
            if len(chans) < 2:
                continue
            # systematic groups: union-find channels by shared upstream edge
            up = {c: set(registry.get(c, {}).get("upstreams", [])) for c in chans}
            cparent = {c: c for c in chans}

            def cfind(x):
                while cparent[x] != x:
                    cparent[x] = cparent[cparent[x]]
                    x = cparent[x]
                return x

            for a in chans:
                for b in chans:
                    if a < b and up[a] & up[b]:
                        cparent[cfind(a)] = cfind(b)
            groups = {}
            for c in chans:
                groups.setdefault(cfind(c), []).append(c)
            # per group p: min p_i of its channels (p_i = 1 - exp(-lambda*w_i))
            group_rows = []
            for gchans in groups.values():
                p_min, w_min = 1.0, None
                for c in gchans:
                    ccd = cad.get((c, cls), {})
                    lam = ccd.get("rate_per_day", 0.0)
                    w_days = (max(min_w, mult * ccd.get("interval_min", 1440))
                              / 1440.0)
                    p = 1.0 - pow(2.718281828459045, -lam * w_days)
                    if p < p_min:
                        p_min, w_min = p, (c, w_days)
                group_rows.append({"channels": gchans, "p": round(p_min, 6),
                                   "lambda_channel": w_min[0] if w_min else None})
            score = sum(__import__("math").log(max(g["p"], 1e-12))
                        for g in group_rows)
            joint_p = 1.0
            for g in group_rows:
                joint_p *= (1.0 - g["p"])
            joint_p = 1.0 - joint_p
            tss = [t for _, t, _ in members]
            max_w = max(max(min_w, mult * cad.get((c, cls), {}).get("interval_min", 1440))
                        for c in chans)
            span_min = (max(tss) - min(tss)) / 60.0
            results.append({
                "class": cls,
                "channels": chans,
                "span_min": round(span_min, 1),
                "n_events": len(members),
                "systematic_groups": len(groups),
                "group_rows": group_rows,
                "score_ln_p": round(score, 3),
                "joint_p_approx": round(joint_p, 8),
                "shared_edges": sorted(set().union(*[up[c] for c in chans])) if len(groups) < len(chans) else [],
                # dense classes chain transitively through the pairwise windows;
                # when the span dwarfs the window this is background rate, not
                # one burst — say so instead of crying wolf (report-only tool)
                "chained_background": span_min > 3.0 * max_w,
                "snippet": (str(members[0][2].get("subject")
                                or members[0][2].get("thread")
                                or members[0][2].get("thread_id")
                                or members[0][2].get("line")
                                or members[0][2].get("note") or ""))[:80],
            })
    results.sort(key=lambda r: r["score_ln_p"])
    return results


def unconfirmed_bursts(channels, cad, min_window_min, mult):
    """'Interesting but unconfirmed' tier: same-class BURSTS from ONE channel
    (>= 2 same-class events within that channel's own cadence window) that no
    other channel corroborated. Report-level visibility only."""
    bursts = []
    for (ch, cls), ccd in sorted(cad.items()):
        evs = channels.get(ch, [])
        w_min = max(min_window_min, mult * ccd["interval_min"])
        tss = [t for t, ev in evs if class_of(ev) == cls]
        if len(tss) < 2:
            continue
        run = [tss[0]]
        runs = []
        for t in tss[1:]:
            if (t - run[-1]) <= w_min * 60.0:
                run.append(t)
            else:
                if len(run) >= 2:
                    runs.append(run)
                run = [t]
        if len(run) >= 2:
            runs.append(run)
        for r in runs:
            bursts.append({"channel": ch, "class": cls, "n": len(r),
                           "span_min": round((r[-1] - r[0]) / 60.0, 1),
                           "window_min": round(w_min, 1),
                           "last_ts": time.strftime(
                               "%Y-%m-%dT%H:%M:%SZ", time.gmtime(r[-1]))})
    bursts.sort(key=lambda b: -b["n"])
    return bursts


def time_to_confirm(channels):
    """Per thread: first finding -> first evidence-bearing corroboration from
    a DIFFERENT agent (gossip-read helpers, bus channels only)."""
    threads = {}
    for ch, evs in channels.items():
        if not ch.startswith("bus:"):
            continue
        for ts, ev in evs:
            tid = _gossip.thread_of(ev)
            if tid:
                threads.setdefault(tid, []).append((ts, ev.get("agent"), ev))
    latencies = []
    for tid, evs in threads.items():
        finders = [e for e in evs if e[2].get("kind") == "finding"]
        if not finders:
            continue
        first = min(finders, key=lambda x: x[0])
        corr = [e for e in evs
                if e[0] >= first[0]
                and e[1] != first[1]
                and e[2].get("kind") in ("verify", "corroboration", "finding")
                and _gossip.has_own_evidence(e[2])]
        if corr:
            nxt = min(corr, key=lambda x: x[0])
            latencies.append((nxt[0] - first[0]) / 60.0)
    if not latencies:
        return {"n_threads_confirmed": 0, "median_min": None}
    return {"n_threads_confirmed": len(latencies),
            "median_min": round(statistics.median(latencies), 1),
            "max_min": round(max(latencies), 1)}


def bootstrap_registry(channels, path):
    """Write initial registry rows: measured interval + seed upstream edges."""
    now = datetime.now(timezone.utc).timestamp()
    rows = []
    for ch in sorted(channels):
        evs = channels[ch]
        gaps = [(b - a) / 60.0 for (a, _), (b, _) in zip(evs, evs[1:]) if b > a]
        interval = round(statistics.median(gaps), 1) if gaps else 1440
        rows.append({"channel": ch, "interval_min": interval,
                     "upstreams": SEED_EDGES.get(ch, []),
                     "note": "seeded 2026-10-11 wave-3 builder C: interval from "
                             "measured history, upstreams from knowledge-tree "
                             "evidence" if SEED_EDGES.get(ch) else
                             "seeded 2026-10-11 wave-3 builder C: interval from "
                             "measured history; no upstream edges identified",
                     "first_seen": time.strftime(
                         "%Y-%m-%dT%H:%M:%SZ", time.gmtime(evs[0][0])),
                     "last_seen": time.strftime(
                         "%Y-%m-%dT%H:%M:%SZ", time.gmtime(evs[-1][0])),
                     "n_events": len(evs), "measured_at": now})
    atomic_write(path, "".join(json.dumps(r, ensure_ascii=False) + "\n"
                               for r in rows))
    return rows


# ---------------------------------------------------------------- selftest

def selftest():
    tmp = tempfile.mkdtemp(prefix="coincidence-selftest-")
    results = []

    def check(name, cond):
        results.append((name, bool(cond)))

    def row(ts, agent, kind, subject, line="evidence: job 123 trace"):
        return json.dumps({"ts": ts, "agent": agent, "kind": kind,
                           "subject": subject, "line": line})

    bus = os.path.join(tmp, "bus")
    os.makedirs(bus)
    # All channels post every ~30 min (tight cadence -> window ~45 min).
    # A and B post the same-class signal 20 min apart -> coincidence;
    # they share upstream "probe:x" -> ONE systematic group.
    # C posts the same class 12h away -> OUTSIDE the window -> separate.
    def filler(fh, agent, hours):
        for h in range(hours):
            for mm in (0, 30):
                fh.write(row(f"2026-10-11T{h:02d}:{mm:02d}:00Z", agent,
                             f"noise-{agent}", f"routine-{agent}-{h}-{mm}") + "\n")
    with open(os.path.join(bus, "a.jsonl"), "w") as fh:
        filler(fh, "a", 24)
        fh.write(row("2026-10-11T10:00:00Z", "a", "finding", "probe-x-flap") + "\n")
    with open(os.path.join(bus, "b.jsonl"), "w") as fh:
        filler(fh, "b", 24)
        fh.write(row("2026-10-11T10:20:00Z", "b", "finding", "probe-x-flap-echo") + "\n")
    with open(os.path.join(bus, "c.jsonl"), "w") as fh:
        filler(fh, "c", 24)
        fh.write(row("2026-10-11T22:00:00Z", "c", "finding", "unrelated-later") + "\n")

    reg_path = os.path.join(tmp, "registry.jsonl")
    with open(reg_path, "w") as fh:
        fh.write(json.dumps({"channel": "bus:a", "interval_min": 30,
                             "upstreams": ["probe:x"]}) + "\n")
        fh.write(json.dumps({"channel": "bus:b", "interval_min": 30,
                             "upstreams": ["probe:x"]}) + "\n")
        fh.write(json.dumps({"channel": "bus:c", "interval_min": 30,
                             "upstreams": ["probe:y"]}) + "\n")

    chans, _ = load_channels("1d", bus, os.path.join(tmp, "none.jsonl"))
    check("loader sees all 3 channels", len(chans) == 3)
    check("ts parser handles Z-less format", parse_ts("2026-10-11T10:20:00") is not None)
    check("ts parser handles -0400 offset",
          abs((parse_ts("2026-10-11T10:20:00-0400") or 0)
              - (parse_ts("2026-10-11T14:20:00Z") or 1)) < 61)

    reg = load_registry(reg_path)
    cd = cadence(chans, reg)
    coinc = find_coincidences(chans, cd, reg, min_window_min=10, mult=1.5)
    check("one coincidence component found", len(coinc) == 1)
    if coinc:
        c = coinc[0]
        check("component is A+B", set(c["channels"]) == {"bus:a", "bus:b"})
        check("shared upstream collapses to ONE systematic group",
              c["systematic_groups"] == 1)
        check("score is one ln(p) term (negative)", c["score_ln_p"] < 0)
        check("span reported ~20 min", 19 <= c["span_min"] <= 21)
    # C's event alone: no partner in window -> not a coincidence
    check("far-apart channel not merged", all(
        set(c["channels"]) != {"bus:a", "bus:b", "bus:c"} for c in coinc))

    ttc = time_to_confirm(chans)
    check("time-to-confirm sees A's finding (no corroborator yet)",
          ttc["n_threads_confirmed"] == 0)

    # read-only guarantee: running the full pipeline changes nothing on disk
    before = sorted(os.listdir(bus))
    find_coincidences(chans, cd, reg, 10, 1.5)
    check("read-only: bus untouched", before == sorted(os.listdir(bus)))

    failed = [n for n, ok in results if not ok]
    for n, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print(f"selftest: {len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(
        description="READ-ONLY cadence-aware multimessenger coincidence scorer "
                    "over bus events + watchdog findings. Windows are per-channel "
                    "interval x 1.5 (NOT fixed +/-10 min — the fleet's scheduled "
                    "jobs are 100-130 min apart). Channels sharing a registry "
                    "upstream edge count as ONE systematic group in the joint "
                    "score SUM ln(p_i). Report-only: no trust-ladder escalation, "
                    "no bus writes (amendment 5).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="7d", help="analysis window: 24h|7d|all")
    ap.add_argument("--bus", default=BUS,
                    help="bus directory override (tests only; never written)")
    ap.add_argument("--registry", default=REGISTRY,
                    help="channel dependency registry path")
    ap.add_argument("--predictions", default=PREDICTIONS,
                    help="watchdog findings ledger path (set to /dev/null to skip)")
    ap.add_argument("--min-window-min", type=float, default=10.0,
                    help="floor on any coincidence window (default 10)")
    ap.add_argument("--cadence-mult", type=float, default=1.5,
                    help="window = cadence_mult x channel interval (default 1.5)")
    ap.add_argument("--bootstrap-registry", action="store_true",
                    help="ONE-TIME: write initial registry rows from measured "
                         "history + seed edges. The only mode that writes.")
    ap.add_argument("--json", action="store_true", help="machine-readable report")
    ap.add_argument("--selftest", action="store_true", help="synthetic-data self test")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    try:
        chans, n_bad_ts = load_channels(a.since, a.bus, a.predictions)
        registry = load_registry(a.registry)
        if a.bootstrap_registry:
            rows = bootstrap_registry(chans, a.registry)
            print(f"registry seeded: {len(rows)} channels -> {a.registry}")
            for r in rows:
                print(f"  {r['channel']:36} interval={r['interval_min']:>9} min  "
                      f"upstreams={len(r['upstreams'])}")
            return 0
        cd = cadence(chans, registry)
        coinc = find_coincidences(chans, cd, registry, a.min_window_min,
                                  a.cadence_mult)
        unconf = unconfirmed_bursts(chans, cd, a.min_window_min, a.cadence_mult)
        ttc = time_to_confirm(chans)
    except OSError as e:
        print(f"coincidence.py: {e}", file=sys.stderr)
        return 1

    n_unreg = len([c for c in chans if c not in registry])
    report = {
        "mode": "report-only (read-only tool)",
        "window": a.since,
        "channels_seen": len(chans),
        "unregistered_channels": n_unreg,
        "events_without_ts_skipped": n_bad_ts,
        "coincidences": coinc,
        "interesting_but_unconfirmed": unconf,
        "time_to_confirm": ttc,
        "starved": len(coinc) == 0,
    }

    if a.json:
        print(json.dumps(report, indent=1))
        return 0

    print(f"coincidence: window={a.since} channels={len(chans)} "
          f"unregistered={n_unreg} (report-only; no escalation, no bus writes)")
    if not coinc:
        print("  NO multi-channel coincidence in window — coincidence-"
              "starvation guard: if this persists across windows, the window "
              "or the class taxonomy may be miscalibrated.")
    for c in coinc:
        groups = " + ".join(",".join(g["channels"]) for g in c["group_rows"])
        flag = "  [chained background: span >> window — not an alarm]" \
            if c.get("chained_background") else ""
        print(f"  class={c['class']:14} span={c['span_min']:>8} min  "
              f"score={c['score_ln_p']:>9}  joint_p~{c['joint_p_approx']}{flag}")
        print(f"    channels ({c['systematic_groups']} systematic group(s)): {groups}")
        if c["shared_edges"]:
            print(f"    shared systematics: {', '.join(c['shared_edges'])}")
        print(f"    {c['n_events']} events, e.g. {c['snippet']}")
    print(f"time-to-confirm: {ttc['n_threads_confirmed']} threads confirmed"
          + (f", median {ttc['median_min']} min" if ttc["median_min"] is not None
             else " (none evidence-bearing yet)"))
    if unconf:
        print("interesting but unconfirmed (single-channel same-class bursts, "
              f"{len(unconf)}):")
        for b in unconf[:5]:
            print(f"  {b['channel']:28} class={b['class']:14} n={b['n']:>4}  "
                  f"span={b['span_min']:>8} min  last={b['last_ts']}")
        if len(unconf) > 5:
            print(f"  ... +{len(unconf) - 5} more (use --json for all)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
