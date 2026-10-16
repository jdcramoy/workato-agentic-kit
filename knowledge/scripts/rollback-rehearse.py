#!/usr/bin/env python3
"""Rollback rehearsal runner — the mechanical "prove it's revertable" step.

Every dev-recipe fix ends with a REHEARSED rollback: snapshot exists, revert
works, re-apply verified. This script is the mechanical (zero-LLM) runner
behind the `rollback-rehearsal` skill.

  rollback-rehearse.py --recipe 82921718            # dry rehearsal (default)
  rollback-rehearse.py --recipe 82921718 --live     # real revert, gated

Dry mode (default):
  1. `wt recipes versions <id>` — parse the newest version (current).
  2. Pick version N-1 and validate the version object exists with an id.
  3. `wt recipes get <id>` — validate the recipe carries code (non-empty),
     capture it as the rollback snapshot, and round-trip-verify the saved
     snapshot file parses and contains code.
  4. Append one line to ~/.claude/knowledge/garden-reports/rollback-rehearsals.jsonl.

Live mode (--live): additionally performs the real revert. The Workato
Developer API does not expose a version's historical code, so the snapshot is
the revert artifact: --live requires the recipe to be in the DEV workspace
(user_id 3535597) and STOPPED, then pushes the newest snapshot's code back
(creating a new version, re-establishing the baseline), and verifies the
version list grew. Never run --live against a running or prod recipe.

Exit 0 on success, 2 on failure. stdlib + subprocess to wt only.
"""

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys

WT = os.path.expanduser("~/.local/bin/wt")
LEDGER = os.path.expanduser(
    "~/.claude/knowledge/garden-reports/rollback-rehearsals.jsonl"
)
HISTORY_DIR = os.path.expanduser("~/.claude/recipe-history")
DEV_WORKSPACE_USER_ID = 3535597  # dev ws 3535597; anything else is not dev


def log_line(msg):
    print(msg)


def fail(msg):
    print("FAIL: %s" % msg, file=sys.stderr)
    sys.exit(2)


def run_wt(args):
    proc = subprocess.run(
        [WT] + args, capture_output=True, text=True, timeout=120
    )
    if proc.returncode != 0:
        fail("wt %s exited %d: %s" % (" ".join(args), proc.returncode, proc.stderr.strip()[:300]))
    return proc.stdout


def wt_json(args):
    out = run_wt(args)
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        fail("wt %s returned non-JSON output: %s" % (" ".join(args), exc))


def append_ledger(entry):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, sort_keys=False) + "\n")


# partial facts recorded as the run progresses, so a failed run still
# leaves an auditable ledger line with result: failure
_PARTIAL = {"ts": None, "recipe_id": None, "current_version": None,
            "prior_version": None, "snapshot_path": None, "mode": "dry"}


def fail(msg):
    print("FAIL: %s" % msg, file=sys.stderr)
    if _PARTIAL["ts"]:
        _PARTIAL["result"] = "failure"
        _PARTIAL["error"] = msg[:300]
        try:
            append_ledger(_PARTIAL)
        except Exception:
            pass
    sys.exit(2)


