#!/usr/bin/env python3
"""instruction-patch.py — the applier for the correction->instruction queue.

Takes a pending queue entry BY SLUG and applies its suggested_patch (one line)
to the entry's target file. Only entries Josh (or the dissenter weekly path)
has explicitly pre-approved — status: approved in queue.jsonl — will apply.
Pending entries stay pending; that is the default posture.

Records {ts, slug, target, applied, diff_note} to
~/.claude/knowledge/instruction-patches/applied.jsonl and flips the queue
entry's status to applied.

Usage:
  python3 instruction-patch.py --list            # show queue + statuses
  python3 instruction-patch.py --approve <slug>  # Josh-approved: pending -> approved
  python3 instruction-patch.py --apply <slug>    # apply an APPROVED entry only
  python3 instruction-patch.py --reject <slug>   # mark rejected (stays in queue)
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from atomic_io import atomic_append

OUT_DIR = Path.home() / ".claude" / "knowledge" / "instruction-patches"
QUEUE = OUT_DIR / "queue.jsonl"
APPLIED = OUT_DIR / "applied.jsonl"

# Hard allowlist of writable targets: instruction surface only. Anything else
# in a queue entry is refused even if someone flips it to approved.
ALLOWED_TARGETS = {
    Path.home() / ".claude" / "skills" / "airo-mcp-playbook" / "SKILL.md",
    Path.home() / ".claude" / "skills" / "workato-development-playbook" / "SKILL.md",
    Path.home() / ".claude" / "skills" / "workato-skill-builder" / "SKILL.md",
    Path.home() / ".claude" / "skills" / "uat-evidence" / "SKILL.md",
    Path.home() / ".claude" / "skills" / "verify" / "SKILL.md",
    Path.home() / "Documents" / "CLAUDE.md",
}


def load_queue():
    if not QUEUE.exists():
        return []
    rows = []
    for ln in QUEUE.read_text().splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            rows.append(json.loads(ln))
        except json.JSONDecodeError:
            print(f"WARN: skipping malformed queue line: {ln[:80]}")
    return rows


def save_queue(rows):
    QUEUE.parent.mkdir(parents=True, exist_ok=True)
    QUEUE.write_text("".join(json.dumps(r) + "\n" for r in rows))


def find_entry(rows, slug):
    matches = [r for r in rows if r.get("slug") == slug]
    if not matches:
        sys.exit(f"no queue entry with slug '{slug}'")
    return matches[-1]  # latest wins


def cmd_list(rows):
    if not rows:
        print("queue empty")
        return
    for r in rows:
        print(f"{r.get('status', '?'):9} {r.get('slug'):28} -> {r.get('target_file')}")
        print(f"          {r.get('suggested_patch', '')[:140]}")


def cmd_approve(rows, slug):
    e = find_entry(rows, slug)
    if e.get("status") != "pending":
        sys.exit(f"refusing: '{slug}' is '{e.get('status')}', only pending -> approved")
    target = Path(e["target_file"])
    if target not in ALLOWED_TARGETS:
        sys.exit(f"refusing: target {target} is not on the allowlist — edit the miner taxonomy instead")
    e["status"] = "approved"
    e["approved_ts"] = datetime.now(timezone.utc).isoformat()
    save_queue(rows)
    print(f"approved: {slug} -> {e['target_file']} (now run --apply {slug})")


def cmd_reject(rows, slug):
    e = find_entry(rows, slug)
    e["status"] = "rejected"
    e["rejected_ts"] = datetime.now(timezone.utc).isoformat()
    save_queue(rows)
    print(f"rejected: {slug}")


def cmd_apply(rows, slug):
    e = find_entry(rows, slug)
    status = e.get("status")
    if status != "approved":
        sys.exit(
            f"refusing: '{slug}' is status '{status}'. Only Josh-approved entries apply. "
            f"Default posture: pending stays pending. (Approve with --approve {slug} first.)"
        )
    target = Path(e["target_file"])
    if target not in ALLOWED_TARGETS:
        sys.exit(f"refusing: target {target} is not on the allowlist")
    if not target.exists():
        sys.exit(f"refusing: target {target} does not exist")

    patch = e["suggested_patch"].strip()
    before = target.read_text()
    if patch in before:
        sys.exit(f"refusing: '{slug}' patch text already present in {target} — nothing to do")

    append = f"- **Correction patch ({e['ts'][:10]}, slug {slug}):** {patch}\n"
    with target.open("a") as fh:
        fh.write(append)

    diff_note = f"appended 1 line to {target.name} ({len(append)} chars): {patch[:100]}"
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "slug": slug,
        "target": str(target),
        "applied": True,
        "diff_note": diff_note,
    }
    atomic_append(APPLIED, rec)

    e["status"] = "applied"
    e["applied_ts"] = rec["ts"]
    save_queue(rows)
    print(f"applied: {slug}")
    print(f"  {diff_note}")
    print(f"  recorded -> {APPLIED}")

    # wave-3 integration: mirror every applied patch into the genome ledger
    # (best-effort — an application must never fail because of the mirror)
    try:
        import subprocess
        _pg = os.path.join(os.path.dirname(os.path.abspath(__file__)), "patch-genome.py")
        _r = subprocess.run(
            [sys.executable, _pg, "record", "--source", "instruction-patch",
             "--origin-slug", slug, "--target", str(target)],
            check=False, capture_output=True, text=True)
        if _r.returncode == 0:
            print(f"  genome -> {_r.stdout.strip().splitlines()[-1] if _r.stdout.strip() else 'recorded'}")
        else:
            print(f"  genome mirror FAILED (non-fatal): {_r.stderr.strip()[:160]}")
    except Exception as _e:  # noqa: BLE001 — mirror is best-effort by design
        print(f"  genome mirror FAILED (non-fatal): {_e}")


def main():
    args = sys.argv[1:]
    rows = load_queue()
    if not args or args[0] == "--list":
        cmd_list(rows)
        return
    if args[0] == "--approve" and len(args) == 2:
        cmd_approve(rows, args[1])
    elif args[0] == "--reject" and len(args) == 2:
        cmd_reject(rows, args[1])
    elif args[0] == "--apply" and len(args) == 2:
        cmd_apply(rows, args[1])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
