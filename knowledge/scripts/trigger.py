#!/usr/bin/env python3
"""trigger.py — L0 trigger hierarchy: prescaled event-class scanner with a
minimum-bias bypass and a novel stream. (Wave-3, builder C, amendment 3.)

WHAT IT IS
  A zero-LLM, stdlib-only L0 layer over the fleet's JSONL event surfaces
  (bus outboxes, triage queue, garden ledgers, predictions). It:

    1. scans the surfaces listed in the trigger menu (GLOB patterns, so new
       event surfaces are added by config, not code),
    2. classifies each event against the menu's classes (signatures:
       error text, conflict count > 1, numeric cost anomaly > 2 sigma,
       verification-failure vocabulary),
    3. applies per-class prescales (accept 1/N, record the factor) with an
       EXPRESS line: prod-touching / P0-citing events are never prescaled,
    4. enforces the COUNT FLOOR on the minimum-bias bypass: if the sampled
       set is below min_bias_floor_per_day (default 10/day) the ENTIRE
       stream bypasses sampling (prescale 1 for everything) — never an
       empty sample,
    5. routes events matching NO known class to the novel stream at
       prescale 1, rate-bounded per run.

  Output: knowledge/events/trigger-log.jsonl — a run summary row with
  UNFOLDED counts (raw x prescale, with the sampled n noted) plus one row
  per sampled event. knowledge/events/novel-stream.jsonl — novel events.

THE DREAMER STAYS FULL-CORPUS
  trigger.py consumes event LEDGERS (machine rows), never session
  transcripts. The dreamer's transcript mining is untouched: prose cannot
  be prescale-unfolded (a repeats signal degrades 1/N under sampling), so
  L0 deliberately does not sit on the dreamer's input path.

HIERARCHY (only L0 is built)
  L0  THIS TOOL. stdlib metadata scanner, zero LLM calls.
  L1  FUTURE (documented, not built): cheap-model salience/novelty scoring
      on L0 survivors only. Wire point: feed trigger-log sample rows to an
      L1 scorer; needs the integrator's model-budget wiring.
  L2  FUTURE (documented, not built): full dreamer/fusion analysis on
      top-N L1 survivors. Never wire L2 to prescaled dreamer input — the
      dreamer reads full corpus (see above).

Usage:
  trigger.py [--since 24h|7d|all] [--config PATH] [--dry-run] [--json]
             [--seed N] [--log PATH] [--novel PATH] [--selftest]

Exit 0 on success; non-zero + stderr on failure.
"""

import argparse
import glob
import hashlib
import json
import os
import random
import re
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atomic_io import atomic_append  # noqa: E402  (read-only import, contract)

KB = os.path.expanduser("~/.claude/knowledge")
DEFAULT_CONFIG = os.path.join(KB, "config", "trigger", "prescales.json")
DEFAULT_LOG = os.path.join(KB, "events", "trigger-log.jsonl")
DEFAULT_NOVEL = os.path.join(KB, "events", "novel-stream.jsonl")


def parse_since(s):
    if not s or s == "all":
        return 0.0, time.time()
    now = time.time()
    if s.endswith("h"):
        return now - float(s[:-1]) * 3600, now
    if s.endswith("d"):
        return now - float(s[:-1]) * 86400, now
    raise ValueError(f"unparsable --since: {s!r} (use 24h|7d|all)")


def parse_ts(v):
    """Robust epoch for the ts formats actually in the ledgers:
    2026-10-07T22:30Z | 2026-10-09T00:24:16 | 2026-10-11T17:35:02-0400 | ..."""
    if not isinstance(v, str):
        return None
    s = v.strip()
    fmts = ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M",
            "%Y-%m-%d", "%Y-%m-%d %H:%M:%S")
    t = s.replace("Z", "+0000")
    m = re.search(r"([+-])(\d{2})(\d{2})$", t)  # -0400 -> -04:00
    if m:
        t = t[:m.start()] + f"{m.group(1)}{m.group(2)}:{m.group(3)}"
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$", t):
        t += ":00"
    t = t.replace(" ", "T", 1) if " " in s[:10] else t
    for f in fmts:
        try:
            return time.mktime(time.strptime(t, f))
        except Exception:
            continue
    try:  # date-only ledgers
        return time.mktime(time.strptime(s[:10], "%Y-%m-%d"))
    except Exception:
        return None


