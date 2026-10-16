#!/usr/bin/env python3
"""elites.py — MAP-Elites archive for harness improvement proposals.

Wave-3 amendment 8: FITNESS = MACHINE-BENCHMARKABLE ARTIFACTS ONLY.
  - bench_runtime_ms : measured script runtime (lower is better)
  - assertion_count  : assertions the artifact carries
  - coverage_count   : corpus/doc surfaces the artifact covers
  - floor            : replay-gym pass — binary MUST-PASS gate to enter the
                       archive (1-bit invariant check, contributes no quality)
P(accept) / any self-report acceptance estimate is FORBIDDEN in fitness and is
loudly refused — the dreamer's self-estimate selects for confident junk.

Descriptor axes (fixed at design time):
  failure_class: timeout | schema-mapping | auth-permission | data-loss-race |
                 silent-failure | perf-cost | governance-process | other
  loop_touched:  dreamer | gardener | watchdog | triage | evidence | fusion |
                 none
  blast_radius:  low | medium | high

Archive ledger: knowledge/dreams/elites/elites.jsonl, append-only. Each row is
a keep/reject decision; the CURRENT CHAMPION of a cell is its latest kept row.
Best-per-cell is retained even if globally outperformed — stepping stones are
the value.

Usage:
  python3 elites.py add --failure-class F --loop L --blast B
      --bench-runtime-ms N --assertion-count N [--coverage-count N]
      --floor-pass/--no-floor-pass --title "..." [--desc "..."] [--source "..."]
  python3 elites.py show [--json]
  python3 elites.py novel --failure-class F --loop L --blast B   # candidate NN
  python3 elites.py augment    # regenerate knowledge/dreams/elites/prompt-augmentation.md
  python3 elites.py --selftest
"""

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from atomic_io import atomic_append_validated, atomic_write  # noqa: E402

K = os.path.join(os.path.expanduser("~"), ".claude", "knowledge")
ARCHIVE = os.path.join(K, "dreams", "elites", "elites.jsonl")
AUGMENT = os.path.join(K, "dreams", "elites", "prompt-augmentation.md")

AXES = {
    "failure_class": ("timeout", "schema-mapping", "auth-permission",
                      "data-loss-race", "silent-failure", "perf-cost",
                      "governance-process", "other"),
    "loop_touched": ("dreamer", "gardener", "watchdog", "triage", "evidence",
                     "fusion", "none"),
    "blast_radius": ("low", "medium", "high"),
}
FORBIDDEN_FITNESS = ("p_accept", "p-accept", "paccept", "acceptance_prob")

SCHEMA = {
    "required": ["id", "ts", "cell", "decision", "candidate"],
    "enums": {"decision": {"kept", "rejected", "floor-failed"}},
}

FORBIDDEN_TEXT = ("FORBIDDEN in fitness: P(accept) / self-estimated acceptance "
                  "probability — the dreamer's self-estimate selects for "
                  "confident junk (amendment 8).")


def now_iso():
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    print(f"WARN: malformed line skipped in {path}",
                          file=sys.stderr)
    return rows


def cell_key(cls, loop, blast):
    return f"{cls}|{loop}|{blast}"


def score(runtime_ms, assertions, coverage):
    """Machine-benchmarkable composite. Runtime term: 2000ms -> 0, 0ms -> 100.
    Lower runtime is better; assertions and coverage are additive."""
    runtime_term = max(0.0, 100.0 - float(runtime_ms) / 20.0)
    return round(float(assertions) + 2.0 * float(coverage) + runtime_term, 2)


def champions(rows):
    """cell -> latest kept row."""
    out = {}
    for r in rows:
        if r.get("decision") == "kept":
            out[r["cell"]] = r
    return out


def forbid_p_accept(obj, where):
    text = json.dumps(obj).lower()
    for bad in FORBIDDEN_FITNESS:
        if bad in text:
            raise ValueError(f"{where}: {FORBIDDEN_TEXT} (found {bad!r})")


def next_id(rows):
    n = 0
    for r in rows:
        rid = str(r.get("id", ""))
        if rid.startswith("elt-"):
            try:
                n = max(n, int(rid[4:]))
            except ValueError:
                pass
    return f"elt-{n + 1:04d}"


