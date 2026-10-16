#!/usr/bin/env python3
"""skill-park-candidates.py — cross-reference skill usage vs fleet references.

P5 SKILLCULL (estate-fusion-audit-2026-10-13). Produces the evidence-backed
park-candidates list. It NEVER parks anything: skills are constitutionally
never_auto; this is a recommendation for Josh only.

Inputs:
  (a) ~/.claude/knowledge/skills-telemetry/invocations.jsonl  (30d invocations)
  (b) live skill list: ~/.claude/skills
  (c) fleet surfaces (grep for each skill name):
        ~/.claude/knowledge/config/fleet/jobs/   (scheduled job prompts/env)
        ~/.claude/agents/                        (agent definitions)
        ~/.claude/knowledge/dreams/config.json   (dreamer trust ladder)
      plus guard-role surfaces:
        ~/.claude/hooks/*                        (hook-referenced = guard)
        ~/.claude/CLAUDE.md, ~/Documents/CLAUDE.md,
        ~/Documents/workbench/CLAUDE.md          (standing-order-referenced = guard)

Rules:
  0 invocations-30d AND 0 fleet refs AND not guard/infra role  -> PARK candidate
  guard role (explicit list + hook/standing-order referenced)   -> GUARD-ROLE keep
  anything else                                                 -> KEEP
  When unsure: KEEP (conservative bias).

Usage:
  skill-park-candidates.py [--days 30] [--json] [--out <md path>]
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

HOME = os.path.expanduser("~")
LEDGER = os.path.join(HOME, ".claude/knowledge/skills-telemetry/invocations.jsonl")
SKILLS_DIR = os.path.join(HOME, ".claude/skills")
REPORT_DEFAULT = os.path.join(
    HOME, ".claude/knowledge/reports/skill-park-candidates-2026-10-13.md")

# Surfaces where a mention means the skill is wired into the fleet.
FLEET_SURFACES = [
    os.path.join(HOME, ".claude/knowledge/config/fleet/jobs"),
    os.path.join(HOME, ".claude/agents"),
    os.path.join(HOME, ".claude/knowledge/dreams/config.json"),
]
# Surfaces where a mention makes the skill a GUARD role (hook or standing order).
GUARD_SURFACES = [
    os.path.join(HOME, ".claude/hooks"),
    os.path.join(HOME, ".claude/CLAUDE.md"),
    os.path.join(HOME, "Documents/CLAUDE.md"),
    os.path.join(HOME, "Documents/workbench/CLAUDE.md"),
]
# Explicit constitutional guard roles (from the P5 contract).
GUARD_ROLES_EXPLICIT = {
    "verify", "handoff", "run-to-completion", "grill-gate", "fusion", "kb",
    "josh-writing-voice", "red-team-review",
}


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def load_invocations(days):
    """Count invocations per skill in the trailing `days` window."""
    cutoff = now_utc() - dt.timedelta(days=days)
    counts = {}
    if not os.path.exists(LEDGER):
        return counts, 0
    total = 0
    with open(LEDGER) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            total += 1
            ts = rec.get("ts")
            try:
                t = dt.datetime.fromtimestamp(float(ts), dt.timezone.utc)
            except (TypeError, ValueError):
                try:
                    t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    continue
            if t < cutoff:
                continue
            skill = rec.get("skill")
            if skill:
                counts[skill] = counts.get(skill, 0) + 1
    return counts, total


def load_live_skills():
    if not os.path.isdir(SKILLS_DIR):
        return []
    return sorted(
        d for d in os.listdir(SKILLS_DIR)
        if os.path.isdir(os.path.join(SKILLS_DIR, d)))


def read_surface_files():
    """Yield (path, text) for every file under the fleet/guard surfaces."""
    for surface in FLEET_SURFACES + GUARD_SURFACES:
        if os.path.isfile(surface):
            try:
                with open(surface, encoding="utf-8", errors="replace") as f:
                    yield surface, f.read()
            except OSError:
                continue
        elif os.path.isdir(surface):
            for root, _dirs, files in os.walk(surface):
                for name in files:
                    p = os.path.join(root, name)
                    if os.path.islink(p) or name.endswith((".pyc", ".DS_Store")):
                        continue
                    try:
                        with open(p, encoding="utf-8", errors="replace") as f:
                            yield p, f.read()
                    except OSError:
                        continue


def find_references(names):
    """Map skill name -> sorted list of files mentioning it.

    Longer names are matched first and masked so 'triage' doesn't count a
    'jira-autotriage' mention as its own reference (and vice versa).
    """
    ref_map = {n: set() for n in names}
    ordered = sorted(names, key=len, reverse=True)
    # Word-boundary-ish pattern: name bounded by non-name chars.
    patterns = {
        n: re.compile(r"(?<![A-Za-z0-9_])" + re.escape(n) + r"(?![A-Za-z0-9_])")
        for n in names
    }
    for path, text in read_surface_files():
        # Mask progressively longer matches so a hit on a longer name
        # (e.g. 'jira-autotriage') is not re-counted for its substrings.
        work = text
        for n in ordered:
            pat = patterns[n]
            if pat.search(work):
                ref_map[n].add(path)
                work = pat.sub("\x00", work)
    return {n: sorted(v) for n, v in ref_map.items()}


def classify(skills, invocations, refs):
    rows = []
    for skill in skills:
        n30 = invocations.get(skill, 0)
        fleet_refs = [p for p in refs.get(skill, [])
                      if not p.startswith(tuple(GUARD_SURFACES))]
        guard_refs = [p for p in refs.get(skill, [])
                      if p.startswith(tuple(GUARD_SURFACES))]
        is_guard = (skill in GUARD_ROLES_EXPLICIT) or bool(guard_refs)
        if is_guard:
            rec, reason = "GUARD-ROLE", "guard/infra role (never park)"
        elif n30 == 0 and not fleet_refs:
            rec, reason = "PARK", "0 invocations-30d, 0 fleet references"
        else:
            rec, reason = "KEEP", (
                f"{n30} invocations-30d" if n30 else
                "fleet-referenced despite 0 telemetry invocations")
        rows.append({
            "skill": skill,
            "invocations_30d": n30,
            "fleet_refs": fleet_refs,
            "guard_refs": guard_refs,
            "guard": is_guard,
            "recommendation": rec,
            "reason": reason,
        })
    rows.sort(key=lambda r: (r["recommendation"] != "PARK",
                             r["recommendation"] != "KEEP",
                             r["skill"]))
    return rows


def render_md(rows, days, total_ledger):
    parks = [r for r in rows if r["recommendation"] == "PARK"]
    guards = [r for r in rows if r["recommendation"] == "GUARD-ROLE"]
    keeps = [r for r in rows if r["recommendation"] == "KEEP"]
    now = now_utc().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Skill park candidates — 2026-10-13 (P5 SKILLCULL)",
        "",
        f"Generated {now}. Window: {days} days. Ledger rows total: {total_ledger}. "
        f"Live skills: {len(rows)}.",
        "",
        "**Recommendation only — nothing is parked. Skills are constitutionally "
        "never_auto; Josh decides.**",
        "",
        f"Headline: **{len(parks)} PARK candidates** of {len(rows)} live skills; "
        f"**{len(guards)} GUARD-ROLE keeps**; {len(keeps)} ordinary keeps.",
        "",
        "| skill | invocations-30d | referenced-by-fleet | recommendation |",
        "|---|---|---|---|",
    ]
    for r in rows:
        where = ", ".join(os.path.relpath(p, HOME)
                          for p in r["fleet_refs"][:3]) or "no"
        if len(r["fleet_refs"]) > 3:
            where += f" (+{len(r['fleet_refs']) - 3} more)"
        if r["guard_refs"]:
            where += " · GUARD: " + ", ".join(
                os.path.relpath(p, HOME) for p in r["guard_refs"][:2])
        lines.append(
            f"| {r['skill']} | {r['invocations_30d']} | {where} | "
            f"**{r['recommendation']}** |")
    lines += [
        "",
        "## Rules applied",
        "- 0 invocations-30d AND 0 fleet references AND not a guard/infra role "
        "→ PARK candidate.",
        "- Guard roles (verify, handoff, run-to-completion, grill-gate, fusion, "
        "kb, josh-writing-voice, red-team-review, plus any skill referenced by a "
        "hook or standing-order CLAUDE.md) → GUARD-ROLE keep regardless of usage.",
        "- Conservative bias: when unsure, KEEP.",
        "",
        "Caveats: telemetry covers Skill-tool invocations mined from transcripts; "
        "a skill invoked only by subagent transcripts still counts. A PARK "
        "candidate may still be context-tax-only value (loading cost with zero "
        "fires) — parking is Josh's call.",
    ]
    return "\n".join(lines) + "\n", parks, guards, keeps


def main():
    ap = argparse.ArgumentParser(
        prog="skill-park-candidates.py",
        description="Cross-reference skill telemetry vs fleet references; "
                    "recommend park candidates (never parks).")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--json", action="store_true", help="emit JSON to stdout")
    ap.add_argument("--out", default=REPORT_DEFAULT)
    args = ap.parse_args()

    invocations, total_ledger = load_invocations(args.days)
    skills = load_live_skills()
    refs = find_references(skills)
    rows = classify(skills, invocations, refs)

    report, parks, guards, keeps = render_md(rows, args.days, total_ledger)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(report)

    print(f"live_skills={len(rows)} park_candidates={len(parks)} "
          f"guard_keeps={len(guards)} ordinary_keeps={len(keeps)}")
    if parks:
        top = ", ".join(r["skill"] for r in parks[:5])
        print(f"top park candidates: {top}")
    print(f"report written: {args.out}")

    if args.json:
        print(json.dumps({
            "generated": now_utc().isoformat(),
            "window_days": args.days,
            "ledger_rows_total": total_ledger,
            "live_skills": len(rows),
            "park_candidates": len(parks),
            "guard_keeps": len(guards),
            "ordinary_keeps": len(keeps),
            "skills": rows,
        }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