def main():
    parser = argparse.ArgumentParser(description="Rollback rehearsal runner")
    parser.add_argument("--recipe", required=True, type=int, help="dev recipe id")
    parser.add_argument(
        "--live",
        action="store_true",
        help="actually revert (requires recipe in DEV workspace AND stopped)",
    )
    parser.add_argument(
        "--profile", default=None, help="wt profile (default: wt current)"
    )
    args = parser.parse_args()
    recipe_id = args.recipe
    mode = "live" if args.live else "dry"

    profile_args = ["--profile", args.profile] if args.profile else []

    def wt_recipe(cmd_args):
        return wt_json(["recipes", *profile_args, cmd_args, str(recipe_id)])

    ts = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    _PARTIAL["ts"] = ts
    _PARTIAL["recipe_id"] = recipe_id
    _PARTIAL["mode"] = mode

    # --- 1. current version -------------------------------------------------
    versions_doc = wt_recipe("versions")
    versions = versions_doc.get("data") or []
    if not versions:
        fail("recipe %s has no version list" % recipe_id)
    versions_sorted = sorted(versions, key=lambda v: v.get("version_no") or 0)
    current = versions_sorted[-1]
    current_version = current.get("version_no")
    _PARTIAL["current_version"] = current_version
    if current_version is None or current_version < 1:
        fail("could not parse newest version_no for recipe %s" % recipe_id)
    log_line(
        "recipe %s: current version %s (id %s)"
        % (recipe_id, current_version, current.get("id"))
    )

    # --- 2. prior version N-1 ------------------------------------------------
    prior = next(
        (v for v in versions_sorted if v.get("version_no") == current_version - 1),
        None,
    )
    if prior is None or not prior.get("id"):
        fail(
            "recipe %s has no version N-1 (%s) to rehearse against"
            % (recipe_id, current_version - 1)
        )
    log_line(
        "prior version %s exists (id %s, created %s)"
        % (prior["version_no"], prior["id"], prior.get("created_at"))
    )
    _PARTIAL["prior_version"] = prior["version_no"]

    # --- 3. code snapshot ----------------------------------------------------
    recipe_doc = wt_recipe("get")
    code = recipe_doc.get("code") or ""
    if not isinstance(code, str) or not code.strip():
        fail("recipe %s get() returned empty/missing code" % recipe_id)
    code_sha = hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]
    running = bool(recipe_doc.get("running"))
    user_id = recipe_doc.get("user_id")

    snapshot_dir = os.path.join(HISTORY_DIR, str(recipe_id))
    os.makedirs(snapshot_dir, exist_ok=True)
    snap_ts = datetime.datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    snapshot_path = os.path.join(snapshot_dir, "pre-rehearsal-%s.json" % snap_ts)
    snapshot = {
        "ts": ts,
        "recipe_id": recipe_id,
        "mode": mode,
        "captured_version_no": current_version,
        "captured_version_id": current.get("id"),
        "prior_version_no": prior["version_no"],
        "prior_version_id": prior["id"],
        "code_sha256": code_sha,
        "code_length": len(code),
        "recipe": recipe_doc,
    }
    with open(snapshot_path, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2)
    _PARTIAL["snapshot_path"] = snapshot_path

    # round-trip: the snapshot must itself prove rollback material exists
    with open(snapshot_path, encoding="utf-8") as fh:
        check = json.load(fh)
    if not (check.get("recipe") or {}).get("code"):
        fail("snapshot round-trip failed: saved snapshot carries no code")
    log_line(
        "snapshot %s (code sha %s, %d chars) round-trip OK"
        % (snapshot_path, code_sha, len(code))
    )

    result = "success"
    extra = {}

    # --- 4. live revert (gated) ----------------------------------------------
    if args.live:
        if user_id != DEV_WORKSPACE_USER_ID:
            fail(
                "--live refused: recipe %s is not in the dev workspace "
                "(user_id %s != %s)" % (recipe_id, user_id, DEV_WORKSPACE_USER_ID)
            )
        if running:
            fail(
                "--live refused: recipe %s is RUNNING. Stop it first "
                "(wt recipes stop %s), then re-run." % (recipe_id, recipe_id)
            )
        restore_doc = wt_json(
            [
                "api",
                *profile_args,
                "PUT",
                "/api/recipes/%s" % recipe_id,
                "--data",
                json.dumps({"code": code}),
            ]
        )
        restored = restore_doc.get("data") or restore_doc
        extra["live_restore_id"] = restored.get("id")
        extra["live_restore_version_no"] = restored.get("version_no")
        log_line(
            "live revert applied: code re-pushed as version %s"
            % restored.get("version_no")
        )
        verify_doc = wt_recipe("versions")
        new_top = max(
            (v.get("version_no") or 0 for v in verify_doc.get("data") or []),
            default=0,
        )
        if new_top <= current_version:
            fail("live revert not confirmed: top version is %s" % new_top)
        log_line("live revert verified: version list grew to %s" % new_top)
        extra["live_verified_top_version"] = new_top

    # --- 5. ledger ------------------------------------------------------------
    entry = {
        "ts": ts,
        "recipe_id": recipe_id,
        "current_version": current_version,
        "prior_version": prior["version_no"],
        "snapshot_path": snapshot_path,
        "mode": mode,
        "result": result,
    }
    entry.update(extra)
    append_ledger(entry)
    log_line("ledger entry appended: %s" % LEDGER)
    print("OK: rollback rehearsal (%s) passed for recipe %s" % (mode, recipe_id))
    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — fail-closed runner
        fail("unexpected error: %r" % (exc,))
