#!/usr/bin/env python3
"""pleiotropy.py — consumer-degree graph + degree→trust-rung policy.

Wave-3 proposal (pleiotropy-gates, AMENDED 2026-10-11 amendment #7):
trust rungs assigned by hand are where Goodhart events live; evo-devo keeps
high-pleiotropy genes conserved because mutating them breaks everything. This
script measures pleiotropy mechanically and renders the verdicts the write-gate
would enforce.

GRAPH SUBSTRATE — REUSED, not rebuilt (amendment #7): synaptic-strength.py
(same directory, built 2026-10-11) already runs the daily per-file ref join
(basename mentioned across INDEX.md + skills/*.md). This script IMPORTS it and
reuses build_files / collect_signals / annotate for the domains/ + projects/
layer; its per-file refs count is carried through as the `ss_refs` column.
Pleiotropy's own layer on top:
  1. extended consumer scan — synaptic only sees INDEX + skills sources; the
     degree graph adds knowledge scripts (*.py), all knowledge md, agent files
     (~/.claude/agents/*.md) and prompt files (the CLAUDE.md trio) as
     consumer sources, then merges degrees (dedup by consumer path).
  2. degree→rung policy — degree <=2 → auto-safe; 3–9 → propose;
     >=10 OR INDEX-consumed → josh-gate + mandatory regression fixture.
  3. runtime-consumer guard — an item referenced from a prompt file
     (agents/*.md, CLAUDE.md) has an uncountable consumer set (every session
     of that agent), so it counts as MAXIMAL pleiotropy: conserved until
     shown otherwise (the evo-devo default), rung floored to josh-gate.
  4. module-split rule — a change touching >=5 consumers must be proposed as
     a module split instead — EXCEPT items under the interface-stability
     exemption (amendment #7): a bugfix to a stable, contracted interface is
     not pleiotropic damage. atomic_io.py is the canonical case.

REPORT-ONLY on first build: nothing is gated; output is the graph + verdicts
to knowledge/reports/pleiotropy/. Enforcement is a later, flagged decision.

Zero-LLM. stdlib only. Reuses scripts/atomic_io.py (read-only import).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import importlib.util  # noqa: E402
from atomic_io import atomic_write  # noqa: E402

# synaptic-strength.py has a hyphenated filename; load it as a module.
_spec = importlib.util.spec_from_file_location(
    "synaptic_strength", Path(__file__).parent / "synaptic-strength.py")
ss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ss)

HOME = Path(os.path.expanduser("~"))
K = HOME / ".claude" / "knowledge"
OUT = K / "reports" / "pleiotropy"
INDEX = K / "INDEX.md"
AGENTS = HOME / ".claude" / "agents"
SKILLS = HOME / ".claude" / "skills"
PROMPT_FILES = [
    HOME / ".claude" / "CLAUDE.md",
    HOME / "Documents" / "CLAUDE.md",
    HOME / "Documents" / "workbench" / "CLAUDE.md",
]
# Runtime-consumer guard source markers: a consumer under any of these
# prefixes embeds the item into agent sessions — its consumer set (every
# session of that agent) is uncountable. Selftest appends to this list.
PROMPT_SOURCE_PREFIXES = [str(AGENTS)] + [str(p) for p in PROMPT_FILES]

# --- CONFIG: interface-stability exemption (amendment #7) -------------------
# Files under an active contract are exempt from the MODULE-SPLIT rule: a
# bugfix to a stable interface is not pleiotropic damage. The rung verdict is
# still reported (degree is still degree) but annotated exempt. Additive only.
EXEMPT_INTERFACE_STABILITY = {
    "atomic_io.py": "canonical stable interface; ~20 consumers via import are "
                    "MANDATED by wave-3 CONTRACTS.md global rules, not "
                    "accidental coupling",
}
# degree at/above which a change must be proposed as a module split instead
MODULE_SPLIT_FLOOR = 5
RUNG_AUTO_SAFE_MAX = 2     # degree <= 2
RUNG_PROPOSE_MAX = 9       # degree 3..9; >=10 or INDEX-consumed or maximal


def _load(p):
    try:
        return p.read_text(errors="ignore").lower()
    except OSError:
        return ""


def build_consumer_sources():
    """(path, lowercase_text) consumer sources, superseting synaptic's
    ref_index (INDEX + skills) with scripts, knowledge md, agents, prompts."""
    sources = [(str(INDEX), _load(INDEX))]
    if SKILLS.is_dir():
        for p in SKILLS.rglob("*.md"):
            sources.append((str(p), _load(p)))
    for p in K.rglob("*.md"):
        if p.is_file():
            sources.append((str(p), _load(p)))
    for p in K.rglob("*.py"):
        if p.is_file():
            sources.append((str(p), _load(p)))
    if AGENTS.is_dir():
        for p in AGENTS.glob("*.md"):
            sources.append((str(p), _load(p)))
    for p in PROMPT_FILES:
        sources.append((str(p), _load(p)))
    return sources


def collect_items():
    """Tracked items: synaptic's domains/projects files + scripts + config."""
    items = {f.path: f for f in ss.build_files() if f.kind == "file"}
    for p in sorted((K / "scripts").glob("*.py")):
        items.setdefault(p, None)
    cfg = K / "config"
    if cfg.is_dir():
        for p in sorted(cfg.glob("*.json")):
            items.setdefault(p, None)
    return items


