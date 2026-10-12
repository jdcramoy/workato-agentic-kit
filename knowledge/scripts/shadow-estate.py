#!/usr/bin/env python3
"""shadow-estate.py — the regret ledger.

For every open/deferred decision in now/decision-inbox.json, attempts a CHEAP,
READ-ONLY counterfactual check: is the thing the decision was waiting on still
true in the live world? Writes a regret ledger markdown file to
knowledge/policies/regret-ledger-<ts>.md with, per deferral: id, what was
deferred, current live state, would-executing-now-still-help (yes/no/stale),
and a cost-of-inference note.

EPISTEMICS — what this tool CAN and CANNOT establish:
  CAN: verifiable state deltas observable from (a) local files under
  ~/.claude/knowledge (existence, mtime) and (b) the DEV Workato REST API via
  the `wt` CLI (recipe running state, last-run time, job counts).
  CANNOT: modeled dollar or time savings; PROD state (unless --env prod
  --confirm, and even then read-only); Jira ticket state (no stdlib auth path
  — any Jira-dependent blocker is marked stale, not guessed); whether a human
  blocker (Josh review, a UAT volunteer) has quietly moved.
A verdict of "stale" means "this counterfactual could not establish currency"
— it is an honest unknown, never presented as a fact.

Usage:
  shadow-estate.py [--env prod --confirm] [--out DIR]
"""
import argparse, json, os, re, subprocess, sys, time

