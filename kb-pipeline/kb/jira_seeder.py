"""jira_seeder.py — seed the case base from Josh's closed Jira tickets.

Extraction heuristics (v0, no LLM):
  presentation = summary + description excerpt (the symptom as filed)
  diagnosis    = the last substantive comment mentioning cause words, or the
                 last comment before closure
  treatment    = the resolution-bearing comment (fix/workaround keywords) or
                 the same comment as diagnosis when both live in one
  skipped      = tickets with no comments and thin descriptions (no signal)

  kb jira_seeder seed            # all stashed tickets -> cases
  kb jira_seeder preview -n 3    # inspect extraction quality
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

CORPUS = Path.home() / ".claude/workato-kb/corpus/jira"

CAUSE_WORDS = re.compile(r"(cause|root|because|due to|reason|actually|turns out|was (a|an) )", re.I)
FIX_WORDS = re.compile(r"(fix|fixed|resolution|workaround|solution|updated|changed|recreate|corrected|switched|enabled|disabled)", re.I)
NOISE = re.compile(r"^(thanks|thank you|ok|okay|got it|ack|perfect|great|noted|hi|hello)", re.I)


def _adf_to_text(node) -> str:
    """Atlassian Document Format -> plain text (REST returns ADF; the MCP normalized)."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(_adf_to_text(n) for n in node)
    if isinstance(node, dict):
        parts = []
        if node.get("text"):
            parts.append(node["text"])
        for child in node.get("content", []) or []:
            parts.append(_adf_to_text(child))
        out = " ".join(p for p in parts if p)
        if node.get("type") in ("paragraph", "listItem"):
            out += "\n"
        return out
    return ""


def _substantive_comments(comments: list[dict]) -> list[str]:
    out = []
    for c in comments:
        body = _adf_to_text(c.get("body") or "").strip()
        # strip Jira markup noise
        body = re.sub(r"[!{^}]", "", body)
        if len(body) < 25 or NOISE.match(body):
            continue
        out.append(body)
    return out


def extract(ticket: dict) -> dict | None:
    fields = ticket.get("fields", {})
    key = ticket.get("key", "?")
    summary = (fields.get("summary") or "").strip()
    desc = (fields.get("description") or "").strip()
    comments = [c for c in (fields.get("comment") or {}).get("comments", []) if isinstance(c, dict)]
    subs = _substantive_comments(comments)
    if not summary:
        return None
    itype = (fields.get("issuetype") or {}).get("name", "")
    if itype.lower() in ("epic", "initiative", "theme"):
        return None  # organizational container, not a case
    presentation = f"{summary}. {desc[:400]}" if desc else summary
    if not subs and len(desc) < 60:
        return None  # no resolution signal
    # problem-shaped only: the case must describe a failure/symptom, and the
    # resolution thread must actually contain a fix-shaped comment
    problem_shaped = bool(re.search(
        r"(error|fail|issue|problem|not working|broken|incorrect|missing|stuck|timeout|denied|unauthorized|can't|cannot|unable)", 
        presentation, re.I))
    if not problem_shaped and itype.lower() not in ("bug", "ticket"):
        return None  # feature requests/org tickets aren't clinical cases
    cause_c = [c for c in subs if CAUSE_WORDS.search(c)]
    fix_c = [c for c in subs if FIX_WORDS.search(c)]
    if not fix_c and not cause_c:
        return None  # no resolution evidence in the thread — not a case
    diagnosis = (cause_c[-1] if cause_c else (subs[-1] if subs else summary))[:500]
    treatment = (fix_c[-1] if fix_c else (subs[-1] if subs else "see discussion"))[:500]
    return {
        "key": key,
        "presentation": presentation[:600],
        "diagnosis": diagnosis,
        "treatment": treatment,
        "outcome": "worked",
        "tags": f"jira,{fields.get('issuetype', {}).get('name', '')}",
        "source": f"jira/{key}",
        "url": f"https://workato.atlassian.net/browse/{key}",
    }


def seed(dry_run: bool = False) -> dict:
    from .cases import file_case, stats

    tickets = sorted(CORPUS.glob("*.json"))
    filed, skipped = 0, 0
    preview = []
    for tf in tickets:
        try:
            t = json.loads(tf.read_text())
        except json.JSONDecodeError:
            continue
        c = extract(t)
        if not c:
            skipped += 1
            continue
        if dry_run:
            preview.append(c)
            continue
        file_case(
            presentation=f"[{c['key']}] {c['presentation']}",
            diagnosis=c["diagnosis"],
            treatment=c["treatment"],
            outcome="worked",
            tags=c["tags"],
            source=c["source"],
        )
        filed += 1
    s = {"tickets_total": len(tickets), "filed": filed, "skipped_no_signal": skipped}
    if dry_run:
        s["preview"] = preview[:3]
    else:
        s["stats"] = stats()
    return s


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sd = sub.add_parser("seed")
    sd.add_argument("--dry-run", action="store_true")
    pv = sub.add_parser("preview")
    pv.add_argument("-n", type=int, default=3)
    a = ap.parse_args()
    if a.cmd == "seed":
        print(json.dumps(seed(dry_run=a.dry_run), indent=2))
    elif a.cmd == "preview":
        s = seed(dry_run=True)
        print(json.dumps(s["preview"][: a.n], indent=2))
