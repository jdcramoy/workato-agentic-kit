"""Cross-pool bridges: auto-append "Related" sections linking curated notes into the KB corpus.

For every target note (knowledge domains/projects + deployed skills), retrieve the
note's nearest corpus neighbors via the existing hybrid search stack (BM25+vec+
rerank, kb.search) and append an idempotent, marker-delimited section of real
relative links. Only links that resolve inside the corpus are emitted, so Obsidian
draws every one as a graph edge and none can create click-stubs.

    python3 -m kb.bridges --dry-run            # report, no writes
    python3 -m kb.bridges                      # write knowledge/ + skills/
    python3 -m kb.bridges --roots knowledge    # scope to one root

Idempotent: re-runs replace the content between the markers, never accrete.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from .common import DATA_ROOT, load_manifest
from .search import search

# user-curated roots, in the brain-vault layout:
#   brain-vault/knowledge/<rest>  (symlink -> ~/.claude/knowledge)
#   brain-vault/skills/<name>/SKILL.md  (symlink -> ~/.claude/skills)
KNOWLEDGE = Path.home() / ".claude/knowledge"
SKILLS = Path.home() / ".claude/skills"

CORPUS_DIR = "kb-corpus"  # vault-side name of the corpus symlink

BRIDGE_HEADING = "## Related (KB bridges)"
BEGIN = "<!-- kb-bridges:v1 begin -->"
END = "<!-- kb-bridges:end -->"

_MIN_RERANK = 0.0  # bge-reranker logit bar; below this the hit is noise
_TOP_N = 4

_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)
_BRIDGE_BLOCK = re.compile(
    rf"\n*{re.escape(BRIDGE_HEADING)}\n.*?{re.escape(END)}\n?", re.S
)


def _url_path_map() -> dict[str, str]:
    """manifest url -> corpus relative path, across every manifest."""
    out: dict[str, str] = {}
    for mf in sorted((DATA_ROOT / "manifest").glob("*.jsonl")):
        for url, rec in load_manifest(mf.stem).items():
            rel = rec.get("path", "")
            if rel:
                out[url] = rel
    return out


def _body_for_query(text: str) -> str:
    text = _FRONTMATTER.sub("", text)
    text = _BRIDGE_BLOCK.sub("", text)
    return text.strip()


def _depth_prefix(target: Path, root: Path) -> str:
    """Number of ../ needed from the note's vault location up to the VAULT root.

    The vault root (brain-vault) contains the root itself as a directory, e.g.
    vault/knowledge/domains/x.md -> 2 levels up; vault/skills/<n>/SKILL.md -> 2.
    """
    depth = len(target.parent.relative_to(root).parts) + 1
    return "../" * depth


def _render_section(links: list[tuple[str, str]]) -> str:
    lines = [BRIDGE_HEADING, "", BEGIN]
    for title, href in links:
        lines.append(f"- [{title}]({href})")
    lines.append(END)
    return "\n".join(lines) + "\n"


def bridge_note(path: Path, root: Path, url_map: dict[str, str]) -> dict:
    text = path.read_text()
    body = _body_for_query(text)
    if len(body) < 200:
        return {"file": str(path), "skipped": "too short", "n_links": 0}

    query = body[:1500]
    hits, _meta = search(query, k=8, rerank=True)

    seen_urls: set[str] = set()
    links: list[tuple[str, str]] = []
    for h in hits:
        if (h.rerank or -99) < _MIN_RERANK or h.url in seen_urls:
            continue
        rel = url_map.get(h.url)
        if not rel:
            continue
        seen_urls.add(h.url)
        href = f"{_depth_prefix(path, root)}{CORPUS_DIR}/{rel}"
        title = h.title or rel.rsplit("/", 1)[-1]
        links.append((title, href))
        if len(links) >= _TOP_N:
            break

    if not links:
        return {"file": str(path), "skipped": "no qualifying hits", "n_links": 0}

    section = _render_section(links)
    if BEGIN in text:
        new_text = _BRIDGE_BLOCK.sub("\n" + section, text)
    else:
        new_text = text.rstrip("\n") + "\n\n" + section

    return {
        "file": str(path),
        "n_links": len(links),
        "new_text": new_text,
        "old_text": text,
    }


def normalize_depth(results: list[dict], dry_run: bool) -> dict:
    touched = 0
    for r in results:
        if "new_text" in r and not dry_run:
            Path(r["file"]).write_text(r["new_text"])
        if "new_text" in r:
            touched += 1
        r.pop("new_text", None)
        r.pop("old_text", None)
    return touched


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--roots", nargs="*", default=["knowledge", "skills"])
    a = ap.parse_args()

    url_map = _url_path_map()
    targets: list[tuple[Path, Path]] = []

    if "knowledge" in a.roots:
        for sub in ("domains", "projects"):
            base = KNOWLEDGE / sub
            if base.is_dir():
                targets += [(p, KNOWLEDGE) for p in sorted(base.rglob("*.md"))]
    if "skills" in a.roots:
        targets += [
            (p, SKILLS)
            for p in sorted(SKILLS.glob("*/SKILL.md"))
        ]

    results = []
    for path, root in targets:
        if "/people/" in str(path):
            continue  # LOCAL-ONLY people files are never touched
        try:
            results.append(bridge_note(path, root, url_map))
        except Exception as e:  # noqa: BLE001 - one bad note never kills the pass
            results.append({"file": str(path), "skipped": f"error: {e}", "n_links": 0})

    touched = normalize_depth(results, a.dry_run)
    bridged = [r for r in results if r["n_links"]]
    skipped = [r for r in results if r.get("skipped")]
    print(
        json.dumps(
            {
                "dry_run": a.dry_run,
                "targets": len(results),
                "bridged": len(bridged),
                "touched_files": touched,
                "skipped": len(skipped),
                "links_total": sum(r["n_links"] for r in bridged),
                "sample": bridged[:3],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
