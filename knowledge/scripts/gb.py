#!/usr/bin/env python3
"""gb.py — goto-bookmark for the Orca browser (Orca has no native bookmarks).

Usage:
  python3 ~/.claude/knowledge/scripts/gb.py <name>          # navigate active tab
  python3 ~/.claude/knowledge/scripts/gb.py --list          # list entries
Hotlist: ~/.claude/knowledge/browser-hotlist.json
"""
import json, subprocess, sys, os

HOTLIST = os.path.expanduser("~/.claude/knowledge/browser-hotlist.json")
ORCA = "/Applications/Orca.app/Contents/Resources/bin/orca"

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    with open(HOTLIST) as f:
        hot = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
    if sys.argv[1] == "--list":
        for k, v in sorted(hot.items()):
            print(f"{k:20s} {v[:90]}")
        return
    name = sys.argv[1]
    if name not in hot:
        print(f"no hotlist entry '{name}'. Have: {', '.join(sorted(hot))}")
        sys.exit(1)
    r = subprocess.run([ORCA, "goto", "--url", hot[name], "--json"],
                       capture_output=True, text=True)
    out = json.loads(r.stdout or "{}")
    ok = out.get("ok")
    print(("navigated: " if ok else "FAILED: ") + name + " -> " + hot[name][:80])
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
