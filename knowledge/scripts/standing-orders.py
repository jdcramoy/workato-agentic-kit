#!/usr/bin/env python3
"""standing-orders.py — the decision compiler: policies that MATCH deferred
decisions and print what WOULD happen. This script NEVER executes anything;
`match` mode is the product — execution stays with Josh.

Inputs (read-only): ~/.claude/knowledge/now/decision-inbox.json (structured;
the .md sibling is human-readable rendering of the same run — checked for
existence/freshness only, never parsed, since the JSON is the source of truth).

Policies: knowledge/policies/<id>.json, schema per frontier/CONTRACTS.md:
  {"id","name","match":{"field":{"op":"value",...}},"action":"auto_execute|draft_for_review",
   "dollar_cap","risk_class" (1-4),"expires_at","ratchet":{"breach_shrinks":true},
   "created_from" (decision ids)}
Matcher: first-match-wins (policies sorted by filename); ALL conditions in a
policy's match must hold (AND). Ops: eq, ne, contains, not_contains, in,
not_in, gte, lte, exists, regex.
Ratchet: "any breach auto-expires the policy" — a breach is a matched decision
carrying a numeric "dollar" field above the policy's dollar_cap. When
ratchet.breach_shrinks is true and a breach occurs, the policy file is stamped
breached_at=<now>, which makes every later run treat it as expired. dollar_cap
is only evaluated when a decision actually carries a "dollar" field — decision
"points" are effort estimates, not dollars, and are never converted.

Usage:
  standing-orders.py match
  standing-orders.py draft
  standing-orders.py policy add --file x.json [--force]
  standing-orders.py policy list
"""
import argparse, glob, json, os, re, sys, time

POLICY_DIR = os.path.join(os.path.expanduser("~/.claude/knowledge"), "policies")
INBOX_JSON = os.path.expanduser("~/.claude/knowledge/now/decision-inbox.json")
INBOX_MD = os.path.expanduser("~/.claude/knowledge/now/decision-inbox.md")
VALID_OPS = {"eq", "ne", "contains", "not_contains", "in", "not_in", "gte", "lte", "exists", "regex"}
VALID_ACTIONS = {"auto_execute", "draft_for_review"}


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def load_inbox():
    with open(INBOX_JSON) as f:
        inbox = json.load(f)
    decisions = list(inbox.get("today", [])) + list(inbox.get("deferred", []))
    return inbox, decisions


def get_field(decision, field):
    if field in decision:
        return decision[field]
    cur = decision
    for part in field.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def cond_holds(value, op, arg):
    if op == "exists":
        return (value is not None) == bool(arg)
    if op == "eq":
        return value == arg
    if op == "ne":
        return value != arg
    if op == "contains":
        return isinstance(value, str) and str(arg) in value
    if op == "not_contains":
        return isinstance(value, str) and str(arg) not in value
    if op == "in":
        return value in arg
    if op == "not_in":
        return value not in arg
    if op == "gte":
        return isinstance(value, (int, float)) and value >= arg
    if op == "lte":
        return isinstance(value, (int, float)) and value <= arg
    if op == "regex":
        return isinstance(value, str) and re.search(arg, value) is not None
    return False


def load_policies():
    policies = []
    for path in sorted(glob.glob(os.path.join(POLICY_DIR, "*.json"))):
        try:
            with open(path) as f:
                pol = json.load(f)
            err = validate_policy(pol)
            if err:
                print(f"note: skipping invalid policy {os.path.basename(path)}: {err}")
                continue
            pol["_path"] = path
            policies.append(pol)
        except (json.JSONDecodeError, OSError) as e:
            print(f"note: skipping unreadable policy {path}: {e}")
    return policies


