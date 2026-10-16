#!/usr/bin/env python3
"""sight.py — one-call perception for the Orca browser loop.

Gives Claude Code Codex-style act->look latency: a single invocation returns
the tab's accessibility snapshot (stable element refs), decodes the screenshot
to a PNG file for the Read tool, and optionally pulls captured network/console.

Usage:
  python3 sight.py                    # tab snapshot + screenshot
  python3 sight.py --screen           # whole-screen capture (native UI, dialogs)
  python3 sight.py --both             # tab + whole screen
  python3 sight.py --net 10 --console 10   # also show captured network/console
  python3 sight.py --png-only         # paths only, no ref table

Output is plain text: file paths first (PNG + snapshot JSON), then a compact
ref table (ref  role  name) for direct use with `orca click --element <ref>`.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import time

ORCA_CANDIDATES = [
    "/Applications/Orca.app/Contents/Resources/bin/orca",
]
TRANSLOCATED_GLOB = "/private/var/folders"


def resolve_orca() -> str:
    for c in ORCA_CANDIDATES:
        if os.path.exists(c):
            return c
    try:
        out = subprocess.run(
            ["find", TRANSLOCATED_GLOB, "-maxdepth", "6",
             "-path", "*Orca.app/Contents/Resources/bin/orca"],
            capture_output=True, text=True, timeout=30).stdout.strip()
        if out:
            return out.splitlines()[0]
    except Exception:
        pass
    sys.exit("sight: orca binary not found")


def orca_json(orca: str, *args: str, timeout: int = 90):
    r = subprocess.run([orca, *args, "--json"],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        sys.exit(f"sight: orca {' '.join(args)} failed: {r.stderr.strip()[:300]}")
    try:
        payload = json.loads(r.stdout)
    except ValueError:
        sys.exit(f"sight: unparsable orca {' '.join(args)} output: {r.stdout[:300]}")
    if not payload.get("ok"):
        sys.exit(f"sight: orca {' '.join(args)} not ok: {json.dumps(payload)[:300]}")
    return payload.get("result", {})


def save_png(data_b64: str, out_dir: str, label: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{label}-{time.strftime('%H%M%S')}.png")
    with open(path, "wb") as f:
        f.write(base64.b64decode(data_b64))
    return path


def ref_table(refs: dict, max_refs: int) -> str:
    def sort_key(item):
        ref = item[0]
        num = "".join(ch for ch in ref if ch.isdigit())
        return int(num) if num else 0
    lines = []
    for ref, meta in sorted(refs.items(), key=sort_key)[:max_refs]:
        name = (meta.get("name") or "").replace("\n", " ")[:60]
        lines.append(f"  {ref:<6} {meta.get('role', '?'):<12} {name}")
    if len(refs) > max_refs:
        lines.append(f"  ... {len(refs) - max_refs} more (see snapshot JSON)")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Orca browser perception in one call")
    ap.add_argument("--screen", action="store_true", help="whole-screen capture instead of tab")
    ap.add_argument("--both", action="store_true", help="tab AND whole screen")
    ap.add_argument("--net", type=int, metavar="N", help="also show last N captured network requests")
    ap.add_argument("--console", type=int, metavar="N", help="also show last N console entries")
    ap.add_argument("--png-only", action="store_true", help="skip the ref table")
    ap.add_argument("--max-refs", type=int, default=40)
    ap.add_argument("--out", default="/tmp/orca-sight", help="output dir")
    args = ap.parse_args()

    orca = resolve_orca()
    want_tab = not args.screen  # --both gives True for both; --screen only screen
    want_screen = args.screen or args.both
    stamp = time.strftime("%H%M%S")

    if want_tab:
        snap = orca_json(orca, "snapshot")
        refs = snap.get("refs", {}) or {}
        os.makedirs(args.out, exist_ok=True)
        snap_path = os.path.join(args.out, f"tab-{stamp}.json")
        with open(snap_path, "w") as f:
            json.dump(snap, f, indent=1)

        shot = orca_json(orca, "screenshot", "--format", "png")
        png_path = save_png(shot.get("data", ""), args.out, f"tab-{stamp}")

        print(f"TAB PNG: {png_path}")
        print(f"SNAPSHOT JSON: {snap_path}")
        if not args.png_only:
            print(f"ORIGIN: {snap.get('origin', '?')}")
            print(f"REFS ({len(refs)}):")
            print(ref_table(refs, args.max_refs) or "  (no interactive elements)")

    if want_screen:
        os.makedirs(args.out, exist_ok=True)
        path = os.path.join(args.out, f"screen-{stamp}.png")
        r = subprocess.run(["screencapture", "-x", path], capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"sight: screencapture failed: {r.stderr.strip()[:200]}")
        print(f"SCREEN PNG: {path}")

    if args.net:
        net = orca_json(orca, "network", "--limit", str(args.net))
        print(f"NETWORK (last {args.net}):")
        for req in (net.get("requests") or [])[-args.net:]:
            print(f"  {req.get('method', '?'):<6} {req.get('status', '?'):<4} {str(req.get('url', ''))[:110]}")

    if args.console:
        con = orca_json(orca, "console", "--limit", str(args.console))
        print(f"CONSOLE (last {args.console}):")
        for msg in (con.get("messages") or [])[-args.console:]:
            text = str(msg.get("text", msg))[:150].replace("\n", " ")
            print(f"  [{msg.get('level') or 'log'}] {text}")


if __name__ == "__main__":
    main()
