#!/usr/bin/env python3
"""gossip-read.py — merged read view of the agent gossip bus.

Each agent writes ONLY its own outbox: knowledge/dreams/bus/<agent>.jsonl.
This script merges all outboxes, sorts by time, tallies corroborations per
thread, applies TTL expiry, and prints the timeline (or thread/agent slices).

Usage:
  gossip-read.py [--since 24h|7d|all] [--thread SLUG] [--agent NAME]
                 [--independence] [--motif] [--bus DIR] [--json]

Epistemics (2026-10-11 patch, review proposal #4 / Merge E):

  PATTERN requires EVIDENCE-BEARING corroboration: at least one event from
  a DIFFERENT agent than the thread finder that carries its own evidence.

  What counts as evidence-bearing (design choice, documented):
    * kind == "verify" — evidence-bearing BY CONSTRUCTION. The GOSSIP.md
      protocol defines verify as 'append ... with YOUR independent
      evidence', and real verify posts in the wild embed their evidence
      (job IDs, trace lines) in prose rather than in a field. Requiring a
      structured field on verify would retroactively de-count every
      existing thread — not backward compatible.
    * any other post (kind "finding" included) only when it carries a
      NON-EMPTY evidence field: `refs` (the bus's canonical evidence
      pointer per GOSSIP.md 'Nothing goes on the bus without a ref'), or
      an explicit `evidence` / `detail` field. Prose fields (line / note /
      text) are DISCUSSION and deliberately do NOT count — two agents
      restating the same observation in prose is the false-PATTERN defect
      this patch fixes (verified 2026-10-11: two plain findings rendered
      'PATTERN 0x 2 witnesses' on the pre-patch script).

  Tag ladder: OBS = unverified observation (no evidence-bearing
  corroboration yet), PATTERN = at least one evidence-bearing corroboration
  from a different agent. Self-verifies (an agent verifying its own
  finding) are counted separately and never count toward PATTERN.

Witness independence labels (--independence):
  anchored     a witness whose first post on the thread came AFTER the
               thread already existed in the merged read — they joined a
               thread they could see, so their corroboration may be
               anchored to the earlier post rather than to the underlying
               fact.
  independent  the witness that OPENS the thread in the merged window —
               first-in-window is the best available evidence of
               independence. HONESTY CAVEAT: a same-window first
               observation is NOT retroactively provable as independent;
               the opener may have been anchored to a source outside the
               window (same upstream alert, same Slack ping). The label
               means 'first in window', nothing stronger.
  unverifiable witnesses that cannot be ordered: posts with no parseable
               timestamp, or tied with the thread-opening second, where
               temporal ordering — the only evidence this mode has — is
               unavailable or ambiguous.
"""

import argparse
import calendar
import glob
import json
import os
import re
import sys
import time

BUS = os.path.expanduser("~/.claude/knowledge/dreams/bus")
MOTIFS = os.path.expanduser("~/.claude/knowledge/bus/motifs.jsonl")
VALID_KINDS = ("finding", "verify", "handoff", "proposal-ref")

EVIDENCE_FIELDS = ("refs", "evidence", "detail")


def parse_since(s):
    if not s or s == "all":
        return 0
    if s.endswith("h"):
        return time.time() - float(s[:-1]) * 3600
    if s.endswith("d"):
        return time.time() - float(s[:-1]) * 86400
    return time.time() - float(s) * 86400


def _ts(ts):
    """Epoch seconds for an ISO-8601 ts, timezone-aware.

    2026-10-16 fix: the old version sliced the Z off and fed the naive
    remainder to time.mktime (which assumes LOCAL time), so every UTC
    Z-suffixed row shifted by the local UTC offset (+4h in New York) —
    TTL expiry and the --since window were both wrong by that much.
    Z rows are UTC (calendar.timegm, no local shift); explicit +hh:mm
    offsets convert tz-aware; naive rows keep the legacy local reading;
    numeric-epoch strings pass through."""
    s = str(ts).strip()
    try:
        return float(s)
    except ValueError:
        pass
    try:
        t = time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
    except Exception:
        return 0.0
    if s.endswith("Z"):
        return calendar.timegm(t)
    m = re.search(r"([+-])(\d{2}):?(\d{2})$", s)
    if m:
        off = int(m.group(2)) * 3600 + int(m.group(3)) * 60
        return calendar.timegm(t) - (off if m.group(1) == "+" else -off)
    return time.mktime(t)


