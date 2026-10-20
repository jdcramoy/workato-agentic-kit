#!/usr/bin/env python3
"""manifest-sweep.py — dead-session manifest sweep (cortex fix 2026-10-20).

Finds sessions that mutated Workato assets (AIRO MCP mutation tool calls or
CLI writes in ~/.claude/projects/**.jsonl transcripts) but ended with NO
manifest-guard evidence: no `wt manifests create/update`, no manifest-guard/
drift run, no test-probe exemption declaration.

Detection logic is reused from ~/.claude/hooks/manifest-guard.sh (same tool
regex, same command-word CLI parsing, same evidence patterns) so the sweep
and the live guard agree on what counts.

Bounded: transcripts modified in the last --days (default 2 = 48h) AND idle
for at least --idle-minutes (default 30, so a running session never flags).
Historical class this exists for: d977ff84 (19 recipe mutations, zero manifest
work, tickets closed).

Output: human digest to stdout; --json for machine reads. Read-only — never
writes, never remediates.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

PROJECTS = Path.home() / ".claude/projects"

MUT_TOOL = re.compile(
    r"^mcp__workato-airo-mcp-(server|prod)__("
    r"recipe_builder_(init|init_skill|push|save|add_step|remove_step|update_step|"
    r"remove_input_field|move_step|move_steps|set_input_field|set_input_field_v4_mode|"
    r"set_condition|set_foreach_source|set_error_handling_config|set_block_comments|"
    r"update_asset_metadata|select_connections|convert_to_skill)"
    r"|blueprint_(apply|init|push|link_asset|reset)"
    r"|genie_(create|update)"
    r"|data_table_(create|update|delete|truncate)"
    r"|knowledge_base_(create|delete|update|delete_documents)"
    r"|mcp_server_create"
    r"|connector_builder_(apply_connector_code_patch|save_latest_connector_code|release_connector)"
    r")$"
)


def is_cli_mutation(cmd: str) -> bool:
    for line in cmd.split("\n"):
        for seg in re.split(r"&&|\|\||[;|]", line):
            s = seg.strip()
            s = re.sub(r"^(?:sudo|env)((?:[ ]+\S+=\S+)+)?[ ]+", "", s)
            if not s:
                continue
            base = os.path.basename(s.split(" ")[0])
            rest = s[len(s.split(" ")[0]):]
            if base in ("wt-prod", "workato-prod", "wt", "workato"):
                if re.search(
                    r"\b(recipes?[ ]+(?:push|import|copy)|packages?[ ]+import|"
                    r"dt[ ]+(?:create|update|delete|truncate|add-row|upsert)|"
                    r"lookup[ ]+(?:add|upsert|delete)|"
                    r"api[ ]+(?:PUT|POST|DELETE))\b", rest,
                ):
                    return True
    return False


def label_for(kind: str) -> str:
    return ("recipe edit" if "recipe_builder" in kind
            else "data table" if "data_table" in kind
            else "genie" if "genie" in kind
            else "knowledge base" if "knowledge_base" in kind
            else "mcp server" if "mcp_server" in kind
            else "blueprint" if "blueprint" in kind
            else "connector")


def scan_transcript(path: Path) -> dict | None:
    """Return suspicion record for one transcript, or None if clean."""
    mutations: list[str] = []
    manifest_seen = False
    first_ts = last_ts = None
    pending_manifest_cmd = None  # (tool_use_id, create|update) awaiting result
    try:
        with open(path, errors="ignore") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ts = rec.get("timestamp")
                if ts:
                    if first_ts is None:
                        first_ts = ts
                    last_ts = ts
                msg = rec.get("message") or {}
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    if c.get("type") == "tool_use":
                        name = c.get("name", "") or ""
                        if MUT_TOOL.match(name):
                            mutations.append(label_for(name.split("__", 1)[1]))
                        elif name == "Bash":
                            cmd = str((c.get("input") or {}).get("command", ""))
                            if is_cli_mutation(cmd):
                                cmd_l = cmd.lower()
                                mutations.append(
                                    "package import" if "import" in cmd_l
                                    else "prod write" if "wt-prod" in cmd_l or "workato-prod" in cmd_l
                                    else "cli write")
                            # PAIRED manifest evidence (guard verification-stage
                            # logic): a real command-word `wt manifests
                            # create|update`, credited only when its own result
                            # carries a real manifest record. Blob-level matching
                            # false-cleared d977ff84 (its transcript quotes the
                            # wt help text inside a tool_result).
                            for seg in re.split(r"&&|\|\||\n|[;|]", cmd):
                                s = seg.strip()
                                m = re.match(r"^(?:sudo |env )?(?:\S*/)?(?:wt|workato)\s+manifests\s+(create|update)\b", s)
                                if m:
                                    pending_manifest_cmd = (c.get("id"), m.group(1))
                    elif c.get("type") == "tool_result" and pending_manifest_cmd and c.get("tool_use_id") == pending_manifest_cmd[0]:
                        text = c.get("content") if isinstance(c.get("content"), str) else json.dumps(c.get("content", ""))
                        if re.search(r'"id"\s*:\s*(\d{6})(?!\d)', text) and ("created_at" in text or "updated_at" in text):
                            manifest_seen = True
                        pending_manifest_cmd = None
                    elif (c.get("type") == "text" and msg.get("role") == "assistant"
                          and re.search(r"manifest exemption: test probe", c.get("text", ""), re.IGNORECASE)):
                        manifest_seen = True
    except Exception as e:
        return {"error": f"unreadable: {e}"}
    if not mutations or manifest_seen:
        return None
    from collections import Counter
    counts = Counter(mutations)
    return {
        "session": path.stem,
        "project": path.parent.name,
        "mutations": dict(counts),
        "total": sum(counts.values()),
        "first_seen": first_ts,
        "last_seen": last_ts,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--days", type=float, default=2.0, help="look-back window (default 2 = 48h)")
    ap.add_argument("--idle-minutes", type=float, default=30.0,
                    help="skip transcripts modified more recently than this (default 30) — live sessions never flag")
    ap.add_argument("--json", action="store_true", dest="as_json", help="machine-readable output")
    a = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=a.days)
    idle_cutoff = now - dt.timedelta(minutes=a.idle_minutes)

    suspects = []
    scanned = 0
    if PROJECTS.is_dir():
        for path in PROJECTS.rglob("*.jsonl"):
            try:
                mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, dt.timezone.utc)
            except OSError:
                continue
            if mtime > idle_cutoff:
                continue  # session may still be live — never flag
            if mtime < cutoff:
                continue
            scanned += 1
            rec = scan_transcript(path)
            if rec and "error" not in rec:
                rec["mtime"] = mtime.strftime("%Y-%m-%dT%H:%M:%SZ")
                suspects.append(rec)
            elif rec:
                rec["session"] = path.stem
                suspects.append(rec)

    suspects.sort(key=lambda r: -r.get("total", 0))

    if a.as_json:
        print(json.dumps({
            "window_days": a.days,
            "idle_minutes": a.idle_minutes,
            "transcripts_scanned": scanned,
            "suspects": suspects,
        }, indent=2))
        return

    print(f"MANIFEST SWEEP — window: last {a.days:g}d (idle > {a.idle_minutes:g}m), "
          f"transcripts scanned: {scanned}")
    if not suspects:
        print("No dead sessions with unmanifested Workato mutations found. CLEAN.")
        return
    for s in suspects:
        if "error" in s:
            print(f"\n[unreadable] {s['session']}: {s['error']}")
            continue
        muts = ", ".join(f"{k} x{v}" for k, v in sorted(s["mutations"].items(), key=lambda kv: -kv[1]))
        print(f"\nSUSPECT {s['session']}")
        print(f"  project:   {s['project']}")
        print(f"  mutations: {s['total']} ({muts})")
        print(f"  activity:  {s.get('first_seen', '?')} -> {s.get('last_seen', '?')} (mtime {s.get('mtime')})")
        print(f"  evidence:  zero wt manifests create/update, zero guard/drift runs, no exemption")
    print(f"\n{len(suspects)} suspect session(s). Review each transcript for manifest work "
          "before backfilling — create manifests via create_manifest.py (manifest-creation skill), never by hand.")


if __name__ == "__main__":
    main()
