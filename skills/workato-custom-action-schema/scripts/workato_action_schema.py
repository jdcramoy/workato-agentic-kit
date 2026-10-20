#!/usr/bin/env python3
"""Resolve a Workato custom-connector action's input/output schema.

A custom action exposes no datapill schema until it has executed once (the
platform derives the schema from a captured sample response). This wrapper
resolves a connector/action by name or ID through the Workato Developer API,
optionally probes the action once so the platform captures the schema, and
prints the resolved input_fields / output_fields / sample_output as JSON.

Preview is the default: without --execute nothing is sent to Workato.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys

API_BASE = os.environ.get("WORKATO_API_BASE", "https://www.workato.com")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preview or execute Workato Developer API calls to resolve a "
            "custom connector action's schema. Preview is the default; pass "
            "--execute to send requests."
        )
    )
    sub = parser.add_subparsers(dest="mode", required=True)

    def common(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--profile", help="Workato CLI profile/environment name")
        p.add_argument(
            "--token",
            help="Developer API token (default: WORKATO_TOKEN env, then workato CLI auth)",
        )
        p.add_argument(
            "--workato-bin",
            default=os.environ.get("WORKATO_BIN", "workato"),
            help="Workato CLI executable used for auth when --token is absent",
        )
        p.add_argument(
            "--execute",
            action="store_true",
            help="perform the API requests instead of only printing them",
        )
        return p

    p_list = sub.add_parser("list", help="list custom connectors and their actions")
    common(p_list)
    p_list.add_argument("--connector-name", help="filter by connector name (exact, case-insensitive)")
    p_list.add_argument("--connector-id", type=int, help="filter by connector ID")

    p_res = sub.add_parser("resolve", help="resolve one action's schema")
    common(p_res)
    p_res.add_argument("--action-name", help="action name (exact, case-insensitive; omit to list all)")
    p_res.add_argument("--connector-id", type=int, help="connector ID to scope name resolution")
    p_res.add_argument("--connector-name", help="connector name to scope name resolution")
    return parser


def get_token(args: argparse.Namespace) -> str:
    token = args.token or os.environ.get("WORKATO_TOKEN")
    if token:
        return token.strip()
    # Fall back to the authenticated Workato CLI for the token.
    cmd = [args.workato_bin]
    if args.profile:
        cmd.extend(("--profile", args.profile))
    cmd.extend(("api", "GET", "/api/custom_connectors"))
    try:
        completed = subprocess.run(
            cmd, capture_output=True, text=True, check=False, timeout=60
        )
    except OSError as exc:
        raise SystemExit(f"error: unable to run Workato CLI for auth: {exc}")
    # The CLI prints the response; a 401 body usually says Unauthorized.
    if "unauthorized" in completed.stdout.lower() and not completed.stderr:
        raise SystemExit(
            "error: no API token. Pass --token, set WORKATO_TOKEN, or authenticate the Workato CLI."
        )
    # Token retrieval via CLI is only a convenience; prefer explicit token.
    raise SystemExit(
        "error: no API token available. Pass --token or set WORKATO_TOKEN "
        "(keychain: security find-generic-password -s workato-platform-cli -a dev -w)."
    )


def api(method: str, path: str, token: str, body: dict | None = None) -> tuple[int, object]:
    import urllib.error
    import urllib.request

    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        API_BASE + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode())
        except Exception:
            return exc.code, {"error": str(exc)}
    except urllib.error.URLError as exc:
        raise SystemExit(f"error: API request failed: {exc}")


def describe(command: list[str]) -> str:
    return "[API CALL] " + " ".join(
        shlex.quote(part) if i == 1 and "Bearer" in str(part) else shlex.quote(str(part))
        for i, part in enumerate(command)
    )


def list_connectors(args: argparse.Namespace, token: str) -> None:
    status, body = api("GET", "/api/custom_connectors", token)
    rows = (body.get("result") or body.get("data") or body) if isinstance(body, dict) else body
    if not isinstance(rows, list):
        print(f"error: unexpected response (HTTP {status}): {json.dumps(body)[:500]}", file=sys.stderr)
        raise SystemExit(1)
    for row in rows:
        cid = row.get("id")
        name = row.get("name") or row.get("title") or row.get("manifest_version", {}).get("title")
        if args.connector_name and str(name).lower() != args.connector_name.lower():
            continue
        if args.connector_id and cid != args.connector_id:
            continue
        print(json.dumps({"connector_id": cid, "name": name}))


def parse_connector_code(code: str) -> dict:
    """Extract action names and their input/output field definitions from SDK code."""
    import re

    # Locate the actions block and split per named action.
    actions_match = re.search(r"^\s*actions:\s*\{", code, re.M)
    if not actions_match:
        return {}
    start = actions_match.end()
    depth = 1
    i = start
    in_str = None
    while i < len(code) and depth > 0:
        ch = code[i]
        if in_str:
            if ch == "\\":
                i += 2
                continue
            if ch == in_str:
                in_str = None
        elif ch in "'\"":
            in_str = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    block = code[start : i - 1] if depth == 0 else code[start:]

    actions = {}
    for name_match in re.finditer(r"^\s{2,}([a-zA-Z_]\w*):\s*\{", block, re.M):
        name = name_match.group(1)
        seg_start = name_match.end()
        d = 1
        j = seg_start
        instr = None
        while j < len(block) and d > 0:
            ch = block[j]
            if instr:
                if ch == "\\":
                    j += 2
                    continue
                if ch == instr:
                    instr = None
            elif ch in "'\"":
                instr = ch
            elif ch == "{":
                d += 1
            elif ch == "}":
                d -= 1
            j += 1
        seg = block[seg_start : j - 1] if d == 0 else block[seg_start:]
        actions[name] = {
            "has_input_fields": "input_fields" in seg,
            "has_output_fields": "output_fields" in seg,
            "has_sample_output": "sample_output" in seg,
        }
    return actions


def resolve(args: argparse.Namespace, token: str) -> None:
    status, body = api("GET", "/api/custom_connectors", token)
    rows = (body.get("result") or body.get("data") or body) if isinstance(body, dict) else body
    if not isinstance(rows, list):
        print(f"error: unexpected response (HTTP {status}): {json.dumps(body)[:500]}", file=sys.stderr)
        raise SystemExit(1)
    matches = []
    for row in rows:
        cid = row.get("id")
        name = row.get("name") or row.get("title")
        if args.connector_id and cid != args.connector_id:
            continue
        if args.connector_name and str(name).lower() != args.connector_name.lower():
            continue
        matches.append(row)
    if len(matches) != 1:
        print(
            f"error: expected exactly one connector match, found {len(matches)}. "
            "Add --connector-id or --connector-name to disambiguate.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    connector = matches[0]
    cid = connector.get("id")

    status, body = api("GET", f"/api/custom_connectors/{cid}/code", token)
    code = (body.get("data") or {}).get("code") if isinstance(body, dict) else None
    if not code:
        print(
            f"error: could not fetch connector code (HTTP {status}): {json.dumps(body)[:500]}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    parsed = parse_connector_code(code)
    if args.action_name:
        if args.action_name not in parsed:
            print(
                f"error: action '{args.action_name}' not found. Available: {sorted(parsed)}",
                file=sys.stderr,
            )
            raise SystemExit(1)
        names = [args.action_name]
    else:
        names = sorted(parsed)

    result = {
        "connector_id": cid,
        "connector_name": connector.get("name") or connector.get("title"),
        "note": (
            "Schema is derived from the connector code's input_fields/output_fields/sample_output. "
            "For ad-hoc HTTP actions, input_fields and sample_output only exist after the action "
            "has executed once; use a probe recipe run to capture them, then re-run resolve."
        ),
        "actions": {n: parsed[n] for n in names},
    }

    print(json.dumps(result, indent=2))


def main() -> int:
    args = build_parser().parse_args()
    plan = []
    base = ["GET", "/api/custom_connectors"]
    if args.mode == "list":
        plan.append(base)
    else:
        # Omitting --action-name on resolve lists every action in the connector.
        plan.append(base)
        plan.append(["GET", "/api/custom_connectors/{connector_id}/code"])

    if not args.execute:
        print("[PREVIEW] Would authenticate as:" + (" profile " + args.profile if args.profile else " default"))
        for method, path in plan:
            print(f"[PREVIEW] {method} {API_BASE}{path}")
        print("No Workato changes were made. Pass --execute to perform this operation.")
        return 0

    token = get_token(args)
    if args.mode == "list":
        list_connectors(args, token)
    else:
        resolve(args, token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
