"""Harness source: ingest Josh's own knowledge tree + skills into the corpus.

Adds a `harness` source alongside docs/blog/eip/... so /kb queries fuse the
curated internal knowledge (domains, projects, claims, deployed skills) with
official docs. Every ingested note gets a stable `harness://` URI, a chunked
entry in the index like any other source, and `source: harness` attribution in
search results.

Scope (deliberately narrow — curated, high-value trees only):
  ~/.claude/knowledge/domains/**/*.md
  ~/.claude/knowledge/projects/**/*.md
  ~/.claude/knowledge/claims/**/*.md
  ~/.claude/skills/*/SKILL.md            (as harness/skills/<skill-name>.md)

NEVER ingested: knowledge/people (LOCAL-ONLY by design), dreams, bus, garden
reports, evals, fixtures, anything queue/log-shaped.

    python3 -m kb.harness_source            # rebuild corpus/harness + manifest
Wired into kb.sync as a source step ("harness") — NOT in CORE_SOURCES yet
(a harness failure must not fail the nightly source-count floor).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .common import DATA_ROOT, save_manifest, sha256_text

KNOWLEDGE = Path.home() / ".claude/knowledge"
SKILLS = Path.home() / ".claude/skills"

OUT_DIR = DATA_ROOT / "corpus" / "harness"
MANIFEST_NAME = "harness"

_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
_H1 = re.compile(r"^#\s+(.+)$", re.M)

# top-level knowledge subdirs that are curated notes worth indexing
_INCLUDE_SUBDIRS = ("domains", "projects", "claims")


def _title_of(text: str, fallback: str) -> str:
    m = _H1.search(_FRONTMATTER.sub("", text))
    return m.group(1).strip() if m else fallback


def _targets() -> list[tuple[str, Path]]:
    """(relative corpus path, source file) for every ingested note."""
    out: list[tuple[str, Path]] = []
    for sub in _INCLUDE_SUBDIRS:
        base = KNOWLEDGE / sub
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*.md")):
            if "/people/" in str(p):
                continue
            out.append((f"harness/knowledge/{p.relative_to(KNOWLEDGE).as_posix()}", p))
    for p in sorted(SKILLS.glob("*/SKILL.md")):
        out.append((f"harness/skills/{p.parent.name}.md", p))
    return out


def sync() -> dict:
    """Mirror curated notes into corpus/harness/ with frontmatter; write manifest."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    records: dict[str, dict] = {}
    written = removed = 0

    for rel, src in _targets():
        raw = src.read_text()
        body = _FRONTMATTER.sub("", raw).strip()
        title = _title_of(raw, Path(rel).stem.replace("-", " "))
        url = f"harness://{rel.removeprefix('harness/')}"

        dst = OUT_DIR / Path(rel).relative_to("harness")
        dst.parent.mkdir(parents=True, exist_ok=True)
        front = (
            "---\n"
            f'url: "{url}"\n'
            f'title: "{title.replace(chr(34), chr(39))}"\n'
            'source: "harness"\n'
            f'origin: "{src}"\n'
            "---\n"
        )
        dst.write_text(front + body + "\n")
        records[url] = {
            "url": url,
            "path": rel,
            "title": title,
            "sha256": sha256_text(front + body + "\n"),
        }
        written += 1

    # purge notes that left the trees
    live_paths = {r["path"] for r in records.values()}
    for p in OUT_DIR.rglob("*.md"):
        if f"harness/{p.relative_to(OUT_DIR).as_posix()}" not in live_paths:
            p.unlink()
            removed += 1

    save_manifest(MANIFEST_NAME, records)
    return {"written": written, "removed": removed, "manifest": MANIFEST_NAME}


if __name__ == "__main__":
    print(json.dumps(sync(), indent=2))
