#!/usr/bin/env python3
"""lint-changed.py — PostToolUse hook (matcher Edit|Write): deterministic
syntax check on the file just written. Catches the runtime-discovered bug
class (regex/typo/py3.9-compat) before it executes.

Exits 0 always; on failure emits additionalContext so the model fixes it
immediately instead of discovering it at runtime. Silent on files it
can't check. Target <0.5s.
"""
import json, os, subprocess, sys

CHECKERS = {
    ".py": lambda p: (["python3", "-m", "py_compile", p], ""),
    ".rb": lambda p: (["ruby", "-c", p], ""),
    ".sh": lambda p: (["bash", "-n", p], ""),
    ".js": lambda p: (["node", "--check", p], ""),
    ".mjs": lambda p: (["node", "--check", p], ""),
    # XML family incl. launchd plists — catches tag-mangle corruption on write
    ".plist": lambda p: (["plutil", "-lint", p], ""),
    ".xml": lambda p: (["xmllint", "--noout", p], ""),
}


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    path = (payload.get("tool_input") or {}).get("file_path") or ""
    if not path or not os.path.isfile(path):
        return
    check = CHECKERS.get(os.path.splitext(path)[1].lower())
    if not check:
        return
    cmd, _ = check(path)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        ok = r.returncode == 0
        err = (r.stderr or r.stdout or "").strip()
    except Exception as e:
        ok, err = True, f"(checker failed to run: {e})"  # never block on hook failure
    if ok:
        return
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": (
                f"SYNTAX CHECK FAILED for {os.path.basename(path)} — fix this now, "
                f"before any further work:\n{err[:800]}"),
        }
    }))


if __name__ == "__main__":
    main()
