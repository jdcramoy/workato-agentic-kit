#!/usr/bin/env python3
"""builder-stack.py — per-project builder-tool priority stack.

The registry (~/.claude/knowledge/builder-stacks/registry.json) is keyed by
canonical project path. This script is the ONLY writer; the /builder-stack
skill is the interview face that calls it.

Subcommands:
  resolve [path]                    Print the ranked stack for a project.
                                    Exit 1 (UNREGISTERED) when no entry —
                                    sessions must interview Josh before any
                                    Workato call on an unregistered project.
  list                              All registered projects.
  set <path> --stack a,b,c          Register/update a project's stack
        [--name N] [--folder ID]    (order = priority, first = first class).
        [--notes S]
  remove <path>                     Remove a project's entry.
"""

import argparse
import json
import os
import sys
from datetime import date

REGISTRY_PATH = os.path.expanduser(
    "~/.claude/knowledge/builder-stacks/registry.json")

# The known builder tools. Order here is display order only — per-project
# stacks define their own ranking.
KNOWN_BUILDERS = {
    "devapi-workato": "devapi-workato MCP (Workato Developer API semantic gateway)",
    "wt": "Workato Toolbox CLI (wt, dev/prod profiles)",
    "airo": "AIRO MCP (workato-airo-mcp-server dev / workato-airo-mcp-prod)",
    "workato-cli": "Workato CLI gem (workato pull/push)",
}


def load_registry():
    if os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH) as f:
            data = json.load(f)
    else:
        data = {}
    data.setdefault("projects", {})
    data.setdefault("known_builders", dict(KNOWN_BUILDERS))
    return data


def save_registry(data):
    os.makedirs(os.path.dirname(REGISTRY_PATH), exist_ok=True)
    tmp = REGISTRY_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")
    os.replace(tmp, REGISTRY_PATH)


def canon(path):
    return os.path.realpath(os.path.expanduser(path))


def cmd_resolve(args):
    path = canon(args.path)
    data = load_registry()
    entry = data["projects"].get(path)
    if entry is None:
        print(f"UNREGISTERED: {path}")
        print("No builder stack on file. Run /builder-stack (register) BEFORE "
              "any Workato call on this project — never guess a stack.")
        return 1
    print(f"project: {path}")
    print(f"name: {entry.get('name', '')}")
    print(f"workato_folder: {entry.get('workato_folder', '')}")
    print("stack:")
    for i, tool in enumerate(entry["stack"], 1):
        print(f"  {i}. {tool} — {KNOWN_BUILDERS.get(tool, 'unknown builder')}")
    if entry.get("notes"):
        print(f"notes: {entry['notes']}")
    print(f"registered: {entry.get('registered', '')}")
    return 0


def cmd_list(args):
    data = load_registry()
    projects = data["projects"]
    if not projects:
        print("No projects registered. Use /builder-stack to register one.")
        return 0
    for path in sorted(projects):
        entry = projects[path]
        stack = " > ".join(entry["stack"])
        folder = entry.get("workato_folder") or "-"
        print(f"{path}")
        print(f"  name: {entry.get('name', '-')}  folder: {folder}")
        print(f"  stack: {stack}")
        if entry.get("notes"):
            print(f"  notes: {entry['notes']}")
    return 0


def cmd_set(args):
    path = canon(args.path)
    stack = [s.strip() for s in args.stack.split(",") if s.strip()]
    if not stack:
        print("ERROR: --stack is empty", file=sys.stderr)
        return 1
    if len(stack) != len(set(stack)):
        print(f"ERROR: duplicate builders in --stack: {stack}", file=sys.stderr)
        return 1
    unknown = [s for s in stack if s not in KNOWN_BUILDERS]
    if unknown:
        print(f"ERROR: unknown builder(s): {', '.join(unknown)}", file=sys.stderr)
        print(f"known builders: {', '.join(sorted(KNOWN_BUILDERS))}", file=sys.stderr)
        return 1
    data = load_registry()
    data["known_builders"] = dict(KNOWN_BUILDERS)
    data["projects"][path] = {
        "name": args.name or "",
        "stack": stack,
        "workato_folder": args.folder or "",
        "registered": date.today().isoformat(),
        "notes": args.notes or "",
    }
    save_registry(data)
    print(f"registered: {path}")
    print("stack: " + " > ".join(stack))
    return 0


def cmd_remove(args):
    path = canon(args.path)
    data = load_registry()
    if path not in data["projects"]:
        print(f"ERROR: not registered: {path}", file=sys.stderr)
        return 1
    del data["projects"][path]
    save_registry(data)
    print(f"removed: {path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("resolve", help="resolve a project's stack")
    p.add_argument("path", nargs="?", default=os.getcwd())
    p.set_defaults(fn=cmd_resolve)

    p = sub.add_parser("list", help="list registered projects")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("set", help="register/update a project's stack")
    p.add_argument("path")
    p.add_argument("--stack", required=True,
                   help="comma-separated builders, first = first class")
    p.add_argument("--name", default="")
    p.add_argument("--folder", default="", help="Workato folder ID")
    p.add_argument("--notes", default="")
    p.set_defaults(fn=cmd_set)

    p = sub.add_parser("remove", help="remove a project's entry")
    p.add_argument("path")
    p.set_defaults(fn=cmd_remove)

    args = parser.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
