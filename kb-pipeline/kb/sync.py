"""Nightly orchestrator: sync all sources -> re-index changed docs -> diff report.

    python3 -m kb.sync                 # everything
    python3 -m kb.sync --no-embed      # crawl+chunk only
Writes a diff report to ~/.claude/workato-kb/diffs/YYYY-MM-DD.json and (best effort)
appends a one-line summary to the gossip bus outbox knowledge/dreams/bus/workato-kb.jsonl.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from .common import DATA_ROOT, fetch_cached


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--no-embed", action="store_true")
    ap.add_argument("--sources", nargs="*", default=None)
    a = ap.parse_args()
    wanted = a.sources

    results: dict = {}
    errors: list[str] = []

    def try_step(name: str, fn, *args, **kwargs):
        if wanted and name not in wanted:
            return
        print(f"[sync] {name} ...", flush=True)
        try:
            results[name] = fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - nightly job records, never dies silently
            errors.append(f"{name}: {e}")
            results[name] = {"error": str(e)}

    from . import docs_source, eip_source, github_source, llms_source, wp_source
    from .indexer import build

    try_step("docs", docs_source.sync)
    try_step("blog", wp_source.sync_blog)
    try_step("changelog", wp_source.changelog_incremental)
    try_step("inspiration", wp_source.sync_inspiration)
    try_step("github", github_source.sync)
    try_step("eip", eip_source.sync)
    try_step("claude", llms_source.sync, "claude")
    try_step("confluence", _confluence_best_effort)
    try_step("index", build, with_embeddings=not a.no_embed)

    today = dt.date.today().isoformat()
    report = {"date": today, "results": results, "errors": errors}
    diff_dir = DATA_ROOT / "diffs"
    diff_dir.mkdir(parents=True, exist_ok=True)
    (diff_dir / f"{today}.json").write_text(json.dumps(report, indent=2))

    # gossip bus (best effort)
    try:
        bus = Path.home() / ".claude/knowledge/dreams/bus"
        bus.mkdir(parents=True, exist_ok=True)
        changed_total = sum(
            r.get("changed", 0) for r in results.values() if isinstance(r, dict)
        )
        with (bus / "workato-kb.jsonl").open("a") as f:
            f.write(
                json.dumps(
                    {
                        "ts": dt.datetime.now().isoformat(),
                        "agent": "workato-kb",
                        "type": "sync_report",
                        "summary": f"KB sync {today}: {changed_total} docs changed across {len(results)} sources; errors: {len(errors)}",
                        "details": {"changed": changed_total, "errors": errors},
                    }
                )
                + "\n"
            )
    except Exception:  # noqa: BLE001
        pass

    print(json.dumps(report, indent=2))


def _confluence_best_effort():
    from . import confluence_sync

    out = {}
    for space in ("extbt", "intbt"):
        try:
            out[space] = confluence_sync.sync_space(space, days=2)
        except SystemExit as e:
            out[space] = {"skipped": str(e).strip().splitlines()[0]}
    return out


if __name__ == "__main__":
    main()