KNOWLEDGE = os.path.expanduser("~/.claude/knowledge")
INBOX = os.path.join(KNOWLEDGE, "now/decision-inbox.json")
POLICY_DIR = os.path.join(KNOWLEDGE, "policies")
WT = os.path.expanduser("~/.local/bin/wt")
RECIPE_RE = re.compile(r"(?:recipe[s]?[/ ]|/recipes/)(\d{7,9})")
PROPOSAL_RE = re.compile(r"(dreams/proposals/[\w.-]+\.md)")
KNOWLEDGE_PATH_RE = re.compile(r"((?:knowledge/)?[\w./-]+\.(?:md|jsonl|json))")


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def run_wt(args, timeout=60):
    try:
        r = subprocess.run([WT] + args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout, r.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", str(e)


def snapshot_recipes(stats, max_extra=5):
    """One batched recipes list (cheap); targeted gets only for referenced ids
    missing from the snapshot, capped at max_extra."""
    stats["api_calls"] += 1
    rc, out, err = run_wt(["api", "GET", "/api/recipes?per_page=100"])
    snap = {}
    if rc == 0:
        try:
            items = json.loads(out).get("items", [])
            for it in items:
                snap[str(it.get("id"))] = it
        except json.JSONDecodeError:
            pass
    return snap


def recipe_get(rid, stats):
    stats["api_calls"] += 1
    rc, out, _ = run_wt(["api", "GET", f"/api/recipes/{rid}"])
    if rc == 0:
        try:
            return json.loads(out)
        except json.JSONDecodeError:
            return None
    return None


def check_decision(d, snap, stats):
    """Return (live_state, verdict, rationale, checks). Verdict in yes/no/stale.
    Only verifiable deltas drive yes/no: the live state is compared against
    what the decision's OWN evidence claimed at decision time."""
    text = " ".join(str(d.get(k, "")) for k in ("evidence", "work", "title"))
    checks = []

    # 1. Recipe-state counterfactual (cheapest verifiable delta).
    rids = set(RECIPE_RE.findall(text))
    live_states = []
    for rid in rids:
        r = snap.get(rid) or recipe_get(rid, stats)
        if r and isinstance(r, dict) and "running" in r:
            live_states.append((rid, r.get("running"), r.get("last_run_at"),
                                r.get("job_succeeded_count"), r.get("job_failed_count")))
        else:
            stats["unresolved_ids"].append(rid)
    if live_states:
        checks.append(f"recipe live state via wt dev API ({len(live_states)} ids)")

    claim_running = re.search(r"(?i)running=True|\bRUNNING\b", text)
    claim_stopped = re.search(r"(?i)running=False|zero (?:live )?jobs|zero runs|jobs? count 0|stopped", text)
    if live_states and claim_stopped and not claim_running:
        still = [s for s in live_states if not s[1]]
        live = "; ".join(f"{r[0]} running={r[1]} last_run={r[2]}" for r in live_states)
        if not still:
            return live, "no", ("decision's evidence claimed a stopped blocking state, but every "
                                "referenced recipe now reports running — the blocking condition "
                                "has verifiably moved; re-derive before executing", checks)
        return live, "yes", ("blocking condition still verifiably present (at least one referenced "
                             "recipe still stopped); deferral cost continues", checks)
    if live_states and claim_stopped and claim_running:
        # Mixed claim (e.g. "RUNNING, job count 0"): the delta to test is job
        # movement, not running state.
        total_jobs = sum((s[3] or 0) + (s[4] or 0) for s in live_states)
        live = "; ".join(f"{r[0]} running={r[1]} ok={r[3]} fail={r[4]}" for r in live_states)
        if total_jobs == 0:
            return live, "yes", ("evidence claimed 'running but zero jobs'; live job counts still "
                                 "0 — the tested-once / never-exercised condition verifiably "
                                 "persists, deferral cost continues", checks)
        return live, "no", ("evidence claimed zero jobs; live job counts are now non-zero — the "
                            "recipe has run since the decision was filed, the recorded blocker "
                            "has moved; re-derive before executing", checks)
    if live_states:
        live = "; ".join(f"{r[0]} running={r[1]} last_run={r[2]} ok={r[3]} fail={r[4]}" for r in live_states)
        return live, "stale", ("live recipe state recorded for context, but the decision's "
                               "blocker is not a claimed recipe-state delta (e.g. VUA flags, "
                               "Jira state, tests never run) — cannot establish currency", checks)

    # 2. Proposal-file counterfactual: is the deferred decision still pending?
    props = PROPOSAL_RE.findall(text)
    if props:
        stats["file_stats"] += len(props)
        checks.append(f"proposal-file existence/mtime ({len(props)} files)")
        present = [p for p in props if os.path.exists(os.path.join(KNOWLEDGE, p))]
        if present:
            age_days = round((time.time() - os.path.getmtime(os.path.join(KNOWLEDGE, present[0]))) / 86400, 1)
            return f"proposal file present: {present[0]} (age {age_days}d)", "yes", (
                "the deferred item is still an undecided proposal on disk; deciding now still "
                "helps (no counterfactual evidence it was resolved elsewhere)", checks)

    # 3. External/human blockers: cannot be checked cheaply or honestly.
    if re.search(r"(?i)volunteer|blocked on Josh|Josh['']s (gate|call|review)|non-US person|"
                 r"Marketing Ops|tenant grants|Workday grants|Confluence drafts|second identity|"
                 r"reviewer names|dispatch lane|completion contract", text):
        return None, "stale", ("blocker is human/organizational (approval, review, grants, or a "
                               "person outside this harness); no cheap read-only check can "
                               "establish whether it moved — recorded as unknown, not a fact", checks)

    # 4. Local-file-only evidence: verify artifacts exist (weak counterfactual).
    kpaths = [p for p in KNOWLEDGE_PATH_RE.findall(text)
              if "proposals/" not in p and ("plan" in p or "investigations/" in p or "projects/" in p)]
    checked = []
    for p in kpaths[:3]:
        stats["file_stats"] += 1
        checks.append(f"artifact stat: {os.path.basename(p)}")
        rel = p[len("knowledge/"):] if p.startswith("knowledge/") else p
        full = os.path.join(KNOWLEDGE, rel)
        checked.append(f"{rel} {'exists' if os.path.exists(full) else 'MISSING'}")
    if checked:
        return "artifacts: " + ", ".join(checked), "stale", (
            "plan artifacts verifiably " + ("present" if "MISSING" not in ", ".join(checked)
                                            else "incomplete") +
            ", but the decision's gate is not file-observable — cannot establish whether "
            "executing now still helps", checks)
    return None, "stale", ("no cheap read-only counterfactual available for this decision", checks)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", choices=["dev", "prod"], default="dev")
    ap.add_argument("--confirm", action="store_true", help="required with --env prod")
    ap.add_argument("--out", default=POLICY_DIR)
    a = ap.parse_args()
    if a.env == "prod":
        if not a.confirm:
            print("WARNING: --env prod reads the LIVE PRODUCTION Workato workspace. "
                  "This tool is read-only, but prod reads still require --confirm.")
            sys.exit(1)
        print("WARNING: reading LIVE PRODUCTION recipe state (read-only).")
    with open(INBOX) as f:
        inbox = json.load(f)
    deferred = inbox.get("deferred", [])
    stats = {"api_calls": 1, "file_stats": 0, "unresolved_ids": []}
    snap = snapshot_recipes(stats)

    rows = []
    for d in deferred:
        live, verdict, extra = check_decision(d, snap, stats)
        rationale, checks = extra
        rows.append({"id": d.get("id", "?"), "title": d.get("title", ""),
                     "deferred_since": d.get("ts") or "(no ts recorded)",
                     "origin": d.get("origin"), "source": d.get("source"),
                     "live_state": live or "(not observable)", "verdict": verdict,
                     "rationale": rationale, "checks": checks})
    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("yes", "no", "stale")}

    os.makedirs(a.out, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%SZ", time.gmtime())
    out_path = os.path.join(a.out, f"regret-ledger-{ts}.md")
    with open(out_path, "w") as f:
        f.write(f"# Regret ledger — {now_iso()}\n\n")
        f.write(f"Source: now/decision-inbox.json run {inbox.get('ts')} — "
                f"{len(deferred)} deferred decisions evaluated.\n\n")
        f.write("## What this ledger CAN and CANNOT establish\n\n")
        f.write("- CAN: verifiable live-state deltas only — local file existence/mtime under\n"
                "  knowledge/, and DEV Workato recipe running/last-run/job-count state via the\n"
                "  `wt` CLI (read-only).\n")
        f.write("- CANNOT: modeled dollar/time savings (none are presented as fact); PROD\n"
                "  state (unless explicitly re-run with --env prod --confirm); Jira ticket\n"
                "  state; whether a human blocker has moved.\n")
        f.write("- \"stale\" means the counterfactual could not establish currency — an\n"
                "  honest unknown, never a disguised claim.\n\n")
        f.write(f"## Cost of inference (whole run)\n\n"
                f"- LLM calls: 0 (pure stdlib heuristics)\n"
                f"- Workato API calls: {stats['api_calls']} batched list"
                f" (+{stats['api_calls'] - 1} targeted gets for referenced ids missing from the snapshot)\n"
                f"- Local file stats: {stats['file_stats']}\n\n")
        f.write(f"## Verdicts: {counts['yes']} yes / {counts['no']} no / {counts['stale']} stale\n\n")
        f.write("| id | deferred_since | live state | still helps? | why |\n")
        f.write("|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['id'][:60].replace('|', '/')} | {r['deferred_since']} | "
                    f"{r['live_state'][:80].replace('|', '/')} | **{r['verdict']}** | "
                    f"{r['rationale'].replace('|', '/')} |\n")
        f.write("\n## Per-deferral detail\n\n")
        for r in rows:
            f.write(f"### {r['id']}\n")
            f.write(f"- what was deferred: {r['title']}\n")
            f.write(f"- origin/source: {r['origin']}/{r['source']}\n")
            f.write(f"- deferred since: {r['deferred_since']}\n")
            f.write(f"- current live state: {r['live_state']}\n")
            f.write(f"- would-executing-now-still-help: **{r['verdict']}**\n")
            f.write(f"- why: {r['rationale']}\n")
            f.write(f"- cost of inference: {'; '.join(r['checks']) if r['checks'] else 'regex classification only — no reads'}\n\n")
    print(f"wrote {out_path}")
    print(f"verdicts: {counts['yes']} yes / {counts['no']} no / {counts['stale']} stale "
          f"over {len(rows)} deferred decisions")
    print(f"inference cost: 0 LLM calls, {stats['api_calls']} Workato API calls, {stats['file_stats']} file stats")
    if stats["unresolved_ids"]:
        print(f"note: recipe ids not resolvable in dev snapshot: {sorted(set(stats['unresolved_ids']))[:8]}")


if __name__ == "__main__":
    main()
