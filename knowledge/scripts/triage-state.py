#!/usr/bin/env python3
"""triage-state.py — state assembly for triage findings (the iteration-3 layer).

The dissenter's read of the 2026-10-14 UAT: Josh's verdict function is
"is the next action MINE and not already covered by a lane" — and the finding
text doesn't carry that. This module assembles the missing state for one
finding, using ONLY what was knowable at verdict time (no leakage):

  lane semantics    what the source's lane is and how Josh treats its reports
  finding history   prior transitions of this slug (status + Josh's decision
                    notes) with decided_ts < T  (the verdict row's own note/
                    jira fields are EXCLUDED — written at verdict time)
  sibling verdicts  other slugs sharing a recipe-id or ticket-key, decided
                    before T ("2 siblings on recipe 82090477 already rejected")
  ticket coverage   ticket keys from PRIOR decision notes/jira fields
                    (the verdict row's own `jira` only counts for
                    jira-autotriage, where the ticket pre-exists the finding)
  lexical flags     plan-ready / awaiting / superseded / done phrasing in the
                    finding's own text (title+evidence+work — pre-verdict)
  age               first-seen ts, re-report count, days old at decision

Usage:
  import triage_state
  idx = triage_state.build_index(queue_rows)
  state = triage_state.state_block(slug, verdict_row, idx)   # -> dict
  text  = triage_state.render(state)                          # judge-ready block
"""
from __future__ import annotations

import re
from collections import defaultdict

TICKET_RE = re.compile(r"\b(?:BSYS|BTSUP|HROPS|PSM|MCP|AAI|CT)-\d{3,6}\b", re.I)
RECIPE_RE = re.compile(r"\b(?:recipe[s]?\s*[#:]?\s*)?(\d{7,8})\b")

LEX_FLAGS = [
    ("plan-ready", re.compile(r"\bplan (is )?ready\b", re.I)),
    ("awaiting", re.compile(r"\bawaiting\b", re.I)),
    ("superseded", re.compile(r"\bsuperseded\b", re.I)),
    ("already-done", re.compile(r"\b(already (done|built|fixed|handled)|is done)\b", re.I)),
    ("root-cause-found", re.compile(r"\broot cause (found|identified)\b", re.I)),
    ("duplicate", re.compile(r"\b(duplicate|dup of)\b", re.I)),
    ("covered-elsewhere", re.compile(r"\b(covered by|fixed in|resolved in|filed as)\b", re.I)),
]

LANES = {
    "workato-health": ("automated watchdog lane — standing autopsy/fix-forward handlers "
                       "exist; Josh historically REJECTS re-reports of items already "
                       "autopsied or filed to Jira"),
    "ops-visibility": ("automated ops-monitoring lane — same pattern as workato-health: "
                       "re-reports of handled items get rejected"),
    "mission-control": ("escalation router — items here were already triaged once by "
                        "another lane; check whether the underlying incident was already "
                        "handled before surfacing"),
    "jira-autotriage": ("originates FROM an existing Jira ticket — a ticket for this "
                        "work exists by construction; the question is whether the next "
                        "action is Josh's"),
    "cortex": "cortex attention item — no auto-lane covers it; Josh-originated reasoning",
    "josh": "Josh-originated — no auto-lane covers it",
    "estate-architect": "weekly architecture review — advisory, batches with its own report",
    "brain-gardener": "knowledge-hygiene lane — low urgency by default",
    "triage-session": "meta item about the triage process itself",
}


def _t(row):
    return row.get("decided_ts") or row.get("ts") or ""


def extract_ids(*texts):
    tickets, recipes = set(), set()
    for t in texts:
        if not t:
            continue
        tickets |= {m.upper() for m in TICKET_RE.findall(t)}
        recipes |= set(RECIPE_RE.findall(t))
    return tickets, recipes


def build_index(rows):
    """rows: raw queue.jsonl dicts. Returns {slug: [rows sorted by time]}."""
    by_slug = defaultdict(list)
    for r in rows:
        if r.get("slug"):
            by_slug[r["slug"]].append(r)
    for rs in by_slug.values():
        rs.sort(key=_t)
    return by_slug