def score(items, sources, index_text=None):
    """degree + verdict per item. Returns list of dicts.

    Needle matching is word-boundary regex — a bare-substring match puts a
    short stem ("low") inside unrelated words ("lower") and inflates degree.
    """
    if index_text is None:
        index_text = _load(INDEX)
    rows = []
    for path, ssfile in sorted(items.items()):
        try:
            item_id = str(path.relative_to(HOME))
        except ValueError:  # synthetic selftest paths outside HOME
            item_id = str(path)
        needle = re.compile(r"\b" + re.escape(path.stem.lower()) + r"\b")
        consumers = set()
        prompt_consumers = 0
        for spath, text in sources:
            if os.path.realpath(spath) == os.path.realpath(path):
                continue  # self-reference is not a consumer
            if needle.search(text):
                consumers.add(spath)
                if any(spath.startswith(pfx) for pfx in PROMPT_SOURCE_PREFIXES):
                    prompt_consumers += 1
        degree = len(consumers)
        index_consumed = bool(needle.search(index_text))
        maximal = prompt_consumers > 0
        if maximal or degree >= 10 or index_consumed:
            rung = "josh-gate+fixture"
        elif degree >= RUNG_AUTO_SAFE_MAX + 1:
            rung = "propose"
        else:
            rung = "auto-safe"
        exempt = path.name in EXEMPT_INTERFACE_STABILITY
        rows.append({
            "item": item_id,
            "name": path.name,
            "degree": degree,
            "ss_refs": ssfile.refs if ssfile is not None else None,
            "index_consumed": index_consumed,
            "prompt_consumers": prompt_consumers,
            "maximal_uncountable": maximal,
            "rung": rung,
            "module_split_required": degree >= MODULE_SPLIT_FLOOR and not exempt,
            "interface_stability_exempt": (
                EXEMPT_INTERFACE_STABILITY.get(path.name) if exempt else None),
            "consumers": sorted(consumers),
        })
    return rows


