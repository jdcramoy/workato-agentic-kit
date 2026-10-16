#!/usr/bin/env python3
"""fleet-cost.py — fleet job cost attribution + budget preflight (P1 PRICEBOOK).

Built 2026-10-13 per estate-fusion-audit-2026-10-13.md "P1 PRICEBOOK". Zero-LLM,
pure stdlib, macOS system python (no datetime.UTC).

What it does:
  1. Walks session transcripts under ~/.claude/projects/*/*.jsonl (READ-ONLY),
     parsing per-turn usage fields (pattern cribbed from turn-audit.py) and the
     gateway cost records. Cost fields were DISCOVERED empirically 2026-10-13:
     Claude Code v2 writes `{"type":"cost-state","totalCostUSD":...,
     "modelUsage":{model:{"costUSD":...,"inputTokens":...}}}` records; sessions
     older than ~2026-10-12 have none. Rows without cost still record token
     counts (cost_usd: null) — presence and absence handled honestly.
  2. ATTRIBUTION: a session's first real user message, whitespace-normalized,
     must match the first 60 chars of some ~/.claude/knowledge/config/fleet/
     jobs/<name>.prompt. Sessions matching no job prompt are not fleet sessions.
  3. Modes:
       --report             per-job trailing-7d stats to stdout + one ledger row
                            per session appended to knowledge/reports/
                            fleet-cost.jsonl (schema {"ts","job","session_id",
                            "in_tokens","out_tokens","cost_usd"}), idempotent by
                            (session_id, job) — never double-appends.
       --preflight <job> --cap <usd>
                            exit 0 if under cap / cap absent / no cost data /
                            ANY internal error (fail-open — a bug here must
                            never break a fleet job); exit 7 if the job's
                            trailing-7d median known cost_usd EXCEEDS cap
                            (the run-job.sh skip signal).

in_tokens = input_tokens + cache_read + cache_creation summed across ALL
assistant turns INCLUDING sidechains (sidechain spend is real spend in this
session; costUSD totals the same scope). out_tokens = output_tokens only.
"""
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

HOME = Path.home()
PROJECTS = HOME / ".claude" / "projects"
JOBS_DIR = HOME / ".claude" / "knowledge" / "config" / "fleet" / "jobs"
LEDGER = HOME / ".claude" / "knowledge" / "reports" / "fleet-cost.jsonl"
SCRIPTS = HOME / ".claude" / "knowledge" / "scripts"

PREFIX_LEN = 60
MTOK = 1_000_000.0


def log(msg):
    sys.stderr.write(f"fleet-cost: {msg}\n")


def utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def norm(s):
    """Whitespace-collapse — prompt files may carry trailing newlines the -p
    arg keeps, and the transcript's first user message is that exact string."""
    return " ".join(str(s).split())


def load_job_prefixes():
    """{job_name: normalized 60-char prefix} from jobs/*.prompt."""
    jobs = {}
    for f in glob.glob(str(JOBS_DIR / "*.prompt")):
        try:
            txt = Path(f).read_text(errors="replace")
        except Exception:
            continue
        name = os.path.basename(f)[: -len(".prompt")]
        prefix = norm(txt)[:PREFIX_LEN]
        if prefix:
            jobs[name] = prefix
    return jobs


def first_user_message(lines_iter):
    """First real user message text (string content, or first text block), or
    None. Tool-result user records are skipped. No isSidechain filter needed
    for -p sessions but applied for correctness anyway."""
    for l in lines_iter:
        if '"type"' not in l or '"user"' not in l:
            continue
        try:
            d = json.loads(l)
        except Exception:
            continue
        if d.get("type") != "user" or d.get("isSidechain"):
            continue
        c = (d.get("message") or {}).get("content")
        if isinstance(c, str) and c.strip():
            return c
        if isinstance(c, list):
            for item in c:
                if isinstance(item, dict) and item.get("type") == "text" \
                        and str(item.get("text", "")).strip():
                    return item["text"]
    return None


