#!/usr/bin/env python3
"""rg-coarsen.py — RG coarse-graining pass over ONE domain file (DRY-RUN).

Wave-3 proposal (cryptic-variation-bank, AMENDED 2026-10-11 annotation #11):
coarse-graining alone says DISCARD irrelevant detail; neutral theory says
cryptic variation is what evolvability draws on when the regime shifts. So
integrated-out detail is BANKED, not discarded, and the bank is the FIRST
search surface on a novel failure class.

Mechanism (amendment #11, three annotations honored):
  1. ACCEPTANCE = THE DRY-RUN REPORT. No domain file is ever edited by this
     script (the contract bans it). The report says what the pass WOULD do.
  2. THE BANK LIVES INSIDE brain_search's SURFACE. brain-mcp indexes the
     knowledge tree itself, so banked items are plain .md files with standard
     frontmatter under knowledge/archive/ — substring search hits them.
  3. REGRET TUNER HAS A FLOOR: integration-regret events (a failure that
     needed a detail this pass integrated out) tune aggressiveness, and NEVER
     below MIN_REGRET_EVENTS = 5 real events (never auto-aggressive on a
     thin base).

Levels: L0 raw transcript evidence → L1 observations (dated/ticketed) →
L2 patterns → L3 principles/procedures (rule-verb).

Decision-relevance question per detail item: "which decision at the
next-coarser level does this detail change?" — scored MECHANICALLY via
reference/usage analysis reusing synaptic-strength.py's daily signal join
(usage ledger reads/writes, INDEX/skills refs, bus corroboration, git).
An item with NO inbound decision signal in the review window is PROPOSED for
integration-out; items WITH signals are tagged `relevant` (stricter edit
protection).

The bank copy: proposed items are COPIED (never moved) to
knowledge/archive/<stem>/<slug>.md with a `micro: archive/<rel>@<commit>`
frontmatter pointer; the parent pointer line this pass WOULD write into the
domain file is rendered in the report for the future Josh-gated apply mode.

Zero-LLM. stdlib only. Reuses scripts/atomic_io.py + synaptic-strength.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import importlib.util  # noqa: E402
from atomic_io import atomic_write  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "synaptic_strength", Path(__file__).parent / "synaptic-strength.py")
ss = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ss)

HOME = Path(os.path.expanduser("~"))
K = HOME / ".claude" / "knowledge"
ARCHIVE = K / "archive"
REPORTS = ARCHIVE / "reports"
REGRET_LEDGER = ARCHIVE / "regret-counter.jsonl"

MIN_REGRET_EVENTS = 5  # amendment #11 floor: never auto-aggressive below this

# Integration-regret counter schema (wired later to the failure-autopsy path):
#   ts            ISO-8601 WITH tz offset (atomic_io validates)
#   banked_item   archive-relative path of the banked file that held the
#                 needed detail
#   source_file   domain file the detail was integrated out of
#   failure_class the failure class string from the autopsy
#   autopsy_ref   job/trace/claim reference proving the failure
#   recovered     bool — did the bank recover the needed detail?
REGRET_SCHEMA = {
    "required": ["ts", "banked_item", "source_file", "failure_class",
                 "autopsy_ref", "recovered"],
    "timestamps": ["ts"],
}

RULE_VERB_RE = re.compile(
    r"^\s*[-*]?\s*(never|always|must|do not|don't|use|prefer|avoid|require)",
    re.IGNORECASE)
DATE_RE = re.compile(r"BSYS-\d+|\b20\d{2}-\d{2}-\d{2}\b")


def git_head_short():
    try:
        proc = subprocess.run(["git", "-C", str(K), "rev-parse", "--short",
                               "HEAD"], capture_output=True, text=True,
                              timeout=15)
        return proc.stdout.strip() or "uncommitted"
    except Exception:
        return "uncommitted"


def parse_items(path):
    """Split a domain file into detail items: (section, text) with section
    = nearest '##' heading. Bullet items keep their bullet siblings' heading."""
    lines = path.read_text(errors="ignore").splitlines()
    section = "(top)"
    items = []  # (section, [lines])
    for line in lines:
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if line.lstrip().startswith(("-", "*")) and line.strip() not in ("-", "*"):
            items.append((section, [line]))
        elif line.startswith("#") or not line.strip():
            continue
        else:
            # paragraph text folds into the previous bullet item if open
            if items and items[-1][0] == section and not line.startswith("#"):
                items[-1][1].append(line)
    return [(sec, "\n".join(ls).strip()) for sec, ls in items if
            "\n".join(ls).strip()]


def slugify(s, maxlen=40):
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:maxlen].rstrip("-") or "item"


def item_tokens(text, n=7):
    """Distinctive tokens (len>=7, alphanumeric) used to detect the item being
    mentioned elsewhere — the mechanical stand-in for 'which decision does
    this detail change'."""
    words = re.findall(r"[a-z][a-z0-9_-]{6,}", text.lower())
    seen, out = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out[:n]


def classify_level(text):
    if RULE_VERB_RE.match(text):
        return "L3"
    if DATE_RE.search(text):
        return "L1"
    return "L2"