def gather_text(ev, depth=1):
    """All string content one level deep — for signature matching."""
    out = []
    stack = [ev]
    for _ in range(depth + 1):
        nxt = []
        for item in stack:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                nxt.extend(item.values())
            elif isinstance(item, (list, tuple)):
                nxt.extend(item)
        stack = nxt
    return " \n ".join(x for x in out if isinstance(x, str))


def load_config(path):
    with open(path) as fh:
        cfg = json.load(fh)
    for key in ("menu_version", "surfaces", "classes"):
        if key not in cfg:
            raise ValueError(f"{path}: menu missing required key {key!r}")
    return cfg


def compile_classes(cfg):
    """Precompile the menu: regexes + extractor tables per class."""
    compiled = {}
    for name, c in cfg["classes"].items():
        spec = {"text_re": re.compile(c["text_regex"]) if c.get("text_regex") else None,
                "numeric_gt": c.get("numeric_gt") or {},
                "sigma": c.get("anomaly_sigma"),
                "min_n": c.get("min_sample_for_sigma", 5),
                "prescale": max(1, int(c.get("prescale", 1))),
                "note": c.get("note", "")}
        compiled[name] = spec
    return compiled


def scan_surfaces(cfg, cutoff, now):
    """Expand surface globs, read JSONL, return events with provenance."""
    events = []
    scanned = {}
    for surf in cfg["surfaces"]:
        name, g = surf["name"], os.path.expanduser(surf["glob"])
        paths = sorted(glob.glob(g))
        n_ok = n_bad = 0
        for p in paths:
            try:
                fh = open(p, errors="replace")
            except OSError as e:
                print(f"warn: cannot read {p}: {e}", file=sys.stderr)
                continue
            with fh:
                for ln, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        n_bad += 1
                        continue
                    ts = parse_ts(row.get("ts") or row.get("ts_corrected"))
                    if ts is not None and ts < cutoff:
                        continue
                    events.append({"row": row, "surface": name, "line": ln,
                                   "path": p, "ts": ts,
                                   "text": gather_text(row)})
                    n_ok += 1
        scanned[name] = {"glob": g, "files": len(paths), "in_window": n_ok,
                         "unparsable": n_bad}
    return events, scanned


def numeric_observations(events, cfg):
    """Per-extractor numeric values via the menu's numeric_extract table:
    either a direct numeric field (regex null) or a regex on a string field."""
    table = cfg.get("numeric_extract", {})
    obs = {}  # (surface, name) -> [(event, value)]
    for ev in events:
        for ext in table.get(ev["surface"], []):
            field, name = ext["field"], ext.get("name") or ext["field"]
            v = ev["row"].get(field)
            if v is None:
                continue
            if ext.get("regex") is None:
                if isinstance(v, (int, float)):
                    obs.setdefault((ev["surface"], name), []).append((ev, float(v)))
            else:
                m = re.search(ext["regex"], str(v))
                if m:
                    obs.setdefault((ev["surface"], name), []).append(
                        (ev, float(m.group(1))))
    return obs


def cost_anomaly_events(obs, sigma, min_n):
    """Events whose extracted value exceeds mean + sigma * stdev (population)."""
    flagged = set()
    detail = {}
    for (surface, name), pairs in obs.items():
        if len(pairs) < min_n:
            detail[f"{surface}:{name}"] = {"n": len(pairs), "skipped": True}
            continue
        vals = [v for _, v in pairs]
        mu, sd = statistics.mean(vals), statistics.pstdev(vals)
        if sd == 0:
            detail[f"{surface}:{name}"] = {"n": len(vals), "skipped": "zero-sigma"}
            continue
        hi = mu + sigma * sd
        n_flag = sum(1 for v in vals if v > hi)
        detail[f"{surface}:{name}"] = {"n": len(vals), "mean": round(mu, 2),
                                       "sigma": round(sd, 2), "threshold": round(hi, 2),
                                       "flagged": n_flag}
        for ev, v in pairs:
            if v > hi:
                flagged.add(id(ev["row"]))
    return flagged, detail