def render_report(rows, days):
    today = dt.date.today().isoformat()
    gates = [r for r in rows if r["rung"] == "josh-gate+fixture"]
    props = [r for r in rows if r["rung"] == "propose"]
    safe = [r for r in rows if r["rung"] == "auto-safe"]
    splits = [r for r in rows if r["module_split_required"]]
    exempt = [r for r in rows if r["interface_stability_exempt"]]
    out = [
        f"# Pleiotropy pass — {today}",
        "",
        f"Consumer-degree graph over knowledge scripts, config, domains, "
        f"projects (signal window {days}d for the synaptic layer; consumer "
        f"scan is all-time). REPORT-ONLY — no gate is enforced.",
        f"Substrate: synaptic-strength.py (imported; ss_refs = its daily "
        f"refs count). This layer adds the extended consumer scan, the "
        f"degree→rung policy, the runtime-consumer guard, and the "
        f"interface-stability exemption (amendment #7).",
        "",
        f"Items scored: {len(rows)} · josh-gate+fixture: {len(gates)} · "
        f"propose: {len(props)} · auto-safe: {len(safe)} · "
        f"module-split candidates: {len(splits)} · exempt: {len(exempt)}",
        "",
        "## Josh-gate + mandatory regression fixture (degree >=10, INDEX-consumed, or prompt-embedded maximal)",
        "",
        "| item | degree | ss_refs | INDEX | prompt | why |",
        "|---|---|---|---|---|---|",
    ]
    for r in sorted(gates, key=lambda r: -r["degree"]):
        why = ("prompt-embedded maximal" if r["maximal_uncountable"] else "")
        if r["index_consumed"]:
            why = (why + "; " if why else "") + "INDEX-consumed"
        if r["degree"] >= 10:
            why = (why + "; " if why else "") + f"degree {r['degree']} >= 10"
        out.append(f"| {r['name']} | {r['degree']} | "
                   f"{r['ss_refs'] if r['ss_refs'] is not None else '—'} | "
                   f"{'y' if r['index_consumed'] else 'n'} | "
                   f"{r['prompt_consumers']} | {why or '—'} |")
    if not gates:
        out.append("(none)")
    out += ["", "## Propose (degree 3–9)", "",
            "| item | degree | ss_refs | module-split? |", "|---|---|---|---|"]
    for r in sorted(props, key=lambda r: -r["degree"]):
        out.append(f"| {r['name']} | {r['degree']} | "
                   f"{r['ss_refs'] if r['ss_refs'] is not None else '—'} | "
                   f"{'yes' if r['module_split_required'] else 'no'} |")
    if not props:
        out.append("(none)")
    out += ["", "## Auto-safe (degree <=2)", ""]
    for r in safe:
        out.append(f"- {r['name']} (degree {r['degree']})")
    if not safe:
        out.append("(none)")
    out += ["", "## Interface-stability exemptions (amendment #7)", "",
            "Exempt from the module-split rule only — a bugfix to a stable "
            "interface is not pleiotropic damage. Rung verdicts unchanged.", ""]
    for r in exempt:
        out.append(f"- {r['name']} — degree {r['degree']}, rung "
                   f"{r['rung']}: {r['interface_stability_exempt']}")
    if not exempt:
        out.append("(none)")
    out += ["", "## Module-split candidates (degree >=5, not exempt)", ""]
    for r in splits:
        out.append(f"- {r['name']} (degree {r['degree']})")
    if not splits:
        out.append("(none)")
    out += ["", "*Report-only first build. Gate enforcement is a later, "
                "flagged decision; the graph JSON beside this report carries "
                "the full consumer lists.*"]
    return "\n".join(out) + "\n", today


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=30,
                    help="signal window for the synaptic substrate (default 30)")
    ap.add_argument("--replay", metavar="FILENAME",
                    help="replay one change through the gate and print the "
                         "verdict (e.g. --replay atomic_io.py)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if args.replay:
        items = collect_items()
        sources = build_consumer_sources()
        rows = score(items, sources)
        hits = [r for r in rows if r["name"] == args.replay]
        if not hits:
            print(f"no item named {args.replay} in the graph", file=sys.stderr)
            return 1
        r = hits[0]
        print(f"gate replay: {r['name']}")
        print(f"  degree={r['degree']} ss_refs={r['ss_refs']} "
              f"index_consumed={r['index_consumed']} "
              f"prompt_consumers={r['prompt_consumers']}")
        print(f"  rung: {r['rung']}")
        print(f"  module-split required: {r['module_split_required']}")
        if r["interface_stability_exempt"]:
            print(f"  interface-stability exemption APPLIES: "
                  f"{r['interface_stability_exempt']}")
        return 0

    items = collect_items()
    sources = build_consumer_sources()
    rows = score(items, sources)
    report, today = render_report(rows, args.days)
    OUT.mkdir(parents=True, exist_ok=True)
    graph = {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(),
        "note": "consumer-degree graph + degree->rung policy verdicts; "
                "report-only first build (amendment #7)",
        "exemptions": EXEMPT_INTERFACE_STABILITY,
        "items": rows,
    }
    gp = OUT / f"graph-{today}.json"
    rp = OUT / f"report-{today}.md"
    atomic_write(gp, json.dumps(graph, indent=1))
    atomic_write(rp, report)
    print(f"wrote {gp}")
    print(f"wrote {rp}")
    print(f"items={len(rows)} gates="
          f"{sum(1 for r in rows if r['rung'] == 'josh-gate+fixture')} "
          f"propose={sum(1 for r in rows if r['rung'] == 'propose')} "
          f"auto-safe={sum(1 for r in rows if r['rung'] == 'auto-safe')}")
    return 0


def selftest():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="pleio-selftest-"))
    # item with 1 consumer -> auto-safe
    (tmp / "low.md").write_text("low pleiotropy item")
    (tmp / "c1.md").write_text("mentions low item")
    # item with 5 consumers -> propose + module-split
    (tmp / "mid.md").write_text("mid pleiotropy item")
    for i in range(5):
        (tmp / f"m{i}.md").write_text("references mid")
    # item with 12 consumers -> josh-gate
    (tmp / "high.md").write_text("high pleiotropy item")
    for i in range(12):
        (tmp / f"h{i}.md").write_text("references high")
    # prompt-embedded -> maximal regardless of degree
    (tmp / "prompt.md").write_text("runtime guard example")
    agents_dir = tmp / "agents"
    agents_dir.mkdir()
    (agents_dir / "some-agent.md").write_text(
        "embeds runtime guard example in a prompt")
    srcs = [(str(p), _load(p)) for p in sorted(tmp.rglob("*.md"))]
    fake_items = {tmp / n: None for n in
                  ("low.md", "mid.md", "high.md", "prompt.md")}
    PROMPT_SOURCE_PREFIXES.append(str(agents_dir))
    rows = score(fake_items, srcs, index_text="")  # synthetic index: none
    by = {r["name"]: r for r in rows}
    assert by["low.md"]["rung"] == "auto-safe", by["low.md"]
    assert by["mid.md"]["rung"] == "propose", by["mid.md"]
    assert by["mid.md"]["module_split_required"] is True
    assert by["high.md"]["rung"] == "josh-gate+fixture", by["high.md"]
    assert by["prompt.md"]["maximal_uncountable"] is True
    assert by["prompt.md"]["rung"] == "josh-gate+fixture"
    assert by["prompt.md"]["degree"] == 1  # maximal is the policy, not degree
    # exemption: atomic_io.py never module-split regardless of degree
    r = {"name": "atomic_io.py", "degree": 20,
         "interface_stability_exempt": EXEMPT_INTERFACE_STABILITY["atomic_io.py"]}
    assert not (r["degree"] >= MODULE_SPLIT_FLOOR and
                not r["interface_stability_exempt"])
    print(f"selftest PASS ({tmp}) — rungs auto-safe/propose/josh-gate, "
          f"prompt-maximal guard, module-split floor, exemption all verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
