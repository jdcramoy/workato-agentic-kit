#!/usr/bin/env python3
"""dream-config.py — trust-ladder control for the harness dreamer.

Usage:
  dream-config.py show                     print current config
  dream-config.py set-mode <mode>          report | propose | auto-safe
Upgrades are intentional: only Josh runs set-mode.
"""
import json, os, sys

CONFIG = os.path.expanduser("~/.claude/knowledge/dreams/config.json")
VALID = ("report", "propose", "auto-safe", "auto-dev")

def main():
    if len(sys.argv) < 2:
        print(__doc__); return 1
    cmd = sys.argv[1]
    cfg = json.load(open(CONFIG))
    if cmd == "show":
        print(json.dumps(cfg, indent=1)); return 0
    if cmd == "set-mode":
        mode = sys.argv[2] if len(sys.argv) > 2 else ""
        if mode not in VALID:
            print(f"invalid mode '{mode}'. valid: {', '.join(VALID)}"); return 1
        cfg["mode"] = mode
        json.dump(cfg, open(CONFIG, "w"), indent=2)
        print(f"dreamer mode -> {mode}")
        print(f"never_auto (constitutional): {', '.join(cfg['never_auto'])}")
        if mode == "auto-dev":
            print(f"auto-dev allow: {', '.join(cfg.get('auto_dev_allow', []))}")
            print(f"auto-dev NEVER: {', '.join(cfg.get('auto_dev_never', []))}")
        return 0
    print(__doc__); return 1

if __name__ == "__main__":
    sys.exit(main())
