#!/usr/bin/env python3
"""Safely start or stop Workato recipes through the Workato Developer CLI."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def positive_int(value: str) -> int:
    """Parse a positive integer CLI identifier."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or execute a Workato recipe start/stop operation. "
            "Preview is the default; pass --execute to mutate Workato."
        )
    )
    parser.add_argument("action", choices=("start", "stop"))

    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--recipe-id",
        type=positive_int,
        nargs="+",
        metavar="ID",
        help="target one or more recipe IDs",
    )
    scope.add_argument("--folder-id", type=positive_int, metavar="ID")
    scope.add_argument(
        "--all",
        action="store_true",
        dest="all_recipes",
        help="target every recipe in the current Workato CLI project",
    )

    parser.add_argument("--profile", help="Workato CLI profile/environment name")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="perform the external mutation instead of only printing the command",
    )
    parser.add_argument(
        "--workato-bin",
        default=os.environ.get("WORKATO_BIN", "workato"),
        help="Workato CLI executable (default: WORKATO_BIN or 'workato')",
    )
    return parser


def resolve_executable(value: str) -> str:
    if os.path.sep in value:
        candidate = Path(value).expanduser()
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise FileNotFoundError(f"Workato CLI is not executable: {candidate}")
        return str(candidate)

    resolved = shutil.which(value)
    if resolved is None:
        raise FileNotFoundError(
            f"Workato CLI '{value}' was not found in PATH; install it or pass --workato-bin"
        )
    return resolved


def command_prefix(args: argparse.Namespace, executable: str) -> list[str]:
    command = [executable]
    if args.profile:
        command.extend(("--profile", args.profile))
    command.extend(("recipes", args.action))
    return command


def build_commands(args: argparse.Namespace, executable: str) -> list[list[str]]:
    prefix = command_prefix(args, executable)
    if args.recipe_id is not None:
        return [prefix + ["--id", str(recipe_id)] for recipe_id in args.recipe_id]
    if args.folder_id is not None:
        return [prefix + ["--folder-id", str(args.folder_id)]]
    return [prefix + ["--all"]]


def main() -> int:
    args = build_parser().parse_args()
    try:
        executable = resolve_executable(args.workato_bin)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 127

    commands = build_commands(args, executable)
    mode = "EXECUTE" if args.execute else "PREVIEW"
    for command in commands:
        print(f"[{mode}] {shlex.join(command)}", flush=True)
    if not args.execute:
        print("No Workato changes were made. Pass --execute to perform this operation.")
        return 0

    failed = 0
    for command in commands:
        try:
            completed = subprocess.run(command, check=False)
        except OSError as exc:
            print(f"error: unable to run Workato CLI: {exc}", file=sys.stderr)
            failed += 1
            continue
        if completed.returncode != 0:
            failed += 1

    if failed:
        print(
            f"error: {failed} of {len(commands)} Workato operation(s) failed",
            file=sys.stderr,
        )
        return 1
    print(f"Completed {len(commands)} Workato operation(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
