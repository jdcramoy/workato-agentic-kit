"""Token-based Confluence sync (nightly job path).

Reads the API token from the macOS keychain:
    security find-generic-password -s atlassian-confluence -a josh.cramoy@workato.com -w
v1 content/search is broken on this tenant (CQL arrives empty server-side),
so sync = full v2 pagination with storage-format bodies -> markdown, sha-compare.
~15 requests per space per night at limit=250; change detection keeps it cheap.

Usage: python3 -m kb.confluence_sync [--space extbt] [--space intbt]
Spaces: extbt (BTI, id 105054224), intbt (BTKB, id 34734917).
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path

from .common import UA, load_manifest, save_manifest, sha256_text
from .confluence_ingest import slugify
from .wp_source import html_to_markdown

SPACES = {"extbt": "105054224", "intbt": "34734917"}
BASE = "https://workato.atlassian.net/wiki"
KEYCHAIN_SERVICE = "atlassian-confluence"
KEYCHAIN_ACCOUNT = "josh.cramoy@workato.com"


def _auth() -> str:
    out = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        raise SystemExit(
            "Confluence API token not in keychain. Create one at "
            "https://id.atlassian.com/manage-profile/security/api-tokens and run:\n"
            f'  security add-generic-password -s {KEYCHAIN_SERVICE} -a {KEYCHAIN_ACCOUNT} -w <TOKEN>'
        )
    email = KEYCHAIN_ACCOUNT
    token = out.stdout.strip()
    return base64.b64encode(f"{email}:{token}".encode()).decode()


def _get(url: str, auth: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Authorization": f"Basic {auth}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.load(resp)


def sync_space(space_alias: str) -> dict:
    auth = _auth()
    space_id = SPACES[space_alias]
    manifest = load_manifest(f"confluence-{space_alias}")
    out_dir = Path.home() / ".claude/workato-kb/corpus/confluence" / space_alias
    out_dir.mkdir(parents=True, exist_ok=True)

    changed, unchanged, errors = 0, 0, []
    cursor = None
    seen_ids = set()
    while True:
        params = {"limit": "250", "body-format": "storage"}
        if cursor:
            params["cursor"] = cursor
        url = f"{BASE}/api/v2/spaces/{space_id}/pages?" + urllib.parse.urlencode(params)
        data = _get(url, auth)
        for page in data.get("results", []):
            pid = page["id"]
            seen_ids.add(pid)
            title = page.get("title", "")
            storage = page.get("body", {}).get("storage", "")
            if isinstance(storage, dict):
                storage = storage.get("value", "") or ""
            body = html_to_markdown(storage)
            digest = sha256_text(body)
            page_url = f"{BASE}/spaces/{space_alias}/pages/{pid}"
            rec = manifest.get(page_url, {})  # manifests are keyed by URL
            if rec.get("sha256") == digest:
                unchanged += 1
                continue
            fname = f"{pid}-{slugify(title)}.md"
            (out_dir / fname).write_text(
                "---\n"
                f'url: "{page_url}"\n'
                f'title: "{title.replace(chr(34), chr(39))}"\n'
                f'confluence_id: "{pid}"\n'
                f'space: "{space_alias}"\n'
                f'version: "{page.get("version", {}).get("number", "")}"\n'
                f'status: "{page.get("status", "")}"\n'
                "---\n\n" + body
            )
            rec.update(
                {
                    "url": page_url,
                    "path": f"confluence/{space_alias}/{fname}",
                    "sha256": digest,
                    "title": title,
                    "confluence_id": pid,
                    "version": page.get("version", {}).get("number", ""),
                }
            )
            manifest[page_url] = rec
            changed += 1
        next_link = (data.get("_links") or {}).get("next")
        if not next_link:
            break
        cursor = urllib.parse.parse_qs(urllib.parse.urlparse(next_link).query).get("cursor", [None])[0]
        if not cursor:
            break

    save_manifest(f"confluence-{space_alias}", manifest)
    return {
        "space": space_alias,
        "changed": changed,
        "unchanged": unchanged,
        "total_known": len(manifest),
        "seen": len(seen_ids),
        "errors": errors,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", choices=list(SPACES), action="append")
    a = ap.parse_args()
    spaces = a.space or list(SPACES)
    results = [sync_space(s) for s in spaces]
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
