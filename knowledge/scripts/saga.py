#!/usr/bin/env python3
"""saga.py — resumable hash-chained mission journals.

A saga is an append-only JSONL journal at knowledge/sagas/<mission_id>.jsonl.
Every step is hash-chained: step_hash = sha256(prev_hash + canonical step
payload). Tampering with any line breaks every hash after it, and `resume`
/`verify` catch it.

Fingerprints ({"git_sha","queues","clock"} or caller-supplied) are recorded at
`start` and recomputed at `resume`. A fingerprint mismatch does NOT resume:
the world moved under the mission — re-plan, do not blind-resume.

Usage:
  saga.py start <mission_id> [--fingerprint '{"git_sha":"...","queues":N,"clock":"YYYY-MM-DD"}']
  saga.py step  <mission_id> --action "..." --state-in '<json>' --state-out '<json>'
                [--compensation '{"action":"...","params":{...}}']
  saga.py resume <mission_id>
  saga.py verify <mission_id>
  saga.py list

Exit codes: 0 ok, 1 chain broken / fingerprint mismatch / usage error.
"""
import argparse, hashlib, json, os, subprocess, sys, time

SAGAS_DIR = os.path.join(os.path.expanduser("~/.claude/knowledge"), "sagas")
INBOX = os.path.join(os.path.expanduser("~/.claude/knowledge/now/decision-inbox.json"))
KNOWLEDGE = os.path.expanduser("~/.claude/knowledge")
GENESIS = "MISSION_START"
ZERO_HASH = "0" * 64


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def now_ts():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def journal_path(mission_id):
    if not mission_id or "/" in mission_id or mission_id.startswith("."):
        sys.exit("invalid mission_id")
    return os.path.join(SAGAS_DIR, mission_id + ".jsonl")


def read_lines(path):
    with open(path) as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    steps = []
    for i, ln in enumerate(lines, 1):
        try:
            steps.append(json.loads(ln))
        except json.JSONDecodeError as e:
            sys.exit(f"CHAIN BROKEN: line {i} is not valid JSON ({e})")
    return steps


def step_hash(prev_hash, step):
    payload = {k: step[k] for k in ("seq", "ts", "action", "state_in", "state_out", "compensation")}
    return hashlib.sha256((prev_hash + canonical(payload)).encode()).hexdigest()


def default_fingerprint():
    fp = {"git_sha": "unknown", "queues": None, "clock": time.strftime("%Y-%m-%d", time.gmtime())}
    try:
        fp["git_sha"] = subprocess.run(
            ["git", "-C", KNOWLEDGE, "rev-parse", "HEAD"], capture_output=True, text=True,
            timeout=10).stdout.strip() or "unknown"
    except Exception:
        pass
    try:
        with open(INBOX) as f:
            inbox = json.load(f)
        fp["queues"] = len(inbox.get("today", [])) + inbox.get("deferred_count",
                       len(inbox.get("deferred", [])))
    except Exception:
        pass
    return fp


def append(path, step):
    with open(path, "a") as f:
        f.write(json.dumps(step) + "\n")


def load_fp(arg):
    if not arg:
        return default_fingerprint()
    try:
        fp = json.loads(arg)
    except json.JSONDecodeError as e:
        sys.exit(f"--fingerprint is not valid JSON: {e}")
    if not isinstance(fp, dict):
        sys.exit("--fingerprint must be a JSON object")
    return fp


def parse_state(raw, flag):
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        sys.exit(f"--{flag} is not valid JSON: {e}")


def chain_status(steps):
    """Recompute the whole chain. Returns list of problems (empty = intact)."""
    problems = []
    prev = ZERO_HASH
    for i, s in enumerate(steps, 1):
        if s.get("prev_hash") != prev:
            problems.append(f"line {i}: prev_hash != previous step_hash (chain splice)")
        want = step_hash(s.get("prev_hash", prev), s)
        if s.get("step_hash") != want:
            problems.append(f"line {i}: step_hash mismatch (content altered)")
        prev = s.get("step_hash", prev)
    return problems


def cmd_start(a):
    path = journal_path(a.mission_id)
    os.makedirs(SAGAS_DIR, exist_ok=True)
    if os.path.exists(path):
        sys.exit(f"saga '{a.mission_id}' already exists: {path}")
    fp = load_fp(a.fingerprint)
    genesis = {"seq": 0, "ts": now_ts(), "prev_hash": ZERO_HASH, "step_hash": None,
               "action": GENESIS, "state_in": None, "state_out": fp, "compensation": None}
    genesis["step_hash"] = step_hash(ZERO_HASH, genesis)
    append(path, genesis)
    print(f"saga started: {path}")
    print(f"  fingerprint: {canonical(fp)}")
    print(f"  genesis hash: {genesis['step_hash'][:16]}...")
    print("next: saga.py step %s --action ... --state-in ... --state-out ..." % a.mission_id)