def classify(events, compiled, cfg):
    """Assign each event to every class whose signature it matches.
    Returns class -> [events]; novel = matched none."""
    obs = numeric_observations(events, cfg)
    sigma_classes = {n: s for n, s in compiled.items() if s["sigma"]}
    anomaly_flagged, anomaly_detail = {}, {}
    for cname, spec in sigma_classes.items():
        flagged, detail = cost_anomaly_events(obs, spec["sigma"], spec["min_n"])
        anomaly_flagged[cname] = flagged
        anomaly_detail[cname] = detail

    by_class = {n: [] for n in compiled}
    novel = []
    for ev in events:
        matched = False
        for cname, spec in compiled.items():
            hit = False
            if spec["sigma"]:
                hit = id(ev["row"]) in anomaly_flagged.get(cname, set())
            else:
                if spec["text_re"] and spec["text_re"].search(ev["text"]):
                    hit = True
                if not hit and spec["numeric_gt"]:
                    for fld, thr in spec["numeric_gt"].items():
                        v = ev["row"].get(fld)
                        if isinstance(v, (int, float)) and v > thr:
                            hit = True
                            break
            if hit:
                by_class[cname].append(ev)
                matched = True
        if not matched:
            novel.append(ev)
    return by_class, novel, anomaly_detail


def run_trigger(cfg, cutoff, now, seed, log_path, novel_path, dry_run):
    rng = random.Random(seed)
    events, scanned = scan_surfaces(cfg, cutoff, now)
    compiled = compile_classes(cfg)
    by_class, novel, anomaly_detail = classify(events, compiled, cfg)

    express_re = re.compile(cfg["express"]["text_regex"]) if cfg.get("express", {}).get("text_regex") else None

    def is_express(ev):
        return bool(express_re and express_re.search(ev["text"]))

    window_days = max((now - cutoff) / 86400, 1.0) if cutoff else 1.0
    floor = int(cfg.get("min_bias_floor_per_day", 10))
    floor_n = int(max(1, round(floor * min(window_days, 1.0) if window_days < 1 else window_days)))

    # Sample per class (prescale 1/N, express always kept). Bypass check after.
    samples = {}   # class -> [ev]
    prescales = {}
    bypass = False
    total_sampled = 0
    for cname, evs in by_class.items():
        p = compiled[cname]["prescale"]
        prescales[cname] = p
        keep = []
        for ev in evs:
            if is_express(ev) or p == 1 or rng.random() < 1.0 / p:
                keep.append(ev)
        samples[cname] = keep
        total_sampled += len(keep)

    if total_sampled < floor_n:
        # COUNT FLOOR: the minimum-bias sample must never be empty. The whole
        # stream bypasses — prescale 1 for every event (amendment 3) — and if
        # even that leaves the sample empty, a minimum-bias random top-up of
        # UNSAMPLED events (class "minimum_bias", prescale 1) fills the floor.
        bypass = True
        for cname in samples:
            samples[cname] = list(by_class[cname])
            prescales[cname] = 1
        total_sampled = sum(len(v) for v in samples.values())
        if total_sampled < floor_n:
            sampled_ids = {id(ev["row"]) for evs in samples.values() for ev in evs}
            pool = [ev for ev in events if id(ev["row"]) not in sampled_ids]
            rng.shuffle(pool)
            samples["minimum_bias"] = pool[: floor_n - total_sampled]
            prescales["minimum_bias"] = 1
            total_sampled += len(samples["minimum_bias"])

    cap = int(cfg.get("novel_rate_cap_per_run", 50))
    novel_written = novel[:cap]
    novel_capped = max(0, len(novel) - cap)

    run_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
    menu_version = cfg["menu_version"]

    summary = {
        "kind": "trigger_summary", "ts": run_ts, "menu_version": menu_version,
        "window": {"cutoff_epoch": cutoff, "days": round(window_days, 3)},
        "bypass": bypass, "count_floor": {"per_day": floor, "required": floor_n,
                                          "sampled": total_sampled},
        "scanned": scanned, "unfolding_note": "unfolded = raw x prescale; n = events actually sampled",
        "classes": {c: {"raw": len(by_class.get(c, [])), "n": len(samples[c]),
                        "prescale": prescales[c],
                        "unfolded": len(by_class.get(c, [])) * prescales[c],
                        "note": compiled[c]["note"] if c in compiled
                                else "minimum-bias top-up (count floor)"}
                    for c in sorted(samples)},
        "anomaly_detail": anomaly_detail,
        "novel": {"raw": len(novel), "written": len(novel_written),
                  "capped": novel_capped, "prescale": 1},
        "total_events": len(events),
    }

    out_log, out_novel = [], []
    for cname in sorted(samples):
        for ev in samples[cname]:
            out_log.append({
                "kind": "trigger_sample", "ts": run_ts, "menu_version": menu_version,
                "class": cname, "event_ts": ev["row"].get("ts"),
                "surface": ev["surface"], "line": ev["line"],
                "digest": hashlib.sha1(json.dumps(ev["row"], sort_keys=True,
                                                  default=str).encode()).hexdigest()[:12],
                "prescale": prescales[cname], "unfolded_contribution": prescales[cname],
                "express": is_express(ev), "bypass_run": bypass,
                "text": ev["text"][:200]})
    for ev in novel_written:
        out_novel.append({
            "kind": "novel_event", "ts": run_ts, "menu_version": menu_version,
            "event_ts": ev["row"].get("ts"), "surface": ev["surface"],
            "line": ev["line"], "prescale": 1,
            "digest": hashlib.sha1(json.dumps(ev["row"], sort_keys=True,
                                             default=str).encode()).hexdigest()[:12],
            "agent": ev["row"].get("agent"), "text": ev["text"][:300]})

    if not dry_run:
        rows = [summary] + out_log
        atomic_append(log_path, rows)
        if out_novel:
            atomic_append(novel_path, out_novel)
    return summary, out_log, out_novel


