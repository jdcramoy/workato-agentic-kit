"""Nightly orchestrator: sync all sources -> re-index changed docs -> diff report.

    python3 -m kb.sync                 # everything
    python3 -m kb.sync --no-embed      # crawl+chunk only
    python3 -m kb.sync --sources docs  # scoped run (single step; report marked "scoped")

Writes a diff report to ~/.claude/workato-kb/diffs/YYYY-MM-DD.json and (best effort)
appends a one-line summary to the gossip bus outbox knowledge/dreams/bus/workato-kb.jsonl.

The report carries a "scope" field ("full" or "scoped") so a targeted single-step run
is never mistaken for a nightly full sync. Full runs enforce a source-count floor:
if any core source step is missing or errors (or total changed-count collapses to 0
against a nonzero previous run), the sync fails loudly — report is still written but
a sync_alert is posted to the bus and the process exits nonzero. This guards against
a silently shrunken corpus/index (see knowledge/cortex/investigations/kb-sync-source-shrink.md).
"""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

from .common import DATA_ROOT, fetch_cached

# True ingest sources. Post-processing steps (attachments, contextualize, index, pmi,
# entropy, lateral, memory-entropy) and the Sunday-only jira-cases are not counted;
# a full run MUST complete every one of these or the sync is considered failed.
CORE_SOURCES = {"docs", "blog", "changelog", "inspiration", "github", "eip", "claude", "confluence"}


def _step_healthy(result) -> bool:
    """A step is healthy when it ran and did not record an error (skips count as ran)."""
    return isinstance(result, dict) and not result.get("error")