def scan_session(f):
    """Parse one transcript file. Returns dict or None on empty/unreadable.
    Per-file try/except: a corrupt transcript must never kill the scan."""
    sid = os.path.basename(f)[: -len(".jsonl")]
    in_tok = 0
    out_tok = 0
    cost_usd = None          # last cost-state totalCostUSD wins (cumulative)
    model_usage = {}         # last cost-state modelUsage (for rate sampling)
    has_cost = False
    last_ts = None
    ts_re = re.compile(r'"timestamp":"([^"]+)"')
    try:
        with open(f, errors="replace") as fh:
            lines = fh
            fu = first_user_message(lines)
            fh.seek(0)
            for l in fh:
                if '"timestamp"' in l[:160] or '"timestamp":"' in l:
                    m = ts_re.search(l)
                    if m:
                        last_ts = m.group(1)
                if '"cost-state"' in l:
                    try:
                        d = json.loads(l)
                    except Exception:
                        d = None
                    if d and d.get("type") == "cost-state":
                        c = d.get("totalCostUSD")
                        if isinstance(c, (int, float)):
                            cost_usd = float(c)
                            has_cost = True
                        mu = d.get("modelUsage")
                        if isinstance(mu, dict) and mu:
                            model_usage = mu
                elif '"usage"' in l and '"assistant"' in l:
                    try:
                        d = json.loads(l)
                    except Exception:
                        d = None
                    if d and d.get("type") == "assistant":
                        u = (d.get("message") or {}).get("usage") or {}
                        if isinstance(u, dict):
                            in_tok += (u.get("input_tokens") or 0) + \
                                      (u.get("cache_read_input_tokens") or 0) + \
                                      (u.get("cache_creation_input_tokens") or 0)
                            out_tok += u.get("output_tokens") or 0
    except Exception as e:
        log(f"skip {os.path.basename(f)[:20]}: {e}")
        return None
    if fu is None and in_tok == 0 and not has_cost:
        return None
    return {
        "file": f, "session_id": sid, "first_user": fu or "",
        "in_tokens": in_tok, "out_tokens": out_tok,
        "cost_usd": cost_usd, "has_cost": has_cost,
        "model_usage": model_usage, "end_ts": last_ts,
    }