def _siblings(slug, verdict_row, T, by_slug):
    """Other slugs sharing a recipe-id or ticket-key with this finding, with
    at least one decided row before T."""
    _, my_recipes = extract_ids(verdict_row.get("slug", ""), verdict_row.get("title", ""),
                                verdict_row.get("evidence", ""))
    my_tickets, more_recipes = extract_ids(verdict_row.get("slug", ""))
    my_tickets |= {t for t in my_tickets}
    my_recipes |= more_recipes
    out = []
    for other, rs in by_slug.items():
        if other == slug:
            continue
        o_tick, o_rec = set(), set()
        decided = []
        for r in rs:
            o_t, o_r = extract_ids(r.get("slug", ""), r.get("title", ""), r.get("evidence", ""))
            o_tick |= o_t
            o_rec |= o_r
            if r.get("status") in ("accepted", "rejected", "built", "deferred") and _t(r) < T:
                decided.append(r)
        if decided and ((my_recipes & o_rec) or (my_tickets & o_tick)):
            shared = (my_recipes & o_rec) | (my_tickets & o_tick)
            out.append({"slug": other, "shared": sorted(shared),
                        "statuses": [f"{r['status']}@{_t(r)[:10]}" for r in decided]})
    return out


def state_block(slug, verdict_row, by_slug, as_of=None):
    """Assemble the state dict for one finding as-of its verdict time.
    Pass as_of (ISO ts) for LIVE open cards: state is 'everything knowable
    now', not what was knowable at a past verdict."""
    T = as_of or _t(verdict_row)
    rs = by_slug.get(slug, [])
    prior = [r for r in rs if r is not verdict_row and _t(r) < T]
    decided_prior = [r for r in prior
                     if r.get("status") in ("accepted", "rejected", "built", "deferred")]

    # ticket coverage from PRIOR rows only (notes + jira fields) — the verdict
    # row's own jira/note is verdict output, not prior state. Exception:
    # jira-autotriage findings are born from a pre-existing ticket.
    tickets, _ = extract_ids(*[f"{r.get('note', '')} {r.get('jira', '')}" for r in decided_prior])
    if (verdict_row.get("source") or "").startswith("jira-autotriage"):
        tickets |= extract_ids(verdict_row.get("jira", ""), slug)[0]

    text = " ".join(str(verdict_row.get(k, "")) for k in ("title", "evidence", "work"))
    flags = [name for name, rx in LEX_FLAGS if rx.search(text)]

    first_seen = rs[0].get("ts", "") if rs else ""
    age_days = None
    if first_seen and T:
        import datetime as dt
        try:
            f = dt.datetime.fromisoformat(first_seen.replace("Z", "+00:00"))
            t = dt.datetime.fromisoformat(T.replace("Z", "+00:00"))
            age_days = round((t - f).total_seconds() / 86400, 1)
        except ValueError:
            pass

    return {"as_of": T, "slug": slug, "source": verdict_row.get("source", ""),
            "lane": LANES.get((verdict_row.get("source") or "").split(":")[0],
                              "no lane info for this source"),
            "prior_decisions": [{"status": r["status"], "at": _t(r),
                                 "note": (r.get("note") or "")[:160]} for r in decided_prior],
            "re_report_n": len(prior),
            "siblings": _siblings(slug, verdict_row, T, by_slug),
            "tickets_referenced": sorted(tickets),
            "lexical_flags": flags,
            "first_seen": first_seen, "age_days_at_decision": age_days}


