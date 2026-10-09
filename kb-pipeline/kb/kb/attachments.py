"""Confluence attachments (roadmap item): PDF/docx/xlsx/pptx/txt text extraction.

Scans every page in the confluence manifests via v2 attachments API, downloads
text-bearing attachments (<= 25MB), extracts to markdown, stores under
corpus/confluence/<space>/attachments/, manifest confluence-attachments.
Incremental: attachment sha256 (of extracted text) change-detects.

    python3 -m kb.attachments [--max-pages 0]   # 0 = all pages
"""

from __future__ import annotations

import argparse
import io
import json
import subprocess
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from .common import MAX_WORKERS, UA, corpus_dir, load_manifest, save_manifest, sha256_text
from .confluence_sync import BASE, _auth
from .confluence_ingest import slugify

TEXT_TYPES = (".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".csv", ".md")
MAX_BYTES = 25_000_000

DL_URL = BASE + "/wiki/rest/api/attachment/content/"  # ?path= style alt handled below


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n\n".join((page.extract_text() or "") for page in reader.pages)


def _extract_zipxml(data: bytes, wanted: set[str]) -> str:
    """Shared extractor for docx/xlsx/pptx (zip of XML)."""
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name in z.namelist():
            if name not in wanted:
                continue
            try:
                root = ET.fromstring(z.read(name))
            except ET.ParseError:
                continue
            for elem in root.iter():
                if elem.text and elem.text.strip():
                    out.append(elem.text.strip())
    return "\n".join(out)


def _extract(data: bytes, suffix: str) -> str:
    if suffix == ".pdf":
        return _extract_pdf(data)
    if suffix == ".docx":
        return _extract_zipxml(data, {"word/document.xml"})
    if suffix == ".xlsx":
        return _extract_zipxml(data, {"xl/sharedStrings.xml"})
    if suffix == ".pptx":
        return _extract_zipxml(data, {n for n in ("ppt/slides/slide1.xml",)})  # per-slide handled below
    return data.decode("utf-8", "replace")


def _extract_pptx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        slides = sorted(n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
        return _extract_zipxml(data, set(slides))


def _download(url: str, auth: str) -> bytes:
    import time

    last = None
    for attempt in range(3):  # transient DNS flakes on this host; retry
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Authorization": f"Basic {auth}"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except urllib.error.HTTPError:
            raise
        except Exception as e:  # noqa: BLE001 - DNS/connection flakes
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def _page_attachments(page_id: str, auth: str) -> list[dict]:
    import time

    url = f"{BASE}/api/v2/pages/{page_id}/attachments?limit=100"
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Authorization": f"Basic {auth}"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp).get("results", [])
        except urllib.error.HTTPError:
            return []
        except Exception as e:  # noqa: BLE001 - DNS/connection flakes
            last = e
            time.sleep(1.5 * (attempt + 1))
    return [{"error": str(last)}]


def sync(max_pages: int = 0, max_workers: int = MAX_WORKERS) -> dict:
    import concurrent.futures as cf

    auth = _auth()
    manifest = load_manifest("confluence-attachments")
    pages_by_space: dict[str, dict] = {}
    for space in ("extbt", "intbt"):
        pages_by_space[space] = load_manifest(f"confluence-{space}")

    jobs = []
    for space, pages in pages_by_space.items():
        for pid, rec in list(pages.items()):
            if max_pages and len(jobs) >= max_pages:
                break
            jobs.append((space, pid, rec["title"]))

    out_dir = corpus_dir("confluence/attachments")
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = {"pages_scanned": 0, "attachments_seen": 0, "extracted": 0, "skipped_type": 0, "too_big": 0, "empty": 0, "errors": []}
    lock_free_stats = stats

    def work(job):
        space, pid, title = job
        atts = _page_attachments(pid, auth)
        results = []
        for att in atts:
            if "error" in att:
                stats["errors"].append({"page": pid, "error": att["error"]})
                continue
            stats["attachments_seen"] += 1
            fname = att.get("title", "")
            suffix = "." + fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
            if suffix not in TEXT_TYPES:
                stats["skipped_type"] += 1
                continue
            att_id = att["id"]
            key = f"att-{att_id}"
            dl = f"{BASE}/wiki/rest/api/attachment/content/{att_id}"
            try:
                data = _download(dl, auth)
            except Exception as e:  # noqa: BLE001
                stats["errors"].append({"att": att_id, "error": str(e)})
                continue
            if len(data) > MAX_BYTES:
                stats["too_big"] += 1
                continue
            try:
                text = _extract_pptx(data) if suffix == ".pptx" else _extract(data, suffix)
            except Exception as e:  # noqa: BLE001
                stats["errors"].append({"att": att_id, "error": f"extract: {e}"})
                continue
            text = text.strip()
            if len(text) < 80:
                stats["empty"] += 1
                continue
            digest = sha256_text(text)
            rec = manifest.get(key, {})
            if rec.get("sha256") == digest:
                continue
            slug = slugify(fname.rsplit(".", 1)[0])
            out = out_dir / f"{att_id}-{slug}.md"
            page_url = f"{BASE}/spaces/{space}/pages/{pid}"
            out.write_text(
                "---\n"
                f'url: "{page_url}"\n'
                f'title: "{fname.replace(chr(34), chr(39))}"\n'
                f'attachment_id: "{att_id}"\n'
                f'space: "{space}"\n'
                f'parent_page: "{title.replace(chr(34), chr(39))}"\n'
                'source: "confluence-attachments"\n'
                "---\n\n" + text
            )
            rec.update(
                {
                    "url": page_url,
                    "path": f"confluence/attachments/{out.name}",
                    "sha256": digest,
                    "title": fname,
                    "attachment_id": att_id,
                    "parent_page": title,
                }
            )
            manifest[key] = rec
            stats["extracted"] += 1
        return

    with cf.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(work, j) for j in jobs]
        for i, fut in enumerate(cf.as_completed(futs), 1):
            fut.result()
            stats["pages_scanned"] += 1
            if i % 250 == 0:
                print(f"  ... {i}/{len(jobs)} pages scanned", flush=True)

    save_manifest("confluence-attachments", manifest)
    stats["total_attachments_known"] = len(manifest)
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=0)
    a = ap.parse_args()
    print(json.dumps(sync(max_pages=a.max_pages), indent=2))