def thread_of(ev):
    """Thread key for an event: thread_id, subject, or thread (all three
    appear in the wild — bus_post.py writes subject+thread, older watchdog
    posts carry only thread)."""
    return ev.get("thread_id") or ev.get("subject") or ev.get("thread")


def has_own_evidence(ev):
    """True if the post carries its own evidence pointer.

    Evidence = a non-empty `refs`, `evidence`, or `detail` field. Prose
    (line/note/text) does NOT count — see module docstring for why.
    kind == "verify" is exempt: evidence-bearing by protocol definition.
    """
    if ev.get("kind") == "verify":
        return True
    for k in EVIDENCE_FIELDS:
        v = ev.get(k)
        if isinstance(v, str) and v.strip():
            return True
        if isinstance(v, (list, tuple)) and any(str(x).strip() for x in v):
            return True
    return False


def load_events(bus_dir, since, only_agent=None):
    cutoff = parse_since(since)
    now = time.time()
    events = []
    for path in sorted(glob.glob(os.path.join(bus_dir, "*.jsonl"))):
        agent_file = os.path.splitext(os.path.basename(path))[0]
        if only_agent and agent_file != only_agent:
            continue
        try:
            with open(path, errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        print(f"warn: {os.path.basename(path)}:{n} unparsable",
                              file=sys.stderr)
                        continue
                    if not isinstance(ev, dict):
                        # fail-open: a parseable non-object row (bare string,
                        # list, number) must warn-and-skip, never kill the
                        # whole merged read (found 2026-10-14 triage batch)
                        print(f"warn: {os.path.basename(path)}:{n} "
                              f"non-object row ({type(ev).__name__})",
                              file=sys.stderr)
                        continue
                    ev.setdefault("agent", agent_file)
                    events.append(ev)
        except OSError as e:
            print(f"warn: cannot read {path}: {e}", file=sys.stderr)

    # TTL expiry (skip events older than their ttl)
    fresh = []
    for ev in events:
        if not isinstance(ev.get("ts"), str):
            fresh.append(ev)
            continue
        ts = _ts(ev["ts"])
        if now - ts <= ev.get("ttl_days", 14) * 86400:
            fresh.append(ev)
    return [e for e in fresh
            if not isinstance(e.get("ts"), str)
            or _ts(e.get("ts")) >= cutoff]


def tally_threads(events):
    """Corroboration tally per thread. A corroboration = an event from a
    DIFFERENT agent than the finder that is evidence-bearing (see module
    docstring). Plain-discussion posts from other agents grow the witness
    set but never the corroboration count.

    2026-10-14 ORDER-DEPENDENCE FIX (found building the bus-actuator): the
    original single pass iterated events in FILE order (sorted glob =
    alphabetical agent name), so a witness whose outbox file sorts before
    the finder's was processed BEFORE the finder was set and mis-filed as a
    self-verify — real corroborations silently discarded (cortex.jsonl
    sorts before brain-gardener.jsonl; measured live: a 3-witness thread
    with a verify + corroboration tallied 0 corroborations). Also, finder
    was only set on kind=="finding", so a defect-opened thread could NEVER
    corroborate (finder None forever). Now: pass 1 settles the finder per
    thread = agent of the EARLIEST (ts_sort_key) post of kind finding|defect,
    falling back to the earliest post of any kind; pass 2 counts."""
    per = {}
    for ev in events:
        tid = thread_of(ev)
        if not tid:
            continue
        per.setdefault(tid, []).append(ev)

    tallies = {}
    for tid, evs in per.items():
        t = tallies.setdefault(tid, {"corroborations": 0, "witnesses": set(),
                                     "subject": evs[0].get("subject", tid),
                                     "finder": None})
        finder_pool = [e for e in evs if e.get("kind") in ("finding", "defect")]
        finder_ev = min(finder_pool or evs, key=ts_sort_key)
        t["finder"] = finder_ev.get("agent")

    for tid, evs in per.items():
        t = tallies[tid]
        for ev in evs:
            if ev.get("kind") in ("verify", "corroboration"):
                if t["finder"] and ev.get("agent") != t["finder"]:
                    t["corroborations"] += 1
                else:
                    t.setdefault("self_verifies", 0)
                    t["self_verifies"] += 1
            elif (ev.get("kind") == "finding"
                  and t["finder"] and ev.get("agent") != t["finder"]
                  and has_own_evidence(ev)):
                # a second agent independently observing WITH its own evidence
                t["corroborations"] += 1
            t["witnesses"].add(ev.get("agent", "?"))
    for tid, t in tallies.items():
        t["witness_count"] = len(t["witnesses"])
    return tallies


def classify_witnesses(events):
    """Split per-thread witnesses into independent / anchored / unverifiable.

    See module docstring for the label semantics and the honesty caveat on
    'independent' (first-in-window is provisional, not provable).
    """
    per = {}
    for ev in events:
        tid = thread_of(ev)
        if not tid:
            continue
        per.setdefault(tid, []).append(ev)

    out = {}
    for tid, evs in per.items():
        # earliest parseable ts per agent on this thread
        agent_ts = {}
        unparsed = set()
        for ev in evs:
            ag = ev.get("agent", "?")
            ts = ev.get("ts")
            t = _ts(ts) if isinstance(ts, str) else None
            if t is None or t == 0.0:
                unparsed.add(ag)
                continue
            if ag not in agent_ts or t < agent_ts[ag]:
                agent_ts[ag] = t
        counts = {"independent": 0, "anchored": 0, "unverifiable": 0}
        labels = {}
        if agent_ts:
            open_t = min(agent_ts.values())
            openers = [a for a, t in agent_ts.items() if t == open_t]
            if len(openers) == 1:
                counts["independent"] += 1
                labels[openers[0]] = "independent"
            else:
                # tie at the opening second: ordering is ambiguous
                counts["unverifiable"] += len(openers)
                for a in openers:
                    labels[a] = "unverifiable"
            for ag, t in agent_ts.items():
                if t > open_t:
                    counts["anchored"] += 1
                    labels[ag] = "anchored"
        for ag in unparsed:
            counts["unverifiable"] += 1
            labels[ag] = "unverifiable"
        out[tid] = {"counts": counts, "labels": labels,
                    "witnesses": sorted(labels)}
    return out


def load_motifs(path=MOTIFS):
    motifs = {}
    if not os.path.exists(path):
        return motifs
    with open(path, errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                m = json.loads(line)
            except Exception:
                print(f"warn: motifs.jsonl:{n} unparsable", file=sys.stderr)
                continue
            slug = m.get("motif")
            if slug:
                motifs[slug] = m
    return motifs


def motif_of(ev, motif_slugs):
    """The motif slug a post cites: explicit `motif` field first, else an
    exact slug match on its thread key (thread_id / subject / thread)."""
    m = ev.get("motif")
    if isinstance(m, str) and m.strip():
        return m.strip()
    tid = thread_of(ev)
    if tid and tid in motif_slugs:
        return tid
    return None



def ts_sort_key(e):
    """Comparable key across MIXED ts shapes: ISO strings (Z / offset /
    naive), epoch floats/ints, epoch-STRINGS, None. (Strike 3 on this bug
    class: turn-audit.jsonl carries raw epoch floats; a str() key breaks
    float-vs-str comparison. 2026-10-16: shape-GROUPING first avoided the
    crash but still mis-ordered — every numeric row landed before every
    string row regardless of real time. Now every parsable shape normalizes
    to epoch via _ts (tz-aware) and interleaves chronologically; only
    unparsable/missing rows sink to the end group."""
    ts = e.get("ts")
    if isinstance(ts, bool):
        return (2, 0.0)
    if isinstance(ts, (int, float)):
        return (0, float(ts))
    if isinstance(ts, str) and ts:
        v = _ts(ts)
        return (0, v) if v else (2, 0.0)
    return (2, 0.0)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="24h")
    ap.add_argument("--thread", default=None)
    ap.add_argument("--agent", default=None)
    ap.add_argument("--independence", action="store_true",
                    help="per-thread witness independence report")
    ap.add_argument("--motif", action="store_true",
                    help="motif registry corroboration report")
    ap.add_argument("--bus", default=None,
                    help="override bus directory (default: ~/.claude/knowledge/dreams/bus); for tests, never writes")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    bus_dir = a.bus or BUS
    events = load_events(bus_dir, a.since, only_agent=a.agent)

    if a.motif:
        motifs = load_motifs()
        if not motifs:
            print(f"no motifs loaded from {MOTIFS}")
            return 1
        stats = {slug: {"count": 0, "agents": set()} for slug in motifs}
        for ev in events:
            slug = motif_of(ev, motifs)
            if slug in stats:
                stats[slug]["count"] += 1
                stats[slug]["agents"].add(ev.get("agent", "?"))
        if a.json:
            print(json.dumps({slug: {**motifs[slug], "posts": s["count"],
                                     "agents": sorted(s["agents"])}
                              for slug, s in stats.items()}, indent=1))
            return 0
        print(f"motif registry ({len(motifs)} motifs, posts in window "
              f"{a.since} citing each):")
        for slug, m in sorted(motifs.items(),
                              key=lambda kv: (-stats[kv[0]]["count"],
                                              kv[0])):
            s = stats[slug]
            agents = ",".join(sorted(s["agents"])) or "-"
            print(f'  {s["count"]:>3}x  {slug:38} [{agents}]  '
                  f'{m.get("definition", "")[:70]}')
        return 0

    tallies = tally_threads(events)

    if a.thread:
        events = [e for e in events if thread_of(e) == a.thread]

    events.sort(key=ts_sort_key)
    if a.json:
        print(json.dumps({"timeline": events, "threads": {
            k: {**v, "witnesses": sorted(v["witnesses"])}
            for k, v in sorted(tallies.items(),
                               key=lambda kv: (-kv[1]["corroborations"],
                                               -kv[1]["witness_count"]))}},
            indent=1))
        return 0

    if not events:
        print("the bus is quiet (no events in window)")
        return 0

    for ev in events:
        ts = ev.get("ts") if isinstance(ev.get("ts"), str) else "?"
        body = str(ev.get("line") or ev.get("text") or ev.get("note") or "")
        print(f'{ts[:16]:16} [{ev.get("agent", "?"):22}] '
              f'{ev.get("kind", "?"):12} '
              f'{str(ev.get("subject") or ev.get("thread") or "?"):28} '
              f'{body[:110]}')

    if a.independence:
        print()
        print("witness independence per thread:")
        cls = classify_witnesses(events)
        for tid, c in sorted(cls.items(),
                             key=lambda kv: (-(kv[1]["counts"]["independent"]
                                               + kv[1]["counts"]["anchored"]),
                                             kv[0])):
            if a.thread and tid != a.thread:
                continue
            n = c["counts"]
            wl = ", ".join(f'{ag}:{c["labels"].get(ag, "?")}'
                           for ag in c["witnesses"])
            print(f'  {tid[:52]:52} ind={n["independent"]} '
                  f'anch={n["anchored"]} unver={n["unverifiable"]}  {wl}')
        return 0

    print()
    print("threads by corroboration (PATTERN needs evidence-bearing "
          "corroboration from a different agent; prose-only agreement "
          "stays OBS):")
    for tid, t in sorted(tallies.items(),
                         key=lambda kv: (-kv[1]["corroborations"],
                                         -kv[1]["witness_count"]))[:10]:
        self_v = t.get("self_verifies", 0)
        tag = "PATTERN  " if t["corroborations"] >= 1 else "OBS      "
        note = f'  (+{self_v} self-checks, not counted)' if self_v else ''
        print(f'  {tag} {t["corroborations"]}x  {t["witness_count"]} witnesses  '
              f'{tid[:56]}{note}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