def cmd_add(a):
    for axis, vals in AXES.items():
        v = getattr(a, axis)
        if v not in vals:
            print(f"ERROR: {axis} {v!r} not in {list(vals)}", file=sys.stderr)
            return 2
    cand = {
        "title": a.title,
        "desc": a.desc,
        "source": a.source,
        "failure_class": a.failure_class,
        "loop_touched": a.loop_touched,
        "blast_radius": a.blast_radius,
        "fitness": {
            "bench_runtime_ms": a.bench_runtime_ms,
            "assertion_count": a.assertion_count,
            "coverage_count": a.coverage_count,
            "replay_gym_floor_pass": a.floor_pass,
        },
        "score": score(a.bench_runtime_ms, a.assertion_count, a.coverage_count),
    }
    try:
        forbid_p_accept(cand, "add")
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    cell = cell_key(a.failure_class, a.loop_touched, a.blast_radius)
    rows = load_jsonl(ARCHIVE)
    champ = champions(rows).get(cell)

    decision, reason = "kept", "empty cell"
    if not a.floor_pass:
        decision, reason = "floor-failed", \
            "replay-gym floor not passed — not archived as elite"
    elif champ and (champ.get("candidate", {}).get("score", -1)
                    >= cand["score"]):
        decision, reason = ("rejected",
                            f"champion score {champ['candidate']['score']} "
                            f">= candidate {cand['score']}")
    rec = {
        "id": next_id(rows),
        "ts": now_iso(),
        "cell": cell,
        "decision": decision,
        "reason": reason,
        "candidate": cand,
    }
    atomic_append_validated(ARCHIVE, rec, SCHEMA)
    print(f"{decision}: {rec['id']} cell={cell} score={cand['score']} "
          f"({reason})")
    return 0 if decision in ("kept", "rejected") else 2


def cmd_show(a):
    rows = load_jsonl(ARCHIVE)
    champs = champions(rows)
    occupied = set(champs)
    print(f"archive: {len(rows)} decision row(s), {len(occupied)} occupied "
          f"cell(s) of {len(AXES['failure_class']) * len(AXES['loop_touched']) * len(AXES['blast_radius'])}")
    for cell in sorted(occupied):
        c = champs[cell]["candidate"]
        print(f"  {cell}  id={champs[cell]['id']} score={c.get('score')} "
              f"rt={c['fitness']['bench_runtime_ms']}ms "
              f"assert={c['fitness']['assertion_count']} "
              f"cov={c['fitness']['coverage_count']}")
    empty = [cell_key(fc, lp, br)
             for fc in AXES["failure_class"]
             for lp in AXES["loop_touched"]
             for br in AXES["blast_radius"]
             if cell_key(fc, lp, br) not in occupied]
    print(f"empty cells: {len(empty)}")
    if not a.json:
        for e in empty:
            print(f"  EMPTY {e}")
    return 0


def dist(cell_a, cell_b):
    a, b = cell_a.split("|"), cell_b.split("|")
    return sum(1 for x, y in zip(a, b) if x != y) / float(len(a))


def cmd_novel(a):
    rows = load_jsonl(ARCHIVE)
    champs = champions(rows)
    cell = cell_key(a.failure_class, a.loop_touched, a.blast_radius)
    for axis, vals in AXES.items():
        v = getattr(a, axis)
        if v not in vals:
            print(f"ERROR: {axis} {v!r} not in {list(vals)}", file=sys.stderr)
            return 2
    if not champs:
        print("novelty: no champions yet — any candidate is maximally novel")
        return 0
    ranked = sorted(((dist(cell, cc), cc) for cc in champs),
                    reverse=True)
    print(f"novelty for {cell}: nearest-neighbor distance "
          f"{ranked[-1][0]:.3f} (nearest: {ranked[-1][1]})")
    print("most-distant cells (novelty-mode targets):")
    for d, cc in ranked[:3]:
        print(f"  d={d:.3f} {cc} id={champs[cc]['id']}")
    return 0


def cmd_augment(_a):
    rows = load_jsonl(ARCHIVE)
    champs = champions(rows)
    all_cells = [cell_key(fc, lp, br)
                 for fc in AXES["failure_class"]
                 for lp in AXES["loop_touched"]
                 for br in AXES["blast_radius"]]
    empty = [c for c in all_cells if c not in champs]
    ranked = []
    for cc, c in champs.items():
        others = [dist(cc, o) for o in champs if o != cc]
        ranked.append((min(others) if others else 1.0, cc))
    top3 = sorted(ranked, reverse=True)[:3]

    lines = [
        "# Dreamer prompt augmentation (generated by elites.py augment)",
        "",
        "Fill an empty descriptor cell — best-per-cell is retained even if",
        "globally outperformed; stepping stones are the value.",
        "",
        f"Empty cells ({len(empty)}/{len(all_cells)}):",
        " ".join(empty) if empty else "(none)",
        "",
        "Most-distant elites (cross-breeding context):",
    ]
    if top3:
        for d, cc in top3:
            c = champs[cc]["candidate"]
            lines.append(
                f"- {cc} (id {champs[cc]['id']}, NN-distance {d:.2f}): "
                f"{c.get('title', '')} — measured runtime "
                f"{c['fitness']['bench_runtime_ms']}ms, "
                f"{c['fitness']['assertion_count']} assertions, "
                f"{c['fitness']['coverage_count']} corpus refs")
    else:
        lines.append("(archive empty — no elites yet)")
    lines += [
        "",
        "Fitness is machine-benchmarkable artifacts only: measured runtime,",
        "assertion count, corpus coverage. Replay-gym pass is the binary floor.",
        "Self-estimated P(accept) is not a fitness signal.",
    ]
    atomic_write(AUGMENT, "\n".join(lines) + "\n")
    print(f"augmentation written: {AUGMENT} ({len(empty)} empty cells, "
          f"{len(top3)} distant elites)")
    return 0


