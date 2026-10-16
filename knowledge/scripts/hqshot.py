#!/usr/bin/env python3
"""hqshot.py — high-quality visual capture of an Orca browser tab for QA.

Visual QA of rendered decks/docs/HTML: open the target, optionally zoom for
fine text, capture, report pixel dims. Screenshots land in /tmp/orca-sight/
(Read them to SEE the page).

Usage:
  hqshot.py <url-or-file-path>            # capture at native res
  hqshot.py <url-or-file-path> --zoom 150 # zoom page to 150% first (fine text)
  hqshot.py <url-or-file-path> --full     # full-page (beyond viewport)
  hqshot.py --qa <file.html>              # deck preset: 1280x720 canvas,
                                          # 2x logical zoom, full capture
Notes: orca viewport --scale 2 TILES the capture (trap, 2026-10-15) — zoom via
CSS instead of deviceScaleFactor. file:// paths render locally with no server.
"""
import base64, json, struct, subprocess, sys, os, datetime, argparse

ORCA = "/Applications/Orca.app/Contents/Resources/bin/orca"
OUTDIR = "/tmp/orca-sight"

def orca(*args):
    r = subprocess.run([ORCA, *args, "--json"], capture_output=True, text=True)
    try:
        return json.loads(r.stdout or "{}")
    except json.JSONDecodeError:
        return {"ok": False, "error": r.stdout[:200] + r.stderr[:200]}

def to_file_url(p):
    if p.startswith(("http://", "https://", "file://")):
        return p
    return "file://" + os.path.abspath(p)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?")
    ap.add_argument("--zoom", type=int, default=100)
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--qa", action="store_true",
                    help="deck preset: zoom 200 on a 1280x720 canvas")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=940)
    a = ap.parse_args()
    if not a.target:
        print(__doc__); sys.exit(1)

    url = to_file_url(a.target)
    zoom = 200 if a.qa else a.zoom
    os.makedirs(OUTDIR, exist_ok=True)

    nav = orca("goto", "--url", url)
    if not nav.get("ok"):
        print("goto FAILED:", json.dumps(nav)[:200]); sys.exit(1)
    orca("wait", "--load", "complete", "--timeout", "20000")
    import time; time.sleep(2)  # SPA render settle

    if zoom != 100:
        orca("eval", "--expression",
             f"document.body.style.zoom = '{zoom}%'")
        time.sleep(1)

    cap = "full-screenshot" if a.full else "screenshot"
    shot = orca(cap, "--format", "png")
    if not shot.get("ok"):
        print(f"{cap} FAILED:", json.dumps(shot)[:200]); sys.exit(1)
    data = base64.b64decode(shot["result"]["data"])
    w, h = struct.unpack(">II", data[16:24])
    slug = "".join(c if c.isalnum() else "-" for c in os.path.basename(a.target))[:40]
    path = f"{OUTDIR}/{datetime.datetime.now():%H%M%S}-{slug}.png"
    with open(path, "wb") as f:
        f.write(data)
    print(f"PNG {path}  ({w}x{h}px, zoom {zoom}%, {'full-page' if a.full else 'viewport'})")
    # restore zoom so the tab is left clean
    if zoom != 100:
        orca("eval", "--expression", "document.body.style.zoom = ''")

if __name__ == "__main__":
    main()