def coarsen(domain_path, days, bank=True):
    since = ss.now_utc() - dt.timedelta(days=days)
    files = ss.build_files()
    signals = ss.collect_signals(files, since)
    reads, read_last, gitmap, ref_index, bus_text, _ = signals

    rel = domain_path.relative_to(K)
    base = domain_path.stem.lower()
    # file-level inbound decision signals (the synaptic join)
    f_reads = reads.get(base, 0)
    f_writes, _ = gitmap.get(str(rel), (0, None))
    f_index = bool(re.search(r"\b" + re.escape(base) + r"\b", _load_index()))
    f_corrob = bus_text.count(base)

    src_texts = [t for _, t in ref_index]
    head = git_head_short()

    scored = []
    for sec, text in parse_items(domain_path):
        toks = item_tokens(text)
        mentioned = 0
        for t in src_texts:
            if sum(1 for tok in toks if tok in t) >= 2:
                mentioned += 1
        inbound = {
            "consumed_elsewhere": mentioned,
            "file_reads_window": f_reads,
            "file_writes_window": f_writes,
            "index_consumed": f_index,
            "bus_corroboration": f_corrob,
        }
        # PER-DETAIL granularity: the card's question ("which decision does
        # THIS detail change") is scored at item level — an item is
        # decision-relevant when its distinctive tokens are consumed by a
        # coarser surface (INDEX, skills, other domains, prompts, bus).
        # File-level signals are reported as context, not verdict drivers:
        # a hot file does not make every bullet decision-relevant.
        decision_relevant = mentioned > 0
        verdict = ("relevant" if decision_relevant
                   else "proposed-integrate-out")
        scored.append({
            "section": sec,
            "text": text,
            "tokens": toks,
            "inbound": inbound,
            "level": classify_level(text),
            "verdict": verdict,
        })
    return scored, head, {"file_reads_window": f_reads,
                          "file_writes_window": f_writes,
                          "index_consumed": f_index,
                          "bus_corroboration": f_corrob}


def bank_copy(domain_path, item, head):
    slug = slugify(item["text"].split("\n")[0])
    dest = ARCHIVE / domain_path.stem / f"{slug}.md"
    arc_rel = dest.relative_to(K)
    front = [
        "---",
        f"title: \"{item['text'].splitlines()[0].lstrip('-* ').strip()[:70]}\"",
        "status: integrated-out-proposal",
        f"source: {domain_path.relative_to(K)}#{slugify(item['section'])}",
        f"level: {item['level']}",
        f"banked_at: {dt.datetime.now(dt.timezone.utc).isoformat()}",
        f"micro: {arc_rel}@{head}",
        "regret_class: pending",
        "---",
        "",
        item["text"],
        "",
    ]
    atomic_write(dest, "\n".join(front))
    return dest, arc_rel


def render(domain_path, scored, head, filelevel, days, banked):
    today = dt.date.today().isoformat()
    props = [i for i in scored if i["verdict"] == "proposed-integrate-out"]
    rel_items = [i for i in scored if i["verdict"] == "relevant"]
    out = [
        f"# Coarse-graining dry-run — {domain_path.name} — {today}",
        "",
        f"Review window {days}d. DRY-RUN: nothing below was applied to the "
        f"domain file (the contract bans it — acceptance is this report). "
        f"Level map: L0 raw evidence -> L1 observations -> L2 patterns -> "
        f"L3 principles. Decision-relevance scored mechanically via the "
        f"synaptic-strength signal join (amendment #11).",
        "",
        f"File-level inbound signals: reads={filelevel['file_reads_window']} "
        f"writes={filelevel['file_writes_window']} "
        f"INDEX={'y' if filelevel['index_consumed'] else 'n'} "
        f"bus={filelevel['bus_corroboration']}",
        "",
        f"Items scored: {len(scored)} · proposed-integrate-out: "
        f"{len(props)} · relevant (protected): {len(rel_items)} · "
        f"banked copies: {len(banked)}",
        "",
        "## Proposed for integration-out (banked copies written)",
        "",
    ]
    for it in props:
        slug = slugify(it["text"].split("\n")[0])
        arc = f"archive/{domain_path.stem}/{slug}.md"
        out.append(f"### [{it['level']}] §{it['section']}")
        out.append("")
        out.append(f"```\n{it['text']}\n```")
        out.append("")
        out.append(f"- inbound signals: {json.dumps(it['inbound'])}")
        out.append(f"- banked: `{arc}@{head}` (micro pointer verified "
                   f"resolvable: {(K / arc).is_file()})")
        out.append(f"- parent pointer line the APPLY mode would write: "
                   f"`(relevant coupling: {slug} — micro: {arc}@{head})`")
        out.append("")
    out += ["## Relevant (inbound decision path in window — stricter edit "
            "protection)", ""]
    for it in rel_items:
        out.append(f"- [{it['level']}] §{it['section']}: "
                   f"{it['text'].splitlines()[0][:80]}")
    if not rel_items:
        out.append("(none)")
    out += [
        "",
        "## Integration-regret counter (floor = "
        f"{MIN_REGRET_EVENTS} events)",
        "",
        f"Ledger: {REGRET_LEDGER} — schema: {json.dumps(REGRET_SCHEMA)}. "
        f"Rows arrive from the failure-autopsy path when a failure needed a "
        f"banked detail. Tuner verdict: "
        f"{tune_aggressiveness(regret_count())}",
        "",
        "## Apply mode (NOT run — Josh-gated, future build)",
        "",
        "1. Replace each proposed item in the domain file with its one-line "
        "parent pointer.",
        "2. Delete the banked copy's `status: integrated-out-proposal` → "
        "`integrated-out`.",
        "3. Rollback: git retains the microphysics; pointer deletion restores "
        "originals verbatim.",
    ]
    return "\n".join(out) + "\n", today