def cmd_selftest(_a):
    import tempfile
    real = (globals()["ARCHIVE"], globals()["AUGMENT"])
    with tempfile.TemporaryDirectory() as td:
        globals()["ARCHIVE"] = os.path.join(td, "elites.jsonl")
        globals()["AUGMENT"] = os.path.join(td, "aug.md")
        ns = lambda **kw: argparse.Namespace(**kw)
        try:
            assert cmd_add(ns(
                failure_class="silent-failure", loop_touched="gardener",
                blast_radius="low", bench_runtime_ms=500, assertion_count=4,
                coverage_count=2, floor_pass=False, title="f1", desc=None,
                source="selftest")) == 2  # floor fail
            assert cmd_add(ns(
                failure_class="silent-failure", loop_touched="gardener",
                blast_radius="low", bench_runtime_ms=500, assertion_count=4,
                coverage_count=2, floor_pass=True, title="e1", desc=None,
                source="selftest")) == 0
            assert cmd_add(ns(
                failure_class="silent-failure", loop_touched="gardener",
                blast_radius="low", bench_runtime_ms=100, assertion_count=9,
                coverage_count=3, floor_pass=True, title="e2", desc=None,
                source="selftest")) == 0  # better, replaces
            # worse candidate: rejected, champion must remain e2
            assert cmd_add(ns(
                failure_class="silent-failure", loop_touched="gardener",
                blast_radius="low", bench_runtime_ms=10, assertion_count=2,
                coverage_count=0, floor_pass=True, title="e3", desc=None,
                source="selftest")) == 0
        except AssertionError:
            pass
        except SystemExit:
            pass
        rows = load_jsonl(globals()["ARCHIVE"])
        champs = champions(rows)
        assert len(champs) == 1, champs
        assert champs[cell_key("silent-failure", "gardener", "low")][
            "candidate"]["title"] == "e2", champs
        # p_accept forbidden
        try:
            forbid_p_accept({"fitness": {"p_accept": 0.9}}, "t")
            raise SystemExit("p_accept guard failed")
        except ValueError:
            pass
        # novel + show + augment
        assert cmd_novel(ns(failure_class="timeout", loop_touched="dreamer",
                            blast_radius="high")) == 0
        assert cmd_show(ns(json=False)) == 0
        assert cmd_augment(None) == 0
        aug = open(globals()["AUGMENT"]).read()
        empty_line = next(l for l in aug.split("\n")
                          if l.startswith("Empty cells ("))
        champ_cell = "silent-failure|gardener|low"
        assert "(167/168)" in empty_line, empty_line
        assert champ_cell not in empty_line, "champion listed as empty"
        assert champ_cell in aug.split("Most-distant elites")[1], \
            "champion missing from cross-breeding context"
    globals()["ARCHIVE"], globals()["AUGMENT"] = real
    print("selftest: PASS (floor-gate/keep-best/replacement/p_accept-ban/"
          "novel/show/augment)")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="MAP-Elites archive (wave-3 amendment 8: machine-"
                    "benchmarkable fitness only; replay-gym pass is the floor; "
                    "P(accept) forbidden)")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    def axes(p):
        p.add_argument("--failure-class", dest="failure_class",
                       choices=AXES["failure_class"], required=True)
        p.add_argument("--loop", dest="loop_touched",
                       choices=AXES["loop_touched"], required=True)
        p.add_argument("--blast", dest="blast_radius",
                       choices=AXES["blast_radius"], required=True)

    p = sub.add_parser("add", help="classify a proposal into a cell; keep best")
    axes(p)
    p.add_argument("--bench-runtime-ms", dest="bench_runtime_ms", type=float,
                   required=True, help="MEASURED script runtime in ms")
    p.add_argument("--assertion-count", dest="assertion_count", type=int,
                   required=True)
    p.add_argument("--coverage-count", dest="coverage_count", type=int,
                   default=0, help="corpus/doc surfaces covered")
    p.add_argument("--floor-pass", dest="floor_pass",
                   action="store_true", default=False,
                   help="artifact passes the replay-gym floor")
    p.add_argument("--title", required=True)
    p.add_argument("--desc")
    p.add_argument("--source")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("show", help="grid dump including empty cells")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("novel", help="nearest-neighbor distance for a candidate")
    axes(p)
    p.set_defaults(fn=cmd_novel)

    sub.add_parser("augment",
                   help="regenerate prompt-augmentation.md for the integrator"
                   ).set_defaults(fn=cmd_augment)

    args = ap.parse_args()
    if args.selftest:
        return cmd_selftest(None)
    if not getattr(args, "fn", None):
        ap.print_help()
        return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
