#!/usr/bin/env python3
"""synaptic-strength.py — one reinforcement pass over the knowledge tree.

Computes a strength score per knowledge file (domains/ + projects/) and per
INDEX.md line from a SINGLE signal join (proposal #5, Merge A):

  reads           knowledge-read events in garden-reports/usage-ledger.jsonl
  writes          git log --since per file (read-only git usage)
  inbound refs    distinct skills/*.md + INDEX.md files naming the basename
  corroboration   bus outbox (dreams/bus/*.jsonl) + bus/motifs.jsonl mentions
  last_verified   claims/claims.jsonl rows naming the file (max last_verified)

Salience override (amygdala/keystone): files named in claims, INDEX lines
carrying incident/prod/hotfix markers, or the keystone list are critical=true
and exempt from decay findings. Decayed files are DEMOTED-never-DELETE
candidates — this script only reports, it never touches the tree.

Zero-LLM. Output: garden-reports/strength-<date>.md (atomic_write).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from atomic_io import atomic_write  # noqa: E402

HOME = Path(os.path.expanduser("~"))
K = HOME / ".claude" / "knowledge"
USAGE = K / "garden-reports" / "usage-ledger.jsonl"
CLAIMS = K / "claims" / "claims.jsonl"
INDEX = K / "INDEX.md"
BUS = K / "dreams" / "bus"
MOTIFS = K / "bus" / "motifs.jsonl"
SKILLS = HOME / ".claude" / "skills"

# Keystone list: the files whose loss or corruption is organ-level. Kept
# literal (review #5 wording) — additive edits land here.
KEYSTONE = [
    "hr-genie.md",
    "workato-platform.md",
    "brain-gardener.md",
    "airo-mcp-playbook",
    "index.md",  # INDEX itself (compared lowercase)
]

# Salience markers on an INDEX line: incidents / prod / hotfix class.
SALIENCE_RE = re.compile(
    r"incident|prod\b|prod[- ]|hotfix|HOTFIX|outage|⛔|PROD\b|bsys-\d+|"
    r"hard rule|LAW|confirmed by live probe|LIVE PRODUCTION",
    re.IGNORECASE,
)

W_READS, W_WRITES, W_REFS, W_CORROB = 1.0, 2.0, 3.0, 2.0
RECENCY_BONUS = [(7, 10.0), (30, 5.0)]  # days -> bonus, first match wins
UNVERIFIED_DAYS = 30  # a claim verified within this window = "verified"
DECAY_DAYS = 45  # no signal of any kind for this long = decay finding


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def parse_iso(ts):
    """ISO-8601 with or without tz; bare dates (claims.jsonl '2026-10-09')
    are read as UTC midnight so every later subtraction stays tz-aware."""
    if not ts:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def git_changed_since(since_dt):
    """One git pass over the knowledge repo: path -> (commit_count, last_date).
    Read-only. Returns {} if the tree is not a repo or git fails."""
    out = {}
    try:
        iso = since_dt.strftime("%Y-%m-%dT%H:%M:%S%z")
        proc = subprocess.run(
            ["git", "-C", str(K), "log", f"--since={iso}", "--name-only",
             "--pretty=format:%cI"],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            return out
        current = None
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            if "T" in line[:11]:  # commit date line (ISO)
                current = parse_iso(line)
                continue
            if current is None:
                continue
            cnt, last = out.get(line, (0, None))
            out[line] = (cnt + 1, max(last, current) if last else current)
    except Exception:
        return out
    return out


def load_jsonl(path):
    rows = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # corrupt line: skip, never crash the pass
    except FileNotFoundError:
        pass
    return rows


def collect_signals(files, since_dt):
    reads = Counter()
    read_last = {}
    for row in load_jsonl(USAGE):
        if row.get("kind") not in ("knowledge-read", "knowledge-write"):
            continue
        ts = parse_iso(row.get("ts", ""))
        if ts and ts < since_dt:
            continue
        tgt = os.path.basename(str(row.get("target", ""))).lower()
        if not tgt:
            continue
        if row["kind"] == "knowledge-read":
            reads[tgt] += 1
            read_last[tgt] = max(read_last.get(tgt, ts), ts)
        else:
            # a write is a stronger read signal (the file was live in a session)
            reads[tgt] += 2
            read_last[tgt] = max(read_last.get(tgt, ts), ts)

    gitmap = git_changed_since(since_dt)

    # inbound refs: basename mentioned in any skills .md or INDEX.md
    ref_index = []  # (source_path, lowercase_text)
    try:
        ref_index.append((str(INDEX), INDEX.read_text(errors="ignore").lower()))
    except FileNotFoundError:
        pass
    if SKILLS.is_dir():
        for p in SKILLS.rglob("*.md"):
            try:
                ref_index.append((str(p), p.read_text(errors="ignore").lower()))
            except OSError:
                continue

    # corroboration: mentions across bus outboxes + motifs
    bus_blobs = []
    for p in list(BUS.glob("*.jsonl")) + [MOTIFS]:
        try:
            bus_blobs.append(p.read_text(errors="ignore").lower())
        except OSError:
            continue
    bus_text = "\n".join(bus_blobs)

    # claims: file -> last verified date (max over claims naming the file)
    claims_by_file = {}
    for row in load_jsonl(CLAIMS):
        refs = [str(row.get("subject", "")), str(row.get("claim", ""))]
        for ev in row.get("evidence", []) or []:
            if isinstance(ev, dict):
                refs.append(str(ev.get("ref", "")))
        blob = " ".join(refs).lower()
        lv = parse_iso(row.get("last_verified", "")) or parse_iso(
            row.get("asserted_at", ""))
        for f in files:
            base = f.path.name.lower()
            stem = f.path.stem.lower()
            if base in blob or (stem in blob and len(stem) > 6):
                cur = claims_by_file.get(f.path.name)
                if lv and (cur is None or lv > cur):
                    claims_by_file[f.path.name] = lv
    return reads, read_last, gitmap, ref_index, bus_text, claims_by_file


class KFile:
    def __init__(self, path, kind, line_no=None, line_text=None):
        self.path = path
        self.kind = kind          # "file" | "index-line"
        self.line_no = line_no
        self.line_text = line_text
        self.reads = 0
        self.read_last = None
        self.writes = 0
        self.write_last = None
        self.refs = 0
        self.corrob = 0
        self.last_verified = None
        self.critical = False
        self.critical_why = []

    @property
    def name(self):
        return self.path.name if self.kind == "file" else f"INDEX.md:{self.line_no}"

    @property
    def last_signal(self):
        sigs = [t for t in (self.read_last, self.write_last) if t]
        return max(sigs) if sigs else None

    def days_since_signal(self):
        ls = self.last_signal
        return (now_utc() - ls).days if ls else None

    def strength(self):
        s = (W_READS * self.reads + W_WRITES * self.writes +
             W_REFS * self.refs + W_CORROB * self.corrob)
        ls = self.last_signal
        if ls:
            for days, bonus in RECENCY_BONUS:
                if (now_utc() - ls).days <= days:
                    s += bonus
                    break
        return round(s, 1)

    def verified_fresh(self):
        return (self.last_verified is not None and
                (now_utc() - self.last_verified).days <= UNVERIFIED_DAYS)


def build_files():
    """domains/*.md + projects/*.md plus INDEX.md list lines."""
    files = [KFile(p, "file") for p in sorted((K / "domains").glob("*.md"))]
    files += [KFile(p, "file") for p in sorted((K / "projects").glob("*.md"))]
    try:
        lines = INDEX.read_text(errors="ignore").splitlines()
    except FileNotFoundError:
        lines = []
    for i, line in enumerate(lines, 1):
        if line.lstrip().startswith(("-", "*")):
            files.append(KFile(INDEX, "index-line", line_no=i, line_text=line))
    return files


def annotate(files, signals):
    reads, read_last, gitmap, ref_index, bus_text, claims = signals
    for f in files:
        base = f.path.name.lower()
        f.reads = reads.get(base, 0)
        f.read_last = read_last.get(base)
        rel = str(f.path.relative_to(K)) if f.kind == "file" else None
        if rel and rel in gitmap:
            f.writes, f.write_last = gitmap[rel]
        if f.kind == "file":
            needle = base
            f.refs = sum(1 for _, blob in ref_index if needle in blob)
            f.corrob = bus_text.count(base)
        else:
            # index line: refs via the line's own target path, corroboration
            # via the whole line's distinctive content is unreliable — use
            # the target file basename if present in the line
            m = re.search(r"\(([^)]+\.md)\)", f.line_text or "")
            tgt = os.path.basename(m.group(1)).lower() if m else None
            if tgt:
                f.refs = sum(1 for _, blob in ref_index if tgt in blob)
                f.corrob = bus_text.count(tgt)
        if f.path.name in claims:
            f.last_verified = claims[f.path.name]

        # salience override. INDEX-as-keystone is FILE-level (reported once in
        # the keystone section, not stamped on all 50 lines — a per-line stamp
        # makes the decay exemption meaningless).
        why = []
        if f.kind == "file" and base in KEYSTONE:
            why.append("keystone-list")
        if f.path.name in claims:
            why.append("named-in-claims")
        if f.kind == "index-line" and SALIENCE_RE.search(f.line_text or ""):
            why.append("index-line-incident-marker")
        if f.kind == "file":
            m = re.search(r"\(([^)]+\.md)\)", "")
            # files: also critical if an INDEX line pointing at them carries
            # an incident marker
            for line_f in [x for x in files if x.kind == "index-line"]:
                m2 = re.search(r"\(([^)]+\.md)\)", line_f.line_text or "")
                if m2 and os.path.basename(m2.group(1)).lower() == base:
                    if SALIENCE_RE.search(line_f.line_text):
                        why.append("index-line-incident-marker")
                        break
        if why:
            f.critical = True
            f.critical_why = sorted(set(why))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30,
                    help="signal window for reads/git (default 30)")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--decay-days", type=int, default=DECAY_DAYS)
    args = ap.parse_args()

    since = now_utc() - dt.timedelta(days=args.days)
    files = build_files()
    signals = collect_signals(files, since)
    annotate(files, signals)

    live = [f for f in files if f.kind == "file"]
    lines = [f for f in files if f.kind == "index-line"]

    # strongest-unverified: strong signal, no fresh verified claim
    unverified = [f for f in live if not f.verified_fresh()]
    unverified.sort(key=lambda f: f.strength(), reverse=True)
    top_unverified = unverified[: args.top]

    # most-decayed: non-critical, has at least one signal, old
    def decay_key(f):
        d = f.days_since_signal()
        return d if d is not None else 9999

    decayed = [f for f in live
               if not f.critical and f.last_signal is not None
               and decay_key(f) >= args.decay_days]
    decayed.sort(key=decay_key, reverse=True)
    top_decayed = decayed[: args.top]

    silent = [f for f in live
              if not f.critical and f.last_signal is None
              and not f.verified_fresh()]

    # over-budget index lines flagged here too (co-report, budget gate lives
    # in index-budget.py — this is the same join, one line per finding)
    keystone_files = [f for f in live if "keystone-list" in f.critical_why]
    salient_lines = [f for f in lines if f.critical]

    today = now_utc().strftime("%Y-%m-%d")
    out = []
    out.append(f"# Synaptic strength pass — {today}")
    out.append("")
    out.append(f"Signal window: {args.days}d reads/git; refs+corroboration all-time; "
               f"last_verified from claims/claims.jsonl. Zero-LLM, one signal join.")
    out.append("")
    out.append(f"Files scored: {len(live)} (domains+projects) · INDEX lines scored: {len(lines)} · "
               f"critical (decay-exempt): {sum(1 for f in live if f.critical)} files, "
               f"{sum(1 for f in lines if f.critical)} lines")
    out.append("")

    out.append(f"## Top {len(top_unverified)} strongest-unverified")
    out.append("")
    out.append("High reinforcement signal, no claim verified in the last "
               f"{UNVERIFIED_DAYS}d — these carry the most load on the least-checked legs.")
    out.append("")
    out.append("| file | strength | reads30 | writes30 | refs | bus | last_verified |")
    out.append("|---|---|---|---|---|---|---|")
    for f in top_unverified:
        lv = f.last_verified.strftime("%Y-%m-%d") if f.last_verified else "never"
        out.append(f"| {f.name} | {f.strength()} | {f.reads} | {f.writes} | "
                   f"{f.refs} | {f.corrob} | {lv} |")
    if not top_unverified:
        out.append("(none)")
    out.append("")

    out.append(f"## Top {len(top_decayed)} most-decayed (non-critical, >= {args.decay_days}d since last signal)")
    out.append("")
    out.append("Demote-never-delete candidates: shrink the INDEX line and/or "
               "move the file to a cold lane — this report never touches them.")
    out.append("")
    out.append("| file | days since last signal | last signal | strength | refs |")
    out.append("|---|---|---|---|---|")
    for f in top_decayed:
        ls = f.last_signal.strftime("%Y-%m-%d") if f.last_signal else "?"
        out.append(f"| {f.name} | {decay_key(f)} | {ls} | {f.strength()} | {f.refs} |")
    if not top_decayed:
        out.append("(none)")
    out.append("")

    out.append("## Silent files (no read/write/git signal in window, unverified, non-critical)")
    out.append("")
    if silent:
        for f in silent:
            out.append(f"- {f.name}")
    else:
        out.append("(none)")
    out.append("")

    out.append("## Keystone / critical (exempt from decay findings)")
    out.append("")
    out.append(f"- INDEX.md — keystone-index (file-level: the routing table itself)")
    for f in keystone_files:
        out.append(f"- {f.name} — {', '.join(f.critical_why)} (strength {f.strength()})")
    out.append("")
    out.append("## Salient INDEX lines (incident/prod/hotfix markers — decay-exempt)")
    out.append("")
    for f in salient_lines:
        out.append(f"- {f.name} — {', '.join(f.critical_why)} (strength {f.strength()}, "
                   f"{len((f.line_text or '').encode())}B)")
    out.append("")

    out.append("## INDEX over-budget lines (see index-budget.py for the full gate)")
    out.append("")
    budget_hits = [f for f in lines if len((f.line_text or "").encode()) > 400]
    budget_hits.sort(key=lambda f: len((f.line_text or "").encode()), reverse=True)
    for f in budget_hits:
        b = len((f.line_text or "").encode())
        out.append(f"- {f.name} — {b} bytes ({b / 400:.1f}x hard budget)")
    if not budget_hits:
        out.append("(none over 400B)")
    out.append("")

    out.append(f"*Method notes: `found` dates are discovery-not-last-fired in the canon "
               f"(see titer-report.py); reads and writes share the usage-ledger window; "
               f"INDEX line read counts are file-level (INDEX.md reads cannot be split per line) "
               f"and are not shown per line; corroboration = exact basename mentions across "
               f"dreams/bus/*.jsonl + bus/motifs.jsonl.*")

    dest = K / "garden-reports" / f"strength-{today}.md"
    atomic_write(dest, "\n".join(out) + "\n")
    print(f"wrote {dest}")
    print("\n".join(out))


if __name__ == "__main__":
    main()
