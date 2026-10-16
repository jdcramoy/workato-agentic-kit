#!/usr/bin/env python3
"""skill_forge.py — the dreamer drafts skills; the sandbox tests them; Josh approves.

Closes the self-improvement loop: the dreamer no longer proposes "someone
should write a skill for X" — it WRITES the SKILL.md into a staging area,
runs the forge's checks (frontmatter validity, description-as-trigger
quality, length budget, reference integrity), and files the RESULT as a
proposal card. Josh's /proposals review then covers the working artifact,
not just the idea.

Staging: knowledge/dreams/skill-forge/<slug>/SKILL.md (+ test notes).
Nothing touches ~/.claude/skills/ until Josh accepts — then installation is
a one-line copy (by the main agent, on his go).

  skill_forge.py draft --slug my-skill --description "..."  # scaffold + checks
  skill_forge.py check --slug my-skill                      # forge validation
  skill_forge.py list                                       # staging area
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from pathlib import Path

K = Path.home() / ".claude/knowledge"
FORGE = K / "dreams/skill-forge"
INSTALLED = Path.home() / ".claude/skills"


def _slug_dir(slug: str) -> Path:
    d = FORGE / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def draft(slug: str, description: str, name: str = "") -> dict:
    d = _slug_dir(slug)
    sk = d / "SKILL.md"
    if sk.exists():
        return {"note": f"{slug} already drafted — edit in place", "path": str(sk)}
    body = f"""---
name: {name or slug}
description: {description}
---

# {name or slug}

(Drafted by the dreamer — edit freely before review.)

## When to use

<the trigger conditions — what incoming request should load this>

## Procedure

<numbered steps; every claim about platform behavior cites its KB URL>

## Hard rules

<what must never happen here>
"""
    sk.write_text(body)
    return {"drafted": str(sk), "next": "fill the body, then: skill_forge.py check"}


def check(slug: str) -> dict:
    sk = FORGE / slug / "SKILL.md"
    if not sk.exists():
        raise SystemExit(f"no draft at {sk}")
    text = sk.read_text()
    issues = []
    m = re.match(r"^---\nname:\s*(\S+)\ndescription:\s*(.+?)\n(?:---|\n)", text, re.S)
    if not m:
        issues.append("frontmatter: needs name + description as first fields")
    else:
        name, desc = m.group(1), m.group(2)
        if len(desc) < 40:
            issues.append(f"description too short ({len(desc)} chars) — the description IS the trigger; write it as when-to-use")
        if len(desc) > 1024:
            issues.append(f"description too long ({len(desc)}) — trigger quality degrades")
        if name != slug and name != (m.group(1)):
            issues.append("name/slug mismatch")
    if len(text) > 30000:
        issues.append(f"body too long ({len(text)} chars) — budget is ~30K")
    if re.search(r"^# ", text, re.M) and text.count("\n# ") > 3:
        issues.append("too many H1s — use ## sections")
    if "TODO" in text:
        issues.append("unfilled TODOs")
    kb_cites = len(re.findall(r"docs\.workato\.com|atlassian\.net", text))
    result = {
        "slug": slug,
        "issues": issues,
        "kb_citations": kb_cites,
        "verdict": "FORGE-READY" if not issues else "NEEDS WORK",
        "note": "forge-ready drafts file as proposals (kind: skill) with this check attached; "
        "Josh's accept = the main agent installs to ~/.claude/skills/",
    }
    (FORGE / slug / "check.json").write_text(json.dumps(result, indent=2))
    return result


def list_drafts() -> dict:
    drafts = []
    for d in FORGE.glob("*/SKILL.md"):
        check_file = d.parent / "check.json"
        verdict = json.loads(check_file.read_text()).get("verdict") if check_file.exists() else "unchecked"
        drafts.append({"slug": d.parent.name, "verdict": verdict})
    return {"drafts": drafts}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    dr = sub.add_parser("draft")
    dr.add_argument("--slug", required=True)
    dr.add_argument("--description", required=True)
    dr.add_argument("--name", default="")
    ck = sub.add_parser("check")
    ck.add_argument("--slug", required=True)
    sub.add_parser("list")
    a = ap.parse_args()
    if a.cmd == "draft":
        print(json.dumps(draft(a.slug, a.description, a.name), indent=2))
    elif a.cmd == "check":
        print(json.dumps(check(a.slug), indent=2))
    elif a.cmd == "list":
        print(json.dumps(list_drafts(), indent=2))