def render(state):
    """Judge-ready text block."""
    lines = ["STATE (assembled from queue history, as known when this was decided):"]
    lines.append(f"- source: {state['source']} — {state['lane']}")
    if state["prior_decisions"]:
        for p in state["prior_decisions"]:
            note = f" — {p['note']}" if p["note"] else ""
            lines.append(f"- PRIOR DECISION on this exact finding: {p['status']} "
                         f"at {p['at']}{note}")
    else:
        lines.append("- no prior decisions on this finding (first time decided)")
    if state["re_report_n"]:
        lines.append(f"- this is RE-REPORT #{state['re_report_n'] + 1} of the same finding "
                     f"(first seen {state['first_seen'][:10]})")
    if state["siblings"]:
        for s in state["siblings"]:
            lines.append(f"- SIBLING finding '{s['slug']}' shares {', '.join(s['shared'])} "
                         f"and was already: {'; '.join(s['statuses'])}")
    if state["tickets_referenced"]:
        lines.append(f"- ticket(s) already covering this work: "
                     f"{', '.join(state['tickets_referenced'])}")
    if state["lexical_flags"]:
        lines.append(f"- finding text contains: {', '.join(state['lexical_flags'])}")
    if state["age_days_at_decision"] is not None:
        lines.append(f"- age at decision: {state['age_days_at_decision']} days")
    return "\n".join(lines)


def factors(state, source=""):
    """Deterministic verdict factors from assembled state — the rules layer of
    the cascade (2026-10-23 jev-replica, lever 1). The model never sees these:
    they settle what is settleable, leaving only 'valuable?' as judgment.

    fresh   — no prior decision on this finding, no done/superseded phrasing
    covered — a sibling was built/accepted/filed, or a ticket already covers it
              (jira-autotriage excluded: there the ticket IS the finding)
    mine    — the next action is Josh's lane, not an automated/escalation lane
    """
    src = (source or state.get("source") or "").split(":")[0]
    flags = set(state.get("lexical_flags", []))

    fresh = (not state["prior_decisions"]
             and not (flags & {"already-done", "superseded", "covered-elsewhere"}))

    sibling_cover = any(
        any(s.split("@")[0] in ("built", "accepted", "filed") for s in sib["statuses"])
        for sib in state["siblings"])
    ticket_cover = bool(state["tickets_referenced"]) and src != "jira-autotriage"
    covered = sibling_cover or ticket_cover or "covered-elsewhere" in flags

    if src in ("workato-health", "ops-visibility"):
        mine = False
    elif src == "mission-control" and ("escalation" in str(state.get("slug", ""))
                                       or state.get("kind") != "decision"):
        mine = False  # mc- escalation re-raises: already triaged once
    else:
        mine = True

    return {"fresh": fresh, "covered": covered, "mine": mine,
            "candidate": fresh and not covered and mine,
            "rationale": {"sibling_cover": sibling_cover,
                          "ticket_cover": ticket_cover, "src": src}}


def render_compact(state):
    """One- to eight-line card rendering for `triage-decide.py list`."""
    lines = [f"STATE: {state['source'].split(':')[0]} — {state['lane']}"]
    for p in state["prior_decisions"]:
        note = f" — {p['note']}" if p["note"] else ""
        lines.append(f"  PRIOR: {p['status']} at {p['at'][:10]}{note}")
    if state["re_report_n"]:
        lines.append(f"  RE-REPORT #{state['re_report_n'] + 1} "
                     f"(first seen {state['first_seen'][:10]})")
    if state["siblings"]:
        counts = defaultdict(int)
        for s in state["siblings"]:
            for st in s["statuses"]:
                counts[st.split("@")[0]] += 1
        tally = ", ".join(f"{k}×{v}" for k, v in sorted(counts.items()))
        examples = ", ".join(s["slug"] for s in state["siblings"][:2])
        lines.append(f"  SIBLINGS: {len(state['siblings'])} finding(s) on shared "
                     f"recipe/ticket ids already decided: {tally} (e.g. {examples})")
    if state["tickets_referenced"]:
        lines.append(f"  TICKETS: {', '.join(state['tickets_referenced'])}")
    if state["lexical_flags"]:
        lines.append(f"  FLAGS: {', '.join(state['lexical_flags'])}")
    return "\n".join(lines)


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    rows = [json.loads(l) for l in
            Path.home().joinpath(".claude/knowledge/triage/queue.jsonl")
            .read_text().splitlines() if l.strip()]
    idx = build_index(rows)
    slug = sys.argv[1] if len(sys.argv) > 1 else "recipe-health-82090477-new-failures"
    verdict = idx[slug][-1]
    print(render(state_block(slug, verdict, idx)))