def _previous_report(today: str):
    """Most recent diff report strictly before today, for the collapse check."""
    diff_dir = DATA_ROOT / "diffs"
    if not diff_dir.is_dir():
        return None
    prior = sorted(p for p in diff_dir.glob("*.json") if p.stem < today)
    if not prior:
        return None
    try:
        return json.loads(prior[-1].read_text())
    except Exception:  # noqa: BLE001 - collapse check is best effort
        return None


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--no-embed", action="store_true")
    ap.add_argument("--sources", nargs="*", default=None)
    a = ap.parse_args()
    wanted = a.sources
    scope = "scoped" if wanted else "full"

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

    from . import attachments, contextualize, docs_source, eip_source, github_source, harness_source, links, llms_source, wp_source
    from .entropy import score as entropy_score
    from .indexer import build
    from .pmi import build as pmi_build

    try_step("docs", docs_source.sync)
    try_step("blog", wp_source.sync_blog)
    try_step("changelog", wp_source.changelog_incremental)
    try_step("inspiration", wp_source.sync_inspiration)
    try_step("github", github_source.sync)
    try_step("eip", eip_source.sync)
    try_step("claude", llms_source.sync, "claude")
    try_step("confluence", _confluence_best_effort)
    # harness source: Josh's knowledge tree + skills -> corpus/harness (NOT in
    # CORE_SOURCES: a harness failure must not fail the nightly floor)
    try_step("harness", harness_source.sync)
    try_step("attachments", attachments.sync)
    # link normalization: website-style .html / absolute docs links -> relative .md
    # links that resolve inside the corpus (Obsidian/md-graph edges). MUST run after
    # every source step or sources re-emit raw links; runs before index build.
    try_step("links", links.normalize)
    # weekly (Sundays): refresh the case base from newly-closed Jira bugs
    if dt.date.today().weekday() == 6 or (wanted and "jira-cases" in wanted):
        def _jira_case_refresh():
            import subprocess, sys as _sys
            r = _sp_run([_sys.executable, str(Path(__file__).parent / "jira_bulk_pull.py")], timeout=1800)
            return {"refresh": r.strip().splitlines()[-1] if r.strip() else "done"}
        try_step("jira-cases", _jira_case_refresh)
    try_step("contextualize", contextualize.run, 400)
    try_step("index", build, with_embeddings=not a.no_embed)
    try_step("pmi", pmi_build)
    try_step("entropy", entropy_score)

    # dream-team feedstock: concept graph + memory-entropy report
    if not wanted or "lateral" in wanted:
        try:
            from .lateral import build as lateral_build

            results["lateral"] = lateral_build()
        except Exception as e:  # noqa: BLE001
            errors.append(f"lateral: {e}")
    if not wanted or "memory-entropy" in wanted:
        try:
            from .dream_entropy import main as de_main

            de_main()
            results["memory-entropy"] = "written"
        except Exception as e:  # noqa: BLE001
            errors.append(f"memory-entropy: {e}")

    today = dt.date.today().isoformat()

    # --- source-count floor (full runs only) ---------------------------------
    # Fails loudly instead of silently writing a shrunken corpus/index.
    floor_failures: list[str] = []
    if scope == "full":
        missing_core = sorted(CORE_SOURCES - {n for n, r in results.items() if _step_healthy(r)})
        if missing_core:
            floor_failures.append(
                f"source-count floor: core sources missing or failed: {missing_core}"
            )
        changed_total = sum(
            r.get("changed", 0)
            for r in results.values()
            if isinstance(r, dict) and not r.get("error")
        )
        prev = _previous_report(today)
        if prev is not None:
            prev_changed = sum(
                r.get("changed", 0)
                for r in prev.get("results", {}).values()
                if isinstance(r, dict) and not r.get("error")
            )
            if prev_changed > 0 and changed_total == 0:
                floor_failures.append(
                    f"collapse check: 0 docs changed across all sources vs {prev_changed} in the previous run"
                )
    report = {"date": today, "scope": scope, "results": results, "errors": errors}
    if floor_failures:
        report["floor_failures"] = floor_failures
    diff_dir = DATA_ROOT / "diffs"
    diff_dir.mkdir(parents=True, exist_ok=True)
    (diff_dir / f"{today}.json").write_text(json.dumps(report, indent=2))

    # science-layer state -> the ops dashboard reads this
    try:
        from .cases import stats as case_stats
        from .curiosity import open_questions
        from .gym_judgment import history as gym_history
        from .model_routing import stats as routing_stats
        state = {
            "updated": dt.datetime.now().isoformat(timespec="seconds"),
            "cases": case_stats(),
            "curiosity_open": len(open_questions()),
            "judgment_gym": gym_history(),
            "model_routing": routing_stats().get("models", {}),
        }
        (DATA_ROOT / "science-state.json").write_text(json.dumps(state, indent=2))
    except Exception as e:  # noqa: BLE001
        print(f"[science-state write failed: {e}]", file=sys.stderr)

    # gossip bus (best effort)
    try:
        bus = Path.home() / ".claude/knowledge/dreams/bus"
        bus.mkdir(parents=True, exist_ok=True)
        # scoped runs: only the executed steps' counts are in the total
        changed_total = sum(
            r.get("changed", 0) for r in results.values() if isinstance(r, dict)
        )
        if floor_failures:
            bus_type, summary = "sync_alert", (
                f"KB sync {today} FAILED source-count floor ({scope}): "
                + " | ".join(floor_failures)
                + f"; per-step errors: {len(errors)}"
            )
        else:
            bus_type = "sync_report"
            summary = (
                f"KB sync {today} [{scope}]: {changed_total} docs changed across "
                f"{len(results)} steps; errors: {len(errors)}"
            )
        with (bus / "workato-kb.jsonl").open("a") as f:
            f.write(
                json.dumps(
                    {
                        "ts": dt.datetime.now().isoformat(),
                        "agent": "workato-kb",
                        "type": bus_type,
                        "scope": scope,
                        "summary": summary,
                        "details": {
                            "changed": changed_total,
                            "errors": errors,
                            "floor_failures": floor_failures,
                        },
                    }
                )
                + "\n"
            )
    except Exception:  # noqa: BLE001
        pass

    print(json.dumps(report, indent=2))
    if floor_failures:
        # loud failure AFTER the report + bus alert are on disk
        raise SystemExit(1)


def _sp_run(cmd, timeout):
    import subprocess

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return (r.stdout + r.stderr).strip()


def _confluence_best_effort():
    from . import confluence_sync

    out = {}
    for space in ("extbt", "intbt"):
        try:
            out[space] = confluence_sync.sync_space(space)
        except SystemExit as e:
            out[space] = {"skipped": str(e).strip().splitlines()[0]}
    return out


if __name__ == "__main__":
    main()
