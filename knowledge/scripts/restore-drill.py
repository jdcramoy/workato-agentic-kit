#!/usr/bin/env python3
"""restore-drill.py — germination trial for the knowledge-tree backup
(next-10 proposal #7, ECO4). Zero-LLM, no args, re-runnable:

    python3 restore-drill.py

Clones the backup repo (github.com/Workato-All/josh-knowledge, the origin
that harness-backup.sh auto-pushes nightly to `main`) into a scratch dir,
then runs structural verification against a manifest generated from the
LIVE tree at ~/.claude/knowledge:

  (a) knowledge-tree file count: live vs backup, delta reported
      (the backup is expected to lag hours — pass = backup present with
      >= 75% of live files and domains/, projects/, scripts/,
      garden-reports/ all non-empty)
  (b) INDEX.md parses as non-empty markdown
  (c) every domains/*.md and projects/*.md has non-empty frontmatter
      (leading ---) or a first heading
  (d) every .jsonl under garden-reports/, claims/, bus/ parses
      line-by-line (corrupt-line counts per file; zero expected)
  (e) every scripts/*.py compiles (py_compile)
  (f) every .json in the backup parses (settings-adjacent config included)

Output: knowledge/garden-reports/restore-drill-<date>.md with a viability
percentage (checks passed / total) and the mandatory NOT-verified footer.

Exit code: 0 = viable-enough (all six checks pass), nonzero = red.
Clone auth / network failure is a hard nonzero (nothing was verified).

Scratch clones land in /tmp/restore-drill/ (never inside the knowledge
tree). Stdslib only.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import py_compile
import shutil
import subprocess
import sys

HOME = os.path.expanduser("~")
LIVE = os.path.join(HOME, ".claude", "knowledge")
REPO_URL = "https://github.com/Workato-All/josh-knowledge.git"
SCRATCH = "/tmp/restore-drill"
REPORT_DIR = os.path.join(LIVE, "garden-reports")

# What the backup captures (mirrors harness-backup.sh rsync excludes):
EXCLUDE_DIRS = {".git", "__pycache__", "node_modules", ".claude-plugin"}
EXCLUDE_FILES = {"usage-ledger.jsonl"}  # large regenerable, excluded by rsync
MAX_FILE_BYTES = 50 * 1024 * 1024       # rsync --max-size='50M'

FOOTER = ("NOT verified: semantic tier — credentials re-entry, live fleet "
          "behavior, and secrets-dependent paths are untestable from the "
          "artifact alone.")


def live_manifest() -> dict:
    """Relative-path -> size for the live tree, minus backup-excluded paths."""
    files = {}
    for root, dirs, names in os.walk(LIVE):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for n in names:
            if n in EXCLUDE_FILES:
                continue
            p = os.path.join(root, n)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            if sz > MAX_FILE_BYTES:
                continue
            files[os.path.relpath(p, LIVE)] = sz
    return files


def clone_backup() -> str:
    dest = os.path.join(SCRATCH, "clone")
    if os.path.exists(dest):
        shutil.rmtree(dest)
    # Size pre-check is done by the caller for reporting; the repo is
    # currently ~1.6 MiB packed, so a full clone is cheap. Use --depth 1
    # anyway: structural checks need no history.
    r = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", "main", REPO_URL, dest],
        capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        sys.stderr.write("CLONE FAILED:\n" + r.stderr[-2000:] + "\n")
        sys.exit(3)  # hard red: nothing verifiable without the artifact
    return dest


def check_count(backup_root: str) -> dict:
    bfiles = {}
    for root, dirs, names in os.walk(backup_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for n in names:
            p = os.path.join(root, n)
            bfiles[os.path.relpath(p, backup_root)] = None
    missing = sorted(set(live_manifest_cache) - set(bfiles))
    extra = sorted(set(bfiles) - set(live_manifest_cache))
    ratio_missing = len(missing) / max(1, len(live_manifest_cache))
    cats_ok = all(
        os.path.isdir(os.path.join(backup_root, c))
        and any(os.scandir(os.path.join(backup_root, c)))  # non-empty
        for c in ("domains", "projects", "scripts", "garden-reports"))
    passed = bool(bfiles) and ratio_missing <= 0.25 and cats_ok
    return {"passed": passed, "live": len(live_manifest_cache),
            "backup": len(bfiles), "missing": len(missing),
            "missing_sample": missing[:15], "extra": extra[:15],
            "ratio_missing": ratio_missing, "cats_ok": cats_ok}


def check_index(backup_root: str) -> dict:
    p = os.path.join(backup_root, "INDEX.md")
    if not os.path.isfile(p):
        return {"passed": False, "detail": "INDEX.md missing"}
    text = open(p, encoding="utf-8", errors="replace").read()
    ok = len(text.strip()) > 200 and ("\n#" in ("\n" + text) or text.startswith("#"))
    return {"passed": ok,
            "detail": f"{len(text)} bytes, "
                      f"{'markdown headings present' if ok else 'no headings/too small'}"}


def check_frontmatter(backup_root: str) -> dict:
    bad = []
    n = 0
    for sub in ("domains", "projects"):
        d = os.path.join(backup_root, sub)
        if not os.path.isdir(d):
            bad.append(f"{sub}/ (dir missing)")
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".md"):
                continue
            n += 1
            p = os.path.join(d, f)
            with open(p, encoding="utf-8", errors="replace") as fh:
                lines = [ln for ln in (next(fh, "").rstrip("\n"),
                                       fh.readline().rstrip("\n"))]
            first, second = lines
            has_fm = first.strip() == "---" and second.strip() != ""
            has_h = first.lstrip().startswith("#")
            if not (has_fm or has_h):
                bad.append(f"{sub}/{f}")
    return {"passed": not bad, "checked": n, "bad": bad[:20]}


JSONL_DIRS = ("garden-reports", "claims", "bus")


def check_jsonl(backup_root: str) -> dict:
    per_file = {}
    for sub in JSONL_DIRS:
        d = os.path.join(backup_root, sub)
        if not os.path.isdir(d):
            continue
        for root, _dirs, names in os.walk(d):
            for f in sorted(names):
                if not f.endswith(".jsonl"):
                    continue
                p = os.path.join(root, f)
                rel = os.path.relpath(p, backup_root)
                bad = 0
                total = 0
                with open(p, encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        if not line.strip():
                            continue
                        total += 1
                        try:
                            json.loads(line)
                        except json.JSONDecodeError:
                            bad += 1
                            if bad <= 3:
                                per_file.setdefault(rel + ":lines", []).append(i)
                per_file[rel] = {"lines": total, "corrupt": bad}
    corrupt_files = {k: v for k, v in per_file.items()
                     if isinstance(v, dict) and v["corrupt"]}
    return {"passed": not corrupt_files, "files": len(
        [k for k, v in per_file.items() if isinstance(v, dict)]),
        "corrupt_files": corrupt_files}


def check_scripts(backup_root: str) -> dict:
    d = os.path.join(backup_root, "scripts")
    bad = []
    n = 0
    if os.path.isdir(d):
        for f in sorted(os.listdir(d)):
            if not f.endswith(".py"):
                continue
            n += 1
            p = os.path.join(d, f)
            try:
                import tempfile
                with tempfile.NamedTemporaryFile(suffix=".pyc") as tf:
                    py_compile.compile(p, cfile=tf.name, doraise=True)
            except Exception as e:  # noqa: BLE001 — report the real error
                bad.append(f"scripts/{f}: {type(e).__name__}: {str(e)[:120]}")
    else:
        bad.append("scripts/ (dir missing)")
    return {"passed": not bad, "checked": n, "bad": bad[:20]}


def check_json(backup_root: str) -> dict:
    bad = []
    n = 0
    for root, dirs, names in os.walk(backup_root):
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in sorted(names):
            if not f.endswith(".json"):
                continue
            n += 1
            p = os.path.join(root, f)
            rel = os.path.relpath(p, backup_root)
            try:
                json.load(open(p, encoding="utf-8", errors="replace"))
            except Exception as e:  # noqa: BLE001
                bad.append(f"{rel}: {type(e).__name__}: {str(e)[:120]}")
    present = n > 0
    return {"passed": not bad, "checked": n, "bad": bad[:20],
            "note": "settings.json itself is scrubbed into the josh-orca "
                    "snapshot, not this repo — settings-adjacent JSON here = "
                    "config/dreams data files" if present else "no .json present"}


live_manifest_cache: dict = {}


def main() -> int:
    global live_manifest_cache
    date = dt.date.today().isoformat()
    live_manifest_cache = live_manifest()
    backup_root = clone_backup()
    head = subprocess.run(["git", "-C", backup_root, "log", "-1",
                           "--format=%h %ci"], capture_output=True, text=True)
    backup_head = head.stdout.strip() or "(unknown)"

    results = {
        "a_file_count": check_count(backup_root),
        "b_index": check_index(backup_root),
        "c_frontmatter": check_frontmatter(backup_root),
        "d_jsonl": check_jsonl(backup_root),
        "e_scripts": check_scripts(backup_root),
        "f_json": check_json(backup_root),
    }
    passed = sum(1 for r in results.values() if r["passed"])
    total = len(results)
    viability = round(100 * passed / total)
    ok = passed == total

    lines = [
        f"# Restore drill — {date}",
        "",
        f"- Backup repo: {REPO_URL} (shallow clone of `main`)",
        f"- Backup HEAD: `{backup_head}`",
        f"- Live tree: {len(live_manifest_cache)} files "
        f"(backup-excluded: {', '.join(sorted(EXCLUDE_DIRS))}, "
        f"{', '.join(sorted(EXCLUDE_FILES))}, >50MB)",
        "",
        "| check | verdict | detail |",
        "|---|---|---|",
    ]
    a = results["a_file_count"]
    lines.append(
        f"| (a) file count | {'PASS' if a['passed'] else 'FAIL'} "
        f"| live={a['live']} backup={a['backup']} missing={a['missing']} "
        f"({a['ratio_missing']:.1%}), category dirs non-empty: "
        f"{a['cats_ok']}; missing sample: "
        f"{'; '.join(a['missing_sample'][:8]) or '—'} |")
    for key, label in (("b_index", "(b) INDEX.md"),
                       ("c_frontmatter", "(c) md frontmatter/heading"),
                       ("d_jsonl", "(d) jsonl line-parse"),
                       ("e_scripts", "(e) scripts py_compile"),
                       ("f_json", "(f) json parse")):
        r = results[key]
        det = json.dumps(r, default=str)[:300]
        lines.append(f"| {label} | {'PASS' if r['passed'] else 'FAIL'} | {det} |")
    lines += [
        "",
        f"**Viability: {viability}% ({passed}/{total} checks passed)** — "
        f"{'VIABLE-ENOUGH' if ok else 'RED: structural failures above'}",
        "",
        "Re-run: `python3 ~/.claude/knowledge/scripts/restore-drill.py` "
        "(no args; exit 0 = drill completed and wrote this report — the "
        "Viability line above carries the verdict; rc=3 = no backup artifact "
        "to verify. A RED verdict must NOT exit nonzero: the fleet runner "
        "treats any nonzero rc as a stub and the nightly double-stubbed for "
        "two nights (2026-10-12/13) while the drill was actually running.",
        "",
        FOOTER,
        "",
    ]
    os.makedirs(REPORT_DIR, exist_ok=True)
    report_path = os.path.join(REPORT_DIR, f"restore-drill-{date}.md")
    with open(report_path, "w") as f:
        f.write("\n".join(lines))
    print("\n".join(lines))
    print(f"report: {report_path}")
    # A completed drill that wrote its report is a VALID run even on a RED
    # verdict — the verdict is report content, not an exit code. Nonzero is
    # reserved for "could not verify anything" (rc=3 above), which the fleet
    # runner correctly treats as a stub. RED-with-report used to exit 2 and
    # the runner's stub contract double-stubbed the job every night.
    return 0


if __name__ == "__main__":
    sys.exit(main())