def validate_policy(pol):
    if not isinstance(pol, dict):
        return "not a JSON object"
    for key in ("id", "name", "match", "action"):
        if key not in pol:
            return f"missing required key '{key}'"
    if pol["action"] not in VALID_ACTIONS:
        return f"action must be one of {sorted(VALID_ACTIONS)}"
    if not isinstance(pol["match"], dict) or not pol["match"]:
        return "match must be a non-empty object of {field: {op: value}}"
    for field, conds in pol["match"].items():
        if not isinstance(conds, dict) or not conds:
            return f"match.{field} must be a non-empty object of op: value"
        for op in conds:
            if op not in VALID_OPS:
                return f"match.{field} uses unknown op '{op}' (valid: {sorted(VALID_OPS)})"
    rc = pol.get("risk_class")
    if not isinstance(rc, int) or not 1 <= rc <= 4:
        return "risk_class must be an integer 1-4"
    return None


def policy_expired(pol):
    exp = pol.get("expires_at")
    if exp and str(exp) <= now_iso():
        return True
    if pol.get("breached_at") and pol.get("ratchet", {}).get("breach_shrinks"):
        return True
    return False


def stamp_breach(pol):
    pol["breached_at"] = now_iso()
    with open(pol["_path"], "w") as f:
        json.dump(pol, f, indent=1)
        f.write("\n")


def cmd_match(_a):
    inbox, decisions = load_inbox()
    md_age = None
    if os.path.exists(INBOX_MD):
        md_age = round(time.time() - os.path.getmtime(INBOX_MD), 0)
    policies = load_policies()
    live = [p for p in policies if not policy_expired(p)]
    expired = len(policies) - len(live)
    print(f"decision-inbox.json ts={inbox.get('ts')} — {len(inbox.get('today', []))} today, "
          f"{inbox.get('deferred_count', len(inbox.get('deferred', [])))} deferred")
    print(f"decision-inbox.md present: {os.path.exists(INBOX_MD)}"
          + (f" (age {md_age/3600:.1f}h — JSON is authoritative)" if md_age is not None else ""))
    print(f"policies loaded: {len(live)} live, {expired} expired/breached\n")

    if not live:
        print("NO LIVE POLICIES — nothing would happen to any decision. "
              "Run `standing-orders.py draft` for candidates.")
        matched_count = 0
    else:
        matched_count = 0
        for d in decisions:
            hit = None
            for pol in live:
                if all(cond_holds(get_field(d, field), op, arg)
                       for field, conds in pol["match"].items()
                       for op, arg in conds.items()):
                    hit = pol
                    break
            if hit:
                matched_count += 1
                print(f"MATCH  [{d.get('id', '?')[:70]}]")
                print(f"  policy: {hit['name']} ({hit['id']}) risk_class={hit.get('risk_class')}")
                print(f"  WOULD: {hit['action']}"
                      + (f" (dollar_cap={hit['dollar_cap']})" if hit.get("dollar_cap") else ""))
                if hit.get("dollar_cap") is not None:
                    dv = d.get("dollar")
                    if isinstance(dv, (int, float)) and dv > hit["dollar_cap"]:
                        print(f"  BREACH: decision dollar={dv} > cap={hit['dollar_cap']}"
                              + (" — policy ratcheted to expired" if hit.get("ratchet", {}).get("breach_shrinks") else ""))
                        if hit.get("ratchet", {}).get("breach_shrinks"):
                            stamp_breach(hit)
                    elif dv is None:
                        print("  note: dollar_cap set but decision carries no 'dollar' field — "
                              "cap not evaluated (points are not dollars)")
            else:
                print(f"NO POLICY  [{d.get('id', '?')[:70]}]")
    print(f"\nSummary: {len(decisions)} open decisions, {matched_count} would be routed "
          f"by policy, {len(decisions) - matched_count} unmatched.")
    print("Nothing was executed. Match mode is advisory; execution stays with Josh.")


