"""Ingest a saved MCP getPagesInConfluenceSpace tool-result file into the corpus.

Usage: python3 -m kb.confluence_ingest <tool-result-file.json> <space-key> [extbt|intbt]
Handles one batch (250 pages). Page id -> corpus/confluence/<space>/<id>.md + manifest.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .common import corpus_dir, load_manifest, save_manifest, sha256_text


def slugify(title: str) -> str:
    s = re.sub(r"[^\w\s-]", "", title.lower())
    s = re.sub(r"[\s_]+", "-", s).strip("-")
    return s[:80] or "untitled"


def ingest(result_file: str, space: str) -> dict:
    raw = Path(result_file).read_text()
    data = json.loads(raw[raw.find("{") :])
    manifest = load_manifest(f"confluence-{space}")
    out_dir = corpus_dir(f"confluence/{space}")
    out_dir.mkdir(parents=True, exist_ok=True)
    changed = 0
    seen = set()
    for page in data.get("results", []):
        pid = page["id"]
        seen.add(pid)
        title = page.get("title", "")
        body = page.get("body") or ""
        if isinstance(body, dict):
            body = body.get("value", "")
        digest = sha256_text(body)
        page_url = f"https://workato.atlassian.net/wiki/spaces/{space}/pages/{pid}"
        rec = manifest.get(page_url, {})  # manifests are keyed by URL
        if rec.get("sha256") == digest:
            continue
        fname = f"{pid}-{slugify(title)}.md"
        (out_dir / fname).write_text(
            "---\n"
            f'url: "{page_url}"\n'
            f'title: "{title.replace(chr(34), chr(39))}"\n'
            f'confluence_id: "{pid}"\n'
            f'space: "{space}"\n'
            f'version: "{page.get("version", {}).get("number", "")}"\n'
            f'status: "{page.get("status", "")}"\n'
            "---\n\n" + body
        )
        rec.update(
            {
                "url": page_url,
                "path": f"confluence/{space}/{fname}",
                "sha256": digest,
                "title": title,
                "confluence_id": pid,
                "version": page.get("version", {}).get("number", ""),
            }
        )
        manifest[page_url] = rec
        changed += 1
    save_manifest(f"confluence-{space}", manifest)
    return {"space": space, "batch_pages": len(data.get("results", [])), "changed": changed, "total_known": len(manifest), "next": (data.get("_links") or {}).get("next", "")}


if __name__ == "__main__":
    print(json.dumps(ingest(sys.argv[1], sys.argv[2]), indent=2))