# ---------------------------------------------------------------- selftest

def selftest():
    import shutil
    tmp = tempfile.mkdtemp(prefix="trigger-selftest-")
    results = []

    def check(name, cond):
        results.append((name, bool(cond)))

    # synthetic surfaces: errors, express, novel, cost anomaly
    bus = os.path.join(tmp, "bus.jsonl")
    led = os.path.join(tmp, "usage.jsonl")
    rows_bus = []
    for i in range(20):
        rows_bus.append({"ts": f"2026-10-11T1{i % 10}:00:00Z", "agent": "t",
                         "kind": "finding", "note": "all quiet here"})
    rows_bus.append({"ts": "2026-10-11T12:00:00Z", "agent": "t", "kind": "finding",
                     "note": "recipe crashed: unknown exception class"})
    rows_bus.append({"ts": "2026-10-11T12:01:00Z", "agent": "t", "kind": "finding",
                     "note": "deployment to production failed halfway"})
    for i in range(30):
        rows_bus.append({"ts": f"2026-10-11T0{i % 10}:30:00Z", "agent": "t2",
                         "kind": "handoff", "note": "routine"})  # novel fodder
    with open(bus, "w") as fh:
        for r in rows_bus:
            fh.write(json.dumps(r) + "\n")
    with open(led, "w") as fh:
        for i in range(20):
            fh.write(json.dumps({"ts": "2026-10-11T05:00:00Z", "kind": "turn-usage",
                                 "target": f"in=1000 out={50 + (i % 10)}"}) + "\n")
        fh.write(json.dumps({"ts": "2026-10-11T05:30:00Z", "kind": "turn-usage",
                             "target": "in=1000 out=99999"}) + "\n")

    cfg = {
        "menu_version": 7,
        "surfaces": [{"name": "bus", "glob": os.path.join(tmp, "bus.jsonl")},
                     {"name": "usage-ledger", "glob": os.path.join(tmp, "usage.jsonl")}],
        "numeric_extract": {"usage-ledger": [{"field": "target", "regex": "out=(\\d+)",
                                              "name": "out_tokens"}]},
        "classes": {
            "unknown_error_class": {"text_regex": "(?i)error|crash|exception|fail",
                                    "prescale": 4},
            "cost_anomaly_gt2sigma": {"anomaly_sigma": 2, "min_sample_for_sigma": 5,
                                      "prescale": 3},
            "failed_verification": {"text_regex": "(?i)deviated|not.?verified",
                                    "prescale": 1}
        },
        "express": {"text_regex": "(?i)production|\\bP0\\b"},
        "min_bias_floor_per_day": 10,
        "novel_rate_cap_per_run": 50
    }
    cfg_path = os.path.join(tmp, "menu.json")
    with open(cfg_path, "w") as fh:
        json.dump(cfg, fh)

    cutoff, now = parse_since("1d")
    summary, out_log, out_novel = run_trigger(cfg, cutoff, now, seed=42,
                                              log_path=os.path.join(tmp, "log.jsonl"),
                                              novel_path=os.path.join(tmp, "novel.jsonl"),
                                              dry_run=True)

    check("summary row carries menu_version 7", summary["menu_version"] == 7)
    check("error event classified", summary["classes"]["unknown_error_class"]["raw"] >= 1)
    check("cost anomaly flagged (>2 sigma)",
          summary["classes"]["cost_anomaly_gt2sigma"]["raw"] == 1)
    check("prescale applied (n <= raw) for error class",
          summary["classes"]["unknown_error_class"]["n"]
          <= summary["classes"]["unknown_error_class"]["raw"])
    check("express event never sampled away",
          any(r["express"] for r in out_log))
    check("novel events captured at prescale 1",
          summary["novel"]["raw"] > 0 and summary["novel"]["prescale"] == 1)
    check("novel rate cap recorded",
          summary["novel"]["written"] == min(summary["novel"]["raw"], 50))

    # count-floor bypass: a stream with almost no matches must not sample empty
    cfg2 = dict(cfg)
    cfg2["classes"] = {"failed_verification": {"text_regex": "(?i)deviated",
                                               "prescale": 100}}
    cfg2["min_bias_floor_per_day"] = 10
    s2, o2, _ = run_trigger(cfg2, cutoff, now, seed=1,
                            log_path=os.path.join(tmp, "l2.jsonl"),
                            novel_path=os.path.join(tmp, "n2.jsonl"), dry_run=True)
    check("count floor forces bypass on sparse stream", s2["bypass"] is True)
    check("bypass keeps every event at prescale 1",
          s2["classes"]["failed_verification"]["prescale"] == 1
          and s2["classes"]["failed_verification"]["n"]
          == s2["classes"]["failed_verification"]["raw"])
    check("bypass run never yields an empty sample", s2["count_floor"]["sampled"] > 0)

    # write path really lands rows (atomic_append)
    lp = os.path.join(tmp, "log.jsonl")
    run_trigger(cfg, cutoff, now, seed=42, log_path=lp,
                novel_path=os.path.join(tmp, "novel.jsonl"), dry_run=False)
    with open(lp) as fh:
        landed = [json.loads(l) for l in fh if l.strip()]
    check("atomic append lands summary + samples",
          any(r["kind"] == "trigger_summary" for r in landed)
          and any(r["kind"] == "trigger_sample" for r in landed))

    shutil.rmtree(tmp, ignore_errors=True)
    failed = [n for n, ok in results if not ok]
    for n, ok in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print(f"selftest: {len(results) - len(failed)}/{len(results)} passed")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser(
        description="L0 trigger hierarchy: prescaled event scanner + minimum-bias "
                    "bypass (count floor) + novel stream. Zero-LLM, stdlib-only. "
                    "L1 (cheap-model salience on L0 survivors) and L2 (dreamer/"
                    "fusion on top-N) are FUTURE stages — documented here, not "
                    "built (wave-3 amendment 3). The dreamer input stays "
                    "FULL-CORPUS: this tool consumes event ledgers, never "
                    "transcripts.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="24h", help="window: 24h|7d|all")
    ap.add_argument("--config", default=DEFAULT_CONFIG, help="trigger menu path")
    ap.add_argument("--log", default=DEFAULT_LOG, help="trigger-log.jsonl path")
    ap.add_argument("--novel", default=DEFAULT_NOVEL, help="novel-stream.jsonl path")
    ap.add_argument("--seed", type=int, default=None, help="sampling seed (default: random)")
    ap.add_argument("--dry-run", action="store_true", help="classify + print, write nothing")
    ap.add_argument("--json", action="store_true", help="print the summary as JSON")
    ap.add_argument("--selftest", action="store_true", help="synthetic-data self test")
    a = ap.parse_args()

    if a.selftest:
        return selftest()

    try:
        cfg = load_config(a.config)
        cutoff, now = parse_since(a.since)
        summary, out_log, out_novel = run_trigger(
            cfg, cutoff, now, seed=a.seed, log_path=a.log, novel_path=a.novel,
            dry_run=a.dry_run)
    except (OSError, ValueError, KeyError) as e:
        print(f"trigger.py: {e}", file=sys.stderr)
        return 1

    if a.json or a.dry_run:
        print(json.dumps(summary, indent=1))
    else:
        print(f"L0 trigger run: menu v{summary['menu_version']}  "
              f"window={summary['window']['days']}d  events={summary['total_events']}  "
              f"bypass={'YES (count floor)' if summary['bypass'] else 'no'}")
        for cname, c in summary["classes"].items():
            print(f"  {cname:28} raw={c['raw']:>5} prescale=1/{c['prescale']:<3} "
                  f"n={c['n']:>5} unfolded={c['unfolded']:>6}")
        print(f"  novel stream: raw={summary['novel']['raw']} "
              f"written={summary['novel']['written']} "
              f"capped={summary['novel']['capped']}")
        dest = "(dry-run: nothing written)" if a.dry_run else f"-> {a.log}" + \
               (f" + {a.novel}" if out_novel else "")
        print(dest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
