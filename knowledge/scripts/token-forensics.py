#!/usr/bin/env python3
"""token-forensics.py — per-tool/turn-type token burn + turn-efficiency analysis
over Claude Code session transcripts (~/.claude/projects/*/*.jsonl).

Measures:
  A. Per tool: calls, errors, result context injected (bytes/est tokens), assistant
     output tokens attributed to the turn that invoked it.
  B. Per wt subcommand: same + blind-retry count (identical command repeated).
  C. KB discipline: after a failed tool call, was the next action a KB consult, a
     blind retry, or neither?

Usage:
  token-forensics.py [--days N] [--project DIR-Substring] [--top N] [--json OUT]

Notes: cache_read_input_tokens = context footprint (what the turn re-reads);
       output_tokens = generation cost. est tokens = bytes/4, heuristic.
"""
import argparse, collections, glob, json, os, sys, time

PROJECTS = os.path.expanduser("~/.claude/projects")


def result_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def first_arg_sig(cmd):
    """Normalize a shell command to 'prog subarg' for grouping (wt manifests x -> wt manifests)."""
    parts = cmd.strip().split()
    if not parts:
        return cmd
    prog = parts[0]
    sub = parts[1] if len(parts) > 1 and not parts[1].startswith("-") else ""
    return f"{prog} {sub}".strip()


def scan_file(path):
    """Yield events for one session file."""
    tool_calls = {}   # id -> {"name","input","output_tokens","ts"}
    events = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                t = d.get("type")
                ts = d.get("timestamp", "")
                if t == "assistant":
                    m = d.get("message", {})
                    usage = m.get("usage") or {}
                    out = usage.get("output_tokens", 0) or 0
                    inp = usage.get("input_tokens", 0) or 0
                    cr = usage.get("cache_read_input_tokens", 0) or 0
                    cc = usage.get("cache_creation_input_tokens", 0) or 0
                    for b in m.get("content", []):
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            tool_calls[b.get("id")] = {
                                "name": b.get("name", "?"),
                                "input": b.get("input", {}),
                                "output_tokens": out,
                                "in_footprint": cr + cc + inp,
                            }
                elif t == "user":
                    c = d.get("message", {}).get("content", [])
                    if isinstance(c, list):
                        for b in c:
                            if isinstance(b, dict) and b.get("type") == "tool_result":
                                tc = tool_calls.get(b.get("tool_use_id"))
                                if tc:
                                    events.append({
                                        "name": tc["name"],
                                        "input": tc["input"],
                                        "output_tokens": tc["output_tokens"],
                                        "in_footprint": tc["in_footprint"],
                                        "result_bytes": len(result_text(b.get("content"))),
                                        "is_error": bool(b.get("is_error")),
                                        "ts": ts,
                                    })
    except OSError:
        return []
    return events


def kb_probe(name, inp):
    if name.startswith("mcp__workato-kb__"):
        return True
    if name == "Bash":
        cmd = (inp or {}).get("command", "")
        return cmd.strip().startswith(("kb ", "kb\n", "/kb"))
    return False


def wt_sig(inp):
    cmd = (inp or {}).get("command", "")
    if not cmd.strip().startswith("wt"):
        return None
    return first_arg_sig(cmd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--project", default=None, help="substring filter on project dir name")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()

    cutoff = time.time() - args.days * 86400
    files = glob.glob(os.path.join(PROJECTS, "*", "*.jsonl"))
    files = [f for f in files if os.path.getmtime(f) >= cutoff]
    if args.project:
        files = [f for f in files if args.project in f]

    per_tool = collections.defaultdict(lambda: collections.Counter())
    per_wt = collections.defaultdict(lambda: collections.Counter())
    kb_after_fail = collections.Counter()  # kb | retry | neither
    blind_retries = collections.Counter()  # wt sub -> count of identical-command repeats
    sessions = 0

    for f in files:
        events = scan_file(f)
        if not events:
            continue
        sessions += 1
        seen_cmds = collections.Counter()
        for i, ev in enumerate(events):
            sig = first_arg_sig(ev["name"])
            key = ev["name"]
            per_tool[key]["calls"] += 1
            per_tool[key]["out_toks"] += ev["output_tokens"]
            per_tool[key]["in_footprint"] += ev["in_footprint"]
            per_tool[key]["result_bytes"] += ev["result_bytes"]
            per_tool[key]["result_toks_est"] += ev["result_bytes"] // 4
            if ev["is_error"]:
                per_tool[key]["errors"] += 1
            # wt subcommand view
            ws = wt_sig(ev["input"])
            if ws:
                per_wt[ws]["calls"] += 1
                per_wt[ws]["out_toks"] += ev["output_tokens"]
                per_wt[ws]["result_toks_est"] += ev["result_bytes"] // 4
                if ev["is_error"]:
                    per_wt[ws]["errors"] += 1
                norm = " ".join((ev["input"] or {}).get("command", "").split())
                seen_cmds[norm] += 1
                if seen_cmds[norm] == 2:
                    blind_retries[ws] += 1
            # KB discipline after a failed call
            if ev["is_error"]:
                nxt = [e for e in events[i + 1:i + 4]]
                if any(kb_probe(e["name"], e["input"]) for e in nxt):
                    kb_after_fail["kb"] += 1
                elif any(first_arg_sig(e["name"]) == sig and
                         (e["input"] or {}).get("command", "") == (ev["input"] or {}).get("command", "")
                         for e in nxt):
                    kb_after_fail["retry"] += 1
                else:
                    kb_after_fail["neither"] += 1

    print(f"sessions scanned: {sessions} ({args.days}d window, project={args.project or 'all'})")
    print(f"failed-call follow-up: kb-consult={kb_after_fail['kb']}  blind-retry={kb_after_fail['retry']}  neither={kb_after_fail['neither']}")
    print()
    hdr = f"{'tool':<42}{'calls':>7}{'err%':>6}{'out_toks':>10}{'result_est':>12}{'in_footprint':>14}"
    print("=== per-tool burn ===")
    print(hdr)
    rows = sorted(per_tool.items(), key=lambda kv: -(kv[1]["out_toks"] + kv[1]["result_toks_est"]))
    for name, c in rows[:args.top]:
        errp = 100 * c["errors"] / c["calls"] if c["calls"] else 0
        fp = c["in_footprint"] // c["calls"] if c["calls"] else 0
        print(f"{name:<42}{c['calls']:>7}{errp:>5.0f}%{c['out_toks']:>10,}{c['result_toks_est']:>12,}{fp:>14,}")
    if per_wt:
        print()
        print("=== wt subcommands ===")
        print(f"{'wt sub':<24}{'calls':>7}{'err%':>6}{'out_toks':>10}{'result_est':>12}{'dup-retries':>12}")
        for name, c in sorted(per_wt.items(), key=lambda kv: -kv[1]["calls"])[:args.top]:
            errp = 100 * c["errors"] / c["calls"] if c["calls"] else 0
            print(f"{name:<24}{c['calls']:>7}{errp:>5.0f}%{c['out_toks']:>10,}{c['result_toks_est']:>12,}{blind_retries.get(name,0):>12}")
    if args.json_out:
        out = {
            "per_tool": {k: dict(v) for k, v in per_tool.items()},
            "per_wt": {k: dict(v) for k, v in per_wt.items()},
            "kb_after_fail": dict(kb_after_fail),
        }
        with open(args.json_out, "w") as fh:
            json.dump(out, fh, indent=1)
        print(f"\njson -> {args.json_out}")


if __name__ == "__main__":
    main()
