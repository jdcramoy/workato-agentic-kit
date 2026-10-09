#!/usr/bin/env python3
"""proposal-pipeline.py — the dreamer's proposal queue, as data.

Scans knowledge/dreams/proposals/*.md frontmatter, cross-refs
garden-reports/proposal-outcomes.jsonl, and prints a digest the gardener,
morning brief, and dashboard consume. Read-only.

Usage:
  proposal-pipeline.py            human digest
  proposal-pipeline.py --json     machine digest (for brief/dashboard)

Pipeline: proposed -> accepted|rejected (Josh call, logged as outcome)
        -> built (work done, outcome logged with evidence ref).
"""
import json, os, re, glob, datetime as dt

HOME = os.path.expanduser("~")
K = os.path.join(HOME, ".claude", "knowledge")
PROPOSALS = os.path.join(K, "dreams", "proposals")
OUTCOMES = os.path.join(K, "garden-reports", "proposal-outcomes.jsonl")
DREAMS = os.path.join(K, "dreams")


def parse_frontmatter(path):
    try:
        head = open(path, errors="replace").read(2000)
    except OSError:
        return None
    m = re.match(r"^---\s*\n(.*?)\n---", head, re.DOTALL)
    if not m:
        return None
    fm = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip().lower()] = v.strip()
    return fm


def load_outcomes():
    rows = []
    try:
        with open(OUTCOMES, errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
    except OSError:
        pass
    return rows


def latest_dream_inventions():
    """Count numbered inventions in the newest dream report (file-gate check)."""
    dreams = sorted(glob.glob(os.path.join(DREAMS, "2*.md")))
    if not dreams:
        return "none", 0, None
    f = dreams[-1]
    try:
        body = open(f, errors="replace").read()
    except OSError:
        return os.path.basename(f), 0, None
    m = re.search(r"^## Inventions.*?$(.*?)(?=^## |\Z)", body, re.MULTILINE | re.DOTALL)
    if not m:
        return os.path.basename(f), 0, None
    n = len(re.findall(r"^\d+\.\s+\*\*", m.group(1), re.MULTILINE))
    return os.path.basename(f), n, f


def collect():
    outcomes = load_outcomes()
    outcome_by_proposal = {}
    for o in outcomes:
        key = (o.get("proposal") or "").lower()
        outcome_by_proposal[key] = o
    items = []
    for p in sorted(glob.glob(os.path.join(PROPOSALS, "*.md"))):
        fm = parse_frontmatter(p) or {}
        title = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", os.path.basename(p)[:-3]).replace("-", " ")
        status = (fm.get("status") or "proposed").lower()
        # outcome log wins if it has a newer ruling for this proposal
        oc = outcome_by_proposal.get(title.lower())
        if oc and oc.get("action", "").lower() in ("accepted", "rejected", "built"):
            if status == "proposed":  # file not updated; log is authoritative
                status = oc["action"].lower()
        items.append({
            "file": os.path.basename(p),
            "title": title,
            "status": status,
            "kind": fm.get("kind", "?"),
            "risk": fm.get("risk", "?"),
            "date": fm.get("created", os.path.basename(p)[:10]),
        })
    # file-gate: inventions in latest dream vs filed invention proposals that day
    dream_name, n_inv, _ = latest_dream_inventions()
    return items, dream_name, n_inv, len(outcomes)


def digest():
    items, dream_name, n_inv, n_outcomes = collect()
    proposed = [i for i in items if i["status"] == "proposed"]
    incubating = [i for i in items if i["status"] == "incubating"]
    accepted = [i for i in items if i["status"] == "accepted"]
    built = [i for i in items if i["status"] == "built"]
    rejected = [i for i in items if i["status"] == "rejected"]
    today = dt.date.today()
    lines = []
    gate = ""
    # file-gate: inventions in latest dream vs filed invention proposals that day.
    # A dream report can legitimately have no "## Inventions" section — the dreamer
    # files inventions straight into the proposals queue — so an empty section is
    # only a miss when nothing was filed on the dream's date either.
    if dream_name == "none":
        gate = "file-gate: no dream report yet"
    elif n_inv:
        gate = f"file-gate: latest dream ({dream_name}) has {n_inv} inventions"
    else:
        filed = [i for i in items if i["date"] == dream_name[:10]]
        if filed:
            gate = (f"file-gate: latest dream ({dream_name}) has no Inventions section; "
                    f"{len(filed)} proposal(s) filed on that date")
        else:
            gate = (f"file-gate: latest dream ({dream_name}) has no Inventions section "
                    f"and no proposals filed that day")
    lines.append(f"PROPOSAL PIPELINE — {len(items)} filed · {len(proposed)} proposed · "
                 f"{len(incubating)} incubating · {len(accepted)} accepted-not-built · "
                 f"{len(built)} built · {len(rejected)} rejected")
    for i in incubating:
        lines.append(f"  INCUBATING (not yet for Josh): {i['title']} (from {i['date']})")
    lines.append(gate)
    for i in accepted:
        lines.append(f"  NEEDS BUILDER: {i['title']} ({i['kind']}, risk {i['risk']}, from {i['date']})")
    for i in proposed:
        age = (today - dt.date.fromisoformat(i["date"])).days if re.match(r"\d{4}-\d{2}-\d{2}", i["date"]) else "?"
        flag = "  <-- NEEDS DECISION (Josh)" if age == "?" or age >= 1 else ""
        lines.append(f"  NEEDS DECISION: {i['title']} ({i['kind']}, risk {i['risk']}, age {age}d){flag}")
    if not proposed and not accepted:
        lines.append("  queue clear")
    return lines, items, {"proposed": len(proposed), "accepted": len(accepted),
                          "built": len(built), "rejected": len(rejected),
                          "dream_inventions": n_inv, "dream_file": dream_name}


def main():
    import sys
    lines, items, counts = digest()
    if "--json" in sys.argv:
        print(json.dumps({"counts": counts, "items": items}, indent=1))
    else:
        print("\n".join(lines))


if __name__ == "__main__":
    main()