def cmd_draft(_a):
    inbox, decisions = load_inbox()
    # Derive drafts from the ACTUAL history, honestly — this run's inbox is one
    # day deep, so treat these as hypotheses for Josh to review, not laws.
    low_risk = [d for d in decisions if str(d.get("work", "")).startswith("decide proposal (low risk)")]
    med_high = [d for d in decisions if "risk)" in str(d.get("work", "")) and d not in low_risk]
    triage_pts = [d for d in decisions if d.get("source") == "jira-autotriage"
                  and isinstance(d.get("points"), int)]
    print(f"HISTORY HONESTY: derived from one decision-inbox run ({inbox.get('ts')}): "
          f"{len(decisions)} open decisions — {len(low_risk)} low-risk dreamer proposals, "
          f"{len(med_high)} medium/high-risk ones, {len(triage_pts)} triage items with points. "
          "That is thin history; these drafts are hypotheses to review, not compiled law.")
    drafts = [
        {"id": "so-001-low-risk-dreamer-proposals",
         "name": "Low-risk dreamer proposals: pre-draft approval text, queue for review",
         "match": {"work": {"contains": "decide proposal (low risk)"},
                   "source": {"eq": "dreamer"}},
         "action": "draft_for_review",
         "dollar_cap": None,
         "risk_class": 1,
         "expires_at": None,
         "ratchet": {"breach_shrinks": True},
         "created_from": sorted(d.get("id") for d in low_risk)[:10]},
        {"id": "so-002-jira-triage-small-builds",
         "name": "Small Jira triage items (<=2 pts, dev-scoped): pre-stage plan summaries",
         "match": {"source": {"eq": "jira-autotriage"}, "points": {"lte": 2}},
         "action": "draft_for_review",
         "dollar_cap": None,
         "risk_class": 2,
         "expires_at": None,
         "ratchet": {"breach_shrinks": True},
         "created_from": sorted(d.get("id") for d in triage_pts if d.get("points", 0) <= 2)},
        {"id": "so-003-prod-facing-josh-gate",
         "name": "Anything prod-facing or Josh-gated: never auto — always a drafted card",
         "match": {"work": {"regex": "(?i)josh[- ]gated|prod write|Josh's call|Josh-gated"}},
         "action": "draft_for_review",
         "dollar_cap": None,
         "risk_class": 4,
         "expires_at": None,
         "ratchet": {"breach_shrinks": True},
         "created_from": sorted(d.get("id") for d in decisions
                                if re.search(r"(?i)josh[- ]gated|prod write|Josh's call", str(d.get("work", ""))))},
    ]
    for d in drafts:
        d["_validation"] = validate_policy(d) or "valid"
    print(json.dumps(drafts, indent=2))
    print("\nDRAFT ONLY — printed, not written. Review, edit, save each to a file and run: "
          "standing-orders.py policy add --file <id>.json")


def cmd_policy_add(a):
    try:
        with open(a.file) as f:
            pol = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        sys.exit(f"cannot read {a.file}: {e}")
    err = validate_policy(pol)
    if err:
        sys.exit(f"invalid policy: {err}")
    dest = os.path.join(POLICY_DIR, pol["id"] + ".json")
    if os.path.exists(dest) and not a.force:
        sys.exit(f"{dest} already exists (use --force to overwrite)")
    os.makedirs(POLICY_DIR, exist_ok=True)
    with open(dest, "w") as f:
        json.dump(pol, f, indent=1)
        f.write("\n")
    print(f"policy installed: {dest}")
    print(f"  {pol['name']} — action={pol['action']} risk_class={pol['risk_class']}")
    print("It will be evaluated by `standing-orders.py match` from the next run onward.")


def cmd_policy_list(_a):
    policies = load_policies()
    if not policies:
        print("no policies installed")
        return
    for pol in policies:
        state = "EXPIRED/BREACHED" if policy_expired(pol) else "live"
        print(f"{pol['id']}: {pol['name']} [{state}] action={pol['action']} risk_class={pol.get('risk_class')}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("match", help="evaluate open decisions against policies (prints WOULD, never executes)").set_defaults(fn=cmd_match)
    sub.add_parser("draft", help="print 3 draft policies derived from real decision history").set_defaults(fn=cmd_draft)
    p = sub.add_parser("policy", help="manage policies")
    psub = p.add_subparsers(dest="pcmd", required=True)
    pa = psub.add_parser("add", help="install a policy from a JSON file")
    pa.add_argument("--file", required=True)
    pa.add_argument("--force", action="store_true")
    pa.set_defaults(fn=cmd_policy_add)
    pl = psub.add_parser("list", help="list installed policies")
    pl.set_defaults(fn=cmd_policy_list)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