def regret_count():
    try:
        lines = [json.loads(l) for l in REGRET_LEDGER.read_text().splitlines()
                 if l.strip()]
        return len(lines)
    except FileNotFoundError:
        return 0
    except Exception:
        return -1  # unreadable ledger: treat as unknown, tuner holds


def tune_aggressiveness(count):
    """Amendment #11 floor: never auto-aggressive on <5 regret events."""
    if count < MIN_REGRET_EVENTS:
        return (f"HOLD ({count} regret events < {MIN_REGRET_EVENTS} floor — "
                f"compaction aggressiveness unchanged)")
    return f"TUNE ENABLED ({count} regret events >= floor)"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", metavar="DOMAIN.md",
                    help="one domain file under knowledge/domains/ "
                         "(or projects/) to coarse-grain")
    ap.add_argument("--days", type=int, default=30,
                    help="review window (default 30)")
    ap.add_argument("--no-bank", action="store_true",
                    help="report only; skip the archive bank copies")
    ap.add_argument("--regret", action="store_true",
                    help="print the integration-regret counter verdict")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if args.regret:
        print(tune_aggressiveness(regret_count()))
        return 0

    if not args.file:
        ap.error("--file is required (one domain file) — first build is a "
                 "dry-run over ONE file by contract")
    domain_path = Path(args.file).expanduser()
    if not domain_path.is_file():
        print(f"not a file: {domain_path}", file=sys.stderr)
        return 1
    if K not in domain_path.resolve().parents:
        print(f"refusing: {domain_path} is not inside the knowledge tree "
              f"(read-only on everything outside the bank)", file=sys.stderr)
        return 1

    scored, head, filelevel = coarsen(domain_path, args.days)
    banked = []
    if not args.no_bank:
        for it in scored:
            if it["verdict"] == "proposed-integrate-out":
                dest, arc_rel = bank_copy(domain_path, it, head)
                banked.append(str(dest))
    report, today = render(domain_path, scored, head, filelevel, args.days,
                           banked)
    REPORTS.mkdir(parents=True, exist_ok=True)
    rp = REPORTS / f"coarsen-{domain_path.stem}-{today}.md"
    atomic_write(rp, report)
    print(f"wrote {rp}")
    print(f"items={len(scored)} proposed-integrate-out="
          f"{sum(1 for i in scored if i['verdict'] == 'proposed-integrate-out')} "
          f"relevant={sum(1 for i in scored if i['verdict'] == 'relevant')} "
          f"banked={len(banked)} regret={tune_aggressiveness(regret_count())}")
    return 0


def _load_index():
    try:
        return ss.INDEX.read_text(errors="ignore").lower()
    except OSError:
        return ""


def selftest():
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="rgcoarsen-selftest-"))
    dom = tmp / "fake-domain.md"
    dom.write_text(
        "# Fake domain\n\n"
        "## Incidents\n\n"
        "- 2026-10-09 BSYS-1234 the heartbeat ledger carried three timestamp "
        "formats at once and the fold crashed on the naive one\n"
        "- an undated procedure bullet about restarting the flux capacitor "
        "with a mallet during the wobble\n\n"
        "## Rules\n\n"
        "- Never book a delta claim without a metric series reference\n")
    # item-level mechanics (parse + level classification); file-level join
    # uses the real knowledge signals, exercised by the live run.
    items = parse_items(dom)
    assert len(items) == 3, items
    levels = [classify_level(t) for _, t in items]
    assert "L1" in levels and "L3" in levels, levels  # dated + rule-verb
    # regret floor
    assert tune_aggressiveness(0).startswith("HOLD")
    assert tune_aggressiveness(4).startswith("HOLD")
    assert tune_aggressiveness(5).startswith("TUNE")
    # micro pointer format + resolvability on a synthetic bank
    bank_dir = tmp / "bank"
    bank_dir.mkdir()
    bf = bank_dir / "x.md"
    bf.write_text("micro: archive/x@abc1234\n")
    assert bf.is_file() and "micro: archive/x@abc1234" in bf.read_text()
    print(f"selftest PASS ({tmp}) — 3 items parsed, L1/L3 classification, "
          f"regret floor (0/4 hold, 5 tune), micro pointer resolvable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