def parse_ts(ts):
    """ISO ts -> epoch seconds; None if unparsable (caller keeps the row rather
    than dropping it — unparsable stays in scope)."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def scan_all(days):
    """All parseable sessions whose file mtime is within days+1d (session END
    ts is the real filter, applied by callers; mtime pre-filter is a perf
    bound only)."""
    cutoff = datetime.now(timezone.utc).timestamp() - (days + 1) * 86400
    out = []
    for f in glob.glob(str(PROJECTS / "*" / "*.jsonl")):
        try:
            if os.path.getmtime(f) < cutoff:
                continue
        except Exception:
            continue
        s = scan_session(f)
        if s:
            out.append(s)
    return out


def attribute(sessions, days, now=None):
    """Filter to trailing-`days` fleet sessions with job attribution.
    now = epoch seconds (injected for tests)."""
    jobs = load_job_prefixes()
    now = now or datetime.now(timezone.utc).timestamp()
    rows = []
    for s in sessions:
        end = parse_ts(s["end_ts"])
        if end is not None and (now - end) > days * 86400:
            continue
        fu = norm(s["first_user"])[:PREFIX_LEN]
        if not fu:
            continue
        job = None
        for name, prefix in jobs.items():
            if fu == prefix or fu.startswith(prefix):
                job = name
                break
        if job is None:
            continue   # not a fleet session
        s["job"] = job
        rows.append(s)
    return rows


def median(vals):
    v = sorted(vals)
    n = len(v)
    if not n:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def ledger_existing():
    """Set of (session_id, job) already in the ledger — idempotency guard."""
    seen = set()
    try:
        with open(LEDGER, errors="replace") as fh:
            for l in fh:
                try:
                    r = json.loads(l)
                except Exception:
                    continue
                seen.add((str(r.get("session_id")), str(r.get("job"))))
    except FileNotFoundError:
        pass
    except Exception as e:
        log(f"ledger read failed (will still append, fail-open): {e}")
    return seen


def append_ledger(rows):
    """Append via atomic_io (shared-ledger safe); returns count written."""
    sys.path.insert(0, str(SCRIPTS))
    from atomic_io import atomic_append
    seen = ledger_existing()
    n = 0
    batch = []
    for s in rows:
        key = (str(s["session_id"]), str(s["job"]))
        if key in seen:
            continue
        seen.add(key)
        batch.append({
            "ts": s["end_ts"] or utcnow_iso(),
            "job": s["job"],
            "session_id": s["session_id"],
            "in_tokens": s["in_tokens"],
            "out_tokens": s["out_tokens"],
            "cost_usd": round(s["cost_usd"], 6) if s["has_cost"] else None,
        })
        n += 1
    if batch:
        atomic_append(str(LEDGER), batch)
    return n


def cmd_report(args):
    """Fail-open: prints what it can, always exits 0."""
    try:
        now = datetime.now(timezone.utc).timestamp()
        sessions = scan_all(args.days)
        fleet = attribute(sessions, args.days, now=now)
        written = append_ledger(fleet)
        by_job = {}
        for s in fleet:
            by_job.setdefault(s["job"], []).append(s)
        print(f"fleet-cost report — trailing {args.days}d "
              f"({len(fleet)} fleet sessions attributed of {len(sessions)} "
              f"parsed; ledger rows appended: {written}; "
              f"costUSD present in {sum(1 for s in fleet if s['has_cost'])})")
        print(f"{'job':<16} {'n':>4} {'in_tok_total':>14} {'in_tok_med':>12} "
              f"{'cost_total':>10} {'cost_med':>9} {'n_costed':>8}")
        for job in sorted(by_job):
            ss = by_job[job]
            costs = [s["cost_usd"] for s in ss if s["has_cost"]]
            ins = [s["in_tokens"] for s in ss] or [0]
            ct = f"{sum(costs):.4f}" if costs else "n/a"
            cm = f"{median(costs):.4f}" if costs else "n/a"
            print(f"{job:<16} {len(ss):>4} {sum(ins):>14,} {median(ins):>12,.0f} "
                  f"{ct:>10} {cm:>9} {len(costs):>8}")
        return 0
    except Exception as e:
        log(f"report failed (fail-open): {e}")
        return 0


def cmd_preflight(args):
    """exit 7 only when the job's trailing-7d median KNOWN cost exceeds cap;
    everything else (no cap data, no sessions, no cost fields, any error)
    exits 0 — fail-open."""
    try:
        cap = float(args.cap)
    except Exception:
        log(f"unparsable cap {args.cap!r} — fail-open")
        return 0
    try:
        now = datetime.now(timezone.utc).timestamp()
        sessions = scan_all(args.days)
        job = args.preflight
        fleet = [s for s in attribute(sessions, args.days, now=now)
                 if s["job"] == job]
        costs = [s["cost_usd"] for s in fleet if s["has_cost"]]
        if not costs:
            log(f"{job}: {len(fleet)} sessions, none with costUSD — "
                f"fail-open (nothing known to be over cap)")
            return 0
        med = median(costs)
        log(f"{job}: {len(fleet)} sessions trailing {args.days}d, "
            f"{len(costs)} costed, median ${med:.4f} vs cap ${cap:.4f}")
        if med > cap:
            return 7
        return 0
    except Exception as e:
        log(f"preflight failed (fail-open): {e}")
        return 0


def main():
    import argparse
    ap = argparse.ArgumentParser(description="fleet cost attribution + preflight")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--preflight", metavar="JOB")
    ap.add_argument("--cap", metavar="USD")
    ap.add_argument("--days", type=int, default=7)
    a = ap.parse_args()
    if a.report:
        return cmd_report(a)
    if a.preflight:
        if a.cap is None:
            log("no --cap given — fail-open")
            return 0
        return cmd_preflight(a)
    ap.print_usage()
    return 2


if __name__ == "__main__":
    sys.exit(main())