def cmd_step(a):
    path = journal_path(a.mission_id)
    if not os.path.exists(path):
        sys.exit(f"no saga '{a.mission_id}' — run: saga.py start {a.mission_id}")
    steps = read_lines(path)
    problems = chain_status(steps)
    if problems:
        print("CHAIN BROKEN — refusing to append to a corrupt journal:")
        for p in problems:
            print("  " + p)
        sys.exit(1)
    last = steps[-1]
    step = {"seq": last["seq"] + 1, "ts": now_ts(), "prev_hash": last["step_hash"],
            "step_hash": None, "action": a.action,
            "state_in": parse_state(a.state_in, "state-in"),
            "state_out": parse_state(a.state_out, "state-out"),
            "compensation": parse_state(a.compensation, "compensation")}
    step["step_hash"] = step_hash(last["step_hash"], step)
    append(path, step)
    print(f"step {step['seq']} appended to {a.mission_id}")
    print(f"  state_out: {canonical(step['state_out'])}")
    print(f"  step_hash: {step['step_hash'][:16]}...")


def cmd_resume(a):
    path = journal_path(a.mission_id)
    if not os.path.exists(path):
        sys.exit(f"no saga '{a.mission_id}'")
    steps = read_lines(path)
    problems = chain_status(steps)
    if problems:
        print("CHAIN BROKEN — journal integrity failed, do not resume:")
        for p in problems:
            print("  " + p)
        sys.exit(1)
    last = steps[-1]
    print(f"saga '{a.mission_id}': chain intact ({len(steps)} entries, through seq {last['seq']})")
    print(f"last state_out: {canonical(last['state_out'])}")
    stored_fp = None
    for s in steps:
        if s.get("action") == GENESIS:
            stored_fp = s.get("state_out")
            break
    current_fp = load_fp(a.fingerprint) if a.fingerprint else default_fingerprint()
    print(f"current fingerprint: {canonical(current_fp)}")
    if stored_fp is not None:
        shared = [k for k in stored_fp if k in current_fp]
        diffs = [(k, stored_fp[k], current_fp[k]) for k in shared if stored_fp[k] != current_fp[k]]
        if diffs:
            print("WORLD CHANGED — re-plan, do not blind-resume")
            for k, old, new in diffs:
                print(f"  {k}: was {old!r}, now {new!r}")
            sys.exit(1)
        if not shared:
            print("note: stored and current fingerprints share no keys — comparability unknown")
    if last.get("compensation"):
        print(f"pending compensation from last step: {canonical(last['compensation'])}")
    print("resume point: replay state_out above; next seq = %d" % (last["seq"] + 1))


def cmd_verify(a):
    path = journal_path(a.mission_id)
    if not os.path.exists(path):
        sys.exit(f"no saga '{a.mission_id}'")
    steps = read_lines(path)
    problems = chain_status(steps)
    if problems:
        print(f"CHAIN BROKEN ({len(problems)} problem(s) in {len(steps)} entries):")
        for p in problems:
            print("  " + p)
        sys.exit(1)
    print(f"OK: {a.mission_id} — {len(steps)} entries, chain intact")


def cmd_list(_a):
    os.makedirs(SAGAS_DIR, exist_ok=True)
    files = sorted(f for f in os.listdir(SAGAS_DIR) if f.endswith(".jsonl"))
    if not files:
        print("no sagas yet — start one with: saga.py start <mission_id>")
        return
    for fn in files:
        mid = fn[:-6]
        try:
            steps = read_lines(os.path.join(SAGAS_DIR, fn))
        except SystemExit:
            print(f"{mid}: UNREADABLE")
            continue
        problems = chain_status(steps)
        status = "intact" if not problems else f"CHAIN BROKEN ({len(problems)})"
        last = steps[-1] if steps else {}
        print(f"{mid}: {len(steps)} entries, last seq {last.get('seq')}, "
              f"{last.get('ts', '?')}, {status}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("start", help="start a new mission journal")
    p.add_argument("mission_id")
    p.add_argument("--fingerprint", help='JSON fingerprint, e.g. {"git_sha":"...","queues":N,"clock":"YYYY-MM-DD"} (default: computed)')
    p.set_defaults(fn=cmd_start)

    p = sub.add_parser("step", help="append one hash-chained step")
    p.add_argument("mission_id")
    p.add_argument("--action", required=True)
    p.add_argument("--state-in", required=True)
    p.add_argument("--state-out", required=True)
    p.add_argument("--compensation", help='JSON {"action":...,"params":...} for rollback')
    p.set_defaults(fn=cmd_step)

    p = sub.add_parser("resume", help="verify chain + fingerprint, print resume point")
    p.add_argument("mission_id")
    p.add_argument("--fingerprint", help="override current fingerprint computation")
    p.set_defaults(fn=cmd_resume)

    p = sub.add_parser("verify", help="recompute the full hash chain")
    p.add_argument("mission_id")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("list", help="list all sagas")
    p.set_defaults(fn=cmd_list)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
