#!/usr/bin/env python3
"""lint-changed.py — PostToolUse hook (matcher Edit|Write): deterministic
syntax check on the file just written. Catches the runtime-discovered bug
class (regex/typo/py3.9-compat) before it executes.

Exits 0 always; on failure emits additionalContext so the model fixes it
immediately instead of discovering it at runtime. Silent on files it
can't check. Target <0.5s.
"""
import json, os, re, subprocess, sys

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


# Insertion-edit clobber class (cortex investigations/insertion-edit-clobber-class.md):
# Edit anchored on a single def/class/lambda line, new_string dropped the definition.
DEF_ANCHOR = re.compile(r"^(?:(?:async\s+)?def\s+(\w+)\s*\(|class\s+(\w+)|[\w.]+\s*=\s*lambda\b)")


def insertion_clobber(old_string: str, new_string: str):
    """WARN if a single-line def/class/lambda anchor was consumed (not re-included)."""
    stripped = old_string.strip()
    if "\n" in stripped:
        return None  # multi-line edit: not the anchor pattern
    m = DEF_ANCHOR.match(stripped)
    if not m:
        return None
    name = m.group(1) or m.group(2) or stripped.split("=")[0].strip()
    if re.search(
        rf"def\s+{re.escape(name)}\b|class\s+{re.escape(name)}\b|{re.escape(name)}\s*=\s*lambda\b",
        new_string,
    ):
        return None  # anchor re-included (possibly modified) — fine
    return (
        f"INSERTION-CLOBBER: Edit used the '{name}' definition line as its only anchor "
        f"but new_string does not define '{name}' — the def/class/lambda was replaced "
        f"(deleted) and its body dangles. Re-include the definition line in new_string."
    )


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or ""
    warnings = []
    # Post-edit clobber check (Edit calls only — Write has no old/new strings)
    old, new = tool_input.get("old_string"), tool_input.get("new_string")
    if isinstance(old, str) and isinstance(new, str):
        w = insertion_clobber(old, new)
        if w:
            warnings.append(w)
    if not path or not os.path.isfile(path):
        if not warnings:
            return
        _emit(path, "SYNTAX/EDIT CHECK", "\n\n".join(warnings))
        return
    check = CHECKERS.get(os.path.splitext(path)[1].lower())
    err = ""
    if check:
        cmd, _ = check(path)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            ok = r.returncode == 0
            err = (r.stderr or r.stdout or "").strip()
        except Exception as e:
            ok, err = True, f"(checker failed to run: {e})"  # never block on hook failure
        if not ok:
            warnings.insert(0, f"SYNTAX CHECK FAILED for {os.path.basename(path)} — fix this now, before any further work:\n{err[:800]}")
    if not warnings:
        return
    _emit(path, "EDIT CHECK", "\n\n".join(warnings))


def _emit(path: str, lead: str, message: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": f"{lead} for {os.path.basename(path) or path}:\n{message[:800]}",
        }
    }))


if __name__ == "__main__":
    main()
