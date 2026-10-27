#!/usr/bin/env python3
"""
workato-review-guard.py — Patricia Guevarra DR-review guardrails (BSYS-29592, 2026-10-20) as code.

Five mechanical rules distilled from the Final Tech Review findings on
BSYS-29592 (https://workato.atlassian.net/browse/BSYS-29592):

  R1 PILL HYGIENE            every loop's loop-item schema must be declared and
                             every loop-item pill must resolve against it
                             (the "invalid pills in some recipes" finding).
  R2 BATCH-WHERE-POSSIBLE    a loop feeding create/insert steps is mechanically
                             batchable (WARNING only — sequential file ops and
                             per-item side-effectful writes are legitimate).
  R3 NO HARDCODED SLACK IDS  Slack-step channel/user IDs are literals matching
                             U[...] / C[...] -> must be project properties.
  R4 BOT IDENTITY            Slack postMessage-style steps must be bound to a
                             slack_bot connection, never a personal user-token
                             Slack connection (search-style steps are exempt).
  R5 ACTION TITLE LENGTH     custom-adapter action titles <= 30 chars
                             ("the connector action titles are very long again").

READ-ONLY against Workato: all live access is `wt` GET calls. Never writes.

Usage:
  workato-review-guard.py --recipe <id>              # single live recipe (dev)
  workato-review-guard.py --folder <folder-id>       # every recipe in folder (dev)
  workato-review-guard.py --files <dir>              # offline fixtures: recipe_*.json,
                                                     #   conns.json, adapter_*.rb
  workato-review-guard.py --recipe <id> --adapter-code adapter.rb
  workato-review-guard.py --files <dir> --rules R1,R3
  workato-review-guard.py --files <dir> --json

Exit codes: 0 = clean (warnings allowed), 1 = at least one FAIL,
2 = usage/IO error.
"""

import argparse
import json
import os
import re
import subprocess
import sys

# ---------------------------------------------------------------- constants

LOOP_KEYWORDS = ("foreach", "repeat")

SLACK_PROVIDERS = ("slack", "slack_bot")

# postMessage-style Slack step action names (R4 scope: outbound posting only)
POST_MESSAGE_PATTERNS = (
    "post_message_to_channel", "post_bot_message", "post_message",
    "send_message", "chat_post_message", "post_delayed_message",
)

# create/insert-style step names that make a loop mechanically batchable (R2)
CREATE_STEP_PATTERNS = (
    "add_record", "add_records", "create_record", "create_records",
    "insert_record", "insert_records", "create_row", "insert_row",
)

# R2 exemption: sequential file operations are legitimate inside a loop
FILE_PROVIDER_MARKER = "workato_files"

SLACK_ID_RE = re.compile(r"(?<![A-Za-z0-9])([UC][A-Z0-9]{8,})(?![A-Za-z0-9])")

PILL_RE = re.compile(r"_dp\('(.+?)'\)", re.S)

ACTION_TITLE_RE = re.compile(r"^\s{2,8}([a-z0-9_]+):\s*\{\s*$")
ACTION_TITLE_LINE_RE = re.compile(r"^\s{4,10}title:\s*'([^']*)'")

R5_TITLE_LIMIT = 30

BLK = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
YEL = "\033[33m"
GRN = "\033[32m"
RST = "\033[0m"


def use_color():
    return sys.stdout.isatty()


# ---------------------------------------------------------------- DSL helpers

def load_recipe(raw):
    """Accept a full recipe JSON (has 'code'), a bare DSL dict, or a JSON string."""
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, dict) and "code" in raw and isinstance(raw["code"], (str, dict)):
        code = raw["code"]
        if isinstance(code, str):
            code = json.loads(code)
        return raw, code
    # bare DSL
    if isinstance(raw, dict) and "as" in raw or "keyword" in raw:
        return {}, raw
    raise ValueError("unrecognized recipe payload")


def walk_blocks(node):
    """Yield every block in the DSL tree (including the root)."""
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("block", []) or []:
        yield from walk_blocks(child)


def extract_pills(value):
    """Yield parsed pill dicts from any string/config fragment."""
    if not isinstance(value, str):
        if isinstance(value, (list, dict)):
            blob = json.dumps(value)
        else:
            return
    else:
        blob = value
    for m in PILL_RE.finditer(blob):
        inner = m.group(1).replace('\\"', '"')
        try:
            yield json.loads(inner)
        except json.JSONDecodeError:
            continue


def schema_navigate(schema, path):
    """Walk an extended_output_schema by a pill path list; return the final node."""
    cur = schema
    node = None
    for seg in path:
        if isinstance(cur, dict):
            props = cur.get("properties") or []
        elif isinstance(cur, list):
            props = cur
        else:
            return None
        nxt = None
        for p in props:
            if isinstance(p, dict) and p.get("name") == seg:
                nxt = p
                break
        if nxt is None:
            return ("missing", seg, node)
        node = nxt
        cur = nxt
    return node


def array_item_properties(node):
    """Return (properties, ok) for an array-of-object schema node."""
    if not isinstance(node, dict):
        return None, False
    if node.get("type") != "array":
        return None, False
    props = node.get("properties")
    if not props:
        # "of": "object" with no declared properties = the known-bad signature
        return [], False
    return props, True


# ---------------------------------------------------------------- wt (read-only)

_WT_CALLS = 0


def wt(*args):
    global _WT_CALLS
    cmd = ["wt"] + [str(a) for a in args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        sys.stderr.write("FATAL: wt CLI not found on PATH\n")
        sys.exit(2)
    _WT_CALLS += 1
    out = proc.stdout
    i_obj, i_arr = out.find("{"), out.find("[")
    if i_obj < 0 and i_arr < 0:
        return None
    start = min(x for x in (i_obj, i_arr) if x >= 0)
    # wt may append a trailing evidence/log line after the JSON body
    dec = json.JSONDecoder()
    try:
        obj, _ = dec.raw_decode(out[start:])
        return obj
    except json.JSONDecodeError:
        return None


def wt_recipe(recipe_id):
    return wt("api", "GET", f"/api/recipes/{recipe_id}")


def wt_recipes_in_folder(folder_id):
    """Paged listing scoped server-side by folder_id; items embed full code + config."""
    recipes, page = [], 1
    while True:
        obj = wt("api", "GET", "/api/recipes",
                 "--query", f"per_page=100", f"page={page}", f"folder_id={folder_id}")
        if not obj or not obj.get("items"):
            break
        recipes.extend(obj["items"])
        total = obj.get("count") or 0
        if len(recipes) >= total or len(obj["items"]) < 100 or page > 100:
            break
        page += 1
    return recipes


def wt_connections():
    """All connections for R4 identity resolution.

    GET /api/connections returns a BARE JSON array (not {"items": ...}) and
    ignores per_page/page — one call returns the whole catalog (965 rows).
    """
    obj = wt("api", "GET", "/api/connections")
    if obj is None:
        return []
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict) and "items" in obj:
        return obj["items"]
    return []


# ---------------------------------------------------------------- rule engines

def rule_r1(recipe, code):
    """Pill hygiene: loop-item schema must be declared; loop pills must resolve."""
    findings = []
    blocks = list(walk_blocks(code))
    by_as = {}
    for b in blocks:
        asname = b.get("as")
        if asname:
            by_as.setdefault(asname, b)

    for b in blocks:
        if b.get("keyword") not in LOOP_KEYWORDS:
            continue
        loc = f"step {b.get('number')} ({b.get('as')})"
        src = b.get("source") or ""
        pills = list(extract_pills(src))
        if not pills:
            continue  # repeat blocks / literal sources out of mechanical scope
        pill = pills[0]
        src_line = pill.get("line")
        path = pill.get("path") or []
        src_step = by_as.get(src_line)
        if src_step is None:
            continue  # cannot verify statically -> no finding
        node = schema_navigate(src_step.get("extended_output_schema", []), path)
        if node is None or (isinstance(node, tuple) and node[0] == "missing"):
            continue  # source schema absent entirely: cannot verify statically
        props, ok = array_item_properties(node)
        if not ok and props == []:
            findings.append(("R1", "FAIL", loc, (
                f"loop source {' -> '.join(map(str, path))} of step '{src_line}' is an "
                f"array of objects with NO declared properties — every loop-item pill in "
                f"this body is an unresolvable/invalid pill. Declare the item schema "
                f"(extended_output_schema properties) on the source step."
            )))
            continue
        if ok:
            names = {p.get("name") for p in props if isinstance(p, dict)}
            for child in walk_blocks(b):
                if child is b:
                    continue
                for pill2 in extract_pills(child.get("input", {})):
                    if pill2.get("line") == b.get("as") and pill2.get("path"):
                        field = str(pill2["path"][0])
                        if names and field not in names:
                            findings.append(("R1", "FAIL", f"step {child.get('number')} in {loc}", (
                                f"loop-item pill '{field}' not present in the declared "
                                f"loop schema of '{src_line}' ({', '.join(sorted(names))[:120]}...)"
                                if len(names) > 6 else
                                f"loop-item pill '{field}' not present in the declared "
                                f"loop schema of '{src_line}' (fields: {', '.join(sorted(names))})"
                            )))
    return findings


def rule_r2(recipe, code):
    """Batch-where-possible: loops feeding create/insert steps (WARNING)."""
    findings = []
    for b in walk_blocks(code):
        if b.get("keyword") not in LOOP_KEYWORDS:
            continue
        loc = f"step {b.get('number')} ({b.get('as')})"
        body = list(walk_blocks(b))[1:]  # exclude the loop block itself
        creates = [c for c in body
                   if any(p in (c.get("name") or "") for p in CREATE_STEP_PATTERNS)]
        if not creates:
            continue
        has_file_ops = any(FILE_PROVIDER_MARKER in (c.get("provider") or "") for c in body)
        names = ", ".join(f"{c.get('provider')}/{c.get('name')} (step {c.get('number')})"
                          for c in creates)
        if has_file_ops:
            findings.append(("R2", "WARNING", loc, (
                f"loop feeds create/insert steps ({names}) — mechanically batchable, BUT this "
                f"body also contains sequential file operations (workato_files), a legitimate "
                f"per-item exemption; confirm the write ordering actually requires serialism"
            )))
        else:
            findings.append(("R2", "WARNING", loc, (
                f"loop feeds create/insert steps ({names}) — mechanically batchable: use a "
                f"batch action (batch create/upsert) or array slicing instead of per-item "
                f"repeats (Patricia BSYS-29592: 'use a batch action instead of a repeat action')"
            )))
    return findings


def rule_r3(recipe, code):
    """No hardcoded Slack channel/user IDs in Slack-step parameters."""
    findings = []
    for b in walk_blocks(code):
        prov = (b.get("provider") or "").lower()
        if "slack" not in prov:
            continue
        blob = json.dumps(b.get("input", {}))
        for m in SLACK_ID_RE.finditer(blob):
            sid = m.group(1)
            findings.append(("R3", "FAIL", f"step {b.get('number')} ({b.get('as')})", (
                f"hardcoded Slack ID '{sid}' in {b.get('provider')}/{b.get('name')} — "
                f"move to a project property (wt properties upsert) so a recipient change "
                f"never needs a prod re-edit (Patricia BSYS-29592)"
            )))
    return findings


def rule_r4(recipe, code, conns_by_id):
    """Bot identity for Slack post steps: bound connection application must be slack_bot."""
    findings = []
    app_map = {}
    for c in recipe.get("config", []) or []:
        if c.get("keyword") == "application" and c.get("account_id"):
            app_map[c.get("provider")] = c["account_id"]

    for b in walk_blocks(code):
        prov = (b.get("provider") or "").lower()
        name = (b.get("name") or "").lower()
        if "slack" not in prov:
            continue
        if not any(p in name for p in POST_MESSAGE_PATTERNS):
            continue  # search-style / read steps are VUA-exempt by design
        loc = f"step {b.get('number')} ({b.get('as')})"
        account_id = app_map.get(b.get("provider"))
        conn = conns_by_id.get(str(account_id)) or conns_by_id.get(account_id)
        if conn is None:
            findings.append(("R4", "FAIL", loc, (
                f"Slack post step {b.get('provider')}/{b.get('name')} is bound to connection "
                f"account_id={account_id} which could not be resolved in the connections "
                f"catalog — verify it is a slack_bot connection, not a personal user token"
            )))
            continue
        application = (conn.get("application") or "").lower()
        conn_name = conn.get("name") or f"connection {account_id}"
        if application != "slack_bot":
            findings.append(("R4", "FAIL", loc, (
                f"Slack post step is bound to '{conn_name}' (application={application}, id "
                f"{account_id}) — bot posts must use a slack_bot connection, never a personal "
                f"user-token Slack connection (Patricia BSYS-29592: 'this should probably be "
                f"using a bot connection or integration user')"
            )))
        else:
            findings.append(("R4", "PASS", loc,
                             f"bound to slack_bot connection '{conn_name}'"))
    return findings


def rule_r5(adapter_sources, recipe=None):
    """Custom-adapter action titles <= 30 chars.

    Parses connector SDK Ruby source: an `actions: {` block at 2-space indent,
    action entries at 4-space indent (`name: {`), each carrying a `title: '...'`
    at 6-space indent. Flags titles longer than the 30-char house bar.
    """
    findings = []
    for fname, text in adapter_sources:
        in_actions = False
        cur_action = None
        checked = 0
        for ln, line in enumerate(text.splitlines(), 1):
            if not in_actions:
                if re.match(r"^  actions:\s*\{?\s*$", line):
                    in_actions = True
                continue
            stripped = line.rstrip()
            if re.match(r"^  \}", stripped) or stripped == "}":
                in_actions = False
                cur_action = None
                continue
            m = ACTION_TITLE_RE.match(line)
            if m and cur_action is None:
                cur_action = m.group(1)
                continue
            if cur_action:
                t = ACTION_TITLE_LINE_RE.match(line)
                if t:
                    checked += 1
                    title = t.group(1)
                    if len(title) > R5_TITLE_LIMIT:
                        findings.append(("R5", "FAIL", f"{fname}:line {ln}", (
                            f"action '{cur_action}' title is {len(title)} chars "
                            f"(house bar {R5_TITLE_LIMIT}): '{title}' — shorten the title, "
                            f"move detail into description/hint (Patricia BSYS-29592: "
                            f"'the connector action titles are very long again')"
                        )))
                    cur_action = None
        if checked:
            findings.append(("R5", "PASS", fname,
                             f"{checked} action title(s) checked, all <= {R5_TITLE_LIMIT} chars"))
    # recipe-step titles (custom-adapter steps can carry an overridden title)
    if recipe is not None and recipe != []:
        _, code = load_recipe(recipe)
        for b in walk_blocks(code):
            t = b.get("title")
            if isinstance(t, str) and len(t) > R5_TITLE_LIMIT:
                findings.append(("R5", "FAIL", f"step {b.get('number')} ({b.get('as')})", (
                    f"step title is {len(t)} chars (house bar {R5_TITLE_LIMIT}): '{t}'"
                )))
    return findings
# ---------------------------------------------------------------- reporting

def run_rules(recipe, conns_by_id, adapter_sources):
    _, code = load_recipe(recipe)
    results = {}
    results["R1"] = rule_r1(recipe, code)
    results["R2"] = rule_r2(recipe, code)
    results["R3"] = rule_r3(recipe, code)
    results["R4"] = rule_r4(recipe, code, conns_by_id)
    results["R5"] = rule_r5(adapter_sources, recipe=recipe)
    return results


def summarize(all_results, adapter_mode, json_out=False, color=True):
    C = (lambda s: s) if not color else (lambda s: s)

    def paint(v, s):
        if not color:
            return s
        return {"FAIL": RED + s + RST, "WARNING": YEL + s + RST,
                "PASS": GRN + s + RST}.get(v, s)

    if json_out:
        out = []
        for rid, results in all_results:
            entry = {"recipe": f"{recipe_label(rid)}", "rules": {}}
            for rule, findings in results.items():
                entry["rules"][rule] = [
                    {"verdict": v, "location": loc, "message": msg}
                    for (_, v, loc, msg) in findings
                ]
            out.append(entry)
        return json.dumps(out, indent=2)

    lines = []
    for rid, results in all_results:
        lines.append(C(BLK + f"\n== {recipe_label(rid)}" + RST))
        for rule in ("R1", "R2", "R3", "R4", "R5"):
            findings = results.get(rule, [])
            fails = [f for f in findings if f[1] == "FAIL"]
            warns = [f for f in findings if f[1] == "WARNING"]
            passes = [f for f in findings if f[1] == "PASS"]
            if fails:
                verdict = paint("FAIL", "FAIL")
            elif warns:
                verdict = paint("WARNING", "WARN")
            elif passes:
                verdict = paint("PASS", "PASS")
            else:
                verdict = DIM + "n/a" + RST
            lines.append(f"  {rule}  {verdict}  ({len(fails)} fail / {len(warns)} warn)")
            for (_, v, loc, msg) in findings:
                marker = paint(v, {"FAIL": "  FAIL", "WARNING": "  WARN", "PASS": "  pass"}[v])
                lines.append(f"{marker} {loc}: {msg}")
    return "\n".join(lines)


def recipe_label(recipe):
    if isinstance(recipe, dict):
        name = recipe.get("name") or ""
        rid = recipe.get("id") or ""
        return f"recipe {rid} '{name}'" if rid else (name or "(unnamed DSL)")
    return str(recipe)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=False)
    g.add_argument("--recipe", type=str)
    g.add_argument("--folder", type=str)
    g.add_argument("--files", type=str, metavar="DIR",
                   help="offline fixture mode: recipe_*.json, conns.json, adapter_*.rb")
    ap.add_argument("--adapter-code", action="append", default=[], metavar="FILE",
                    help="connector SDK Ruby source(s) for R5 (may be used alone or with a scan mode)")
    ap.add_argument("--rules", type=str, default="R1,R2,R3,R4,R5",
                    help="comma-separated rule subset")
    ap.add_argument("--json", action="store_true", dest="as_json")
    ap.add_argument("--no-color", action="store_true")
    args = ap.parse_args()

    wanted = {r.strip().upper() for r in args.rules.split(",") if r.strip()}
    color = (not args.no_color) and use_color()
    if not any([args.recipe, args.folder, args.files, args.adapter_code]):
        ap.error("one of --recipe, --folder, --files, or --adapter-code is required")
    jobs = []  # list of (recipe_dict, path_or_None)
    conns_by_id = {}
    adapter_sources = []
    if args.recipe:
        r = wt_recipe(args.recipe)
        if not r or "code" not in r:
            sys.stderr.write(f"FATAL: could not fetch recipe {args.recipe} via wt (read-only GET)\n")
            sys.exit(2)
        jobs.append((r, None))
        conns_by_id = {str(c.get("id")): c for c in (wt_connections() or [])}
    elif args.folder:
        jobs = [(r, None) for r in wt_recipes_in_folder(args.folder)]
        if not jobs:
            sys.stderr.write(f"no recipes found in folder {args.folder}\n")
            sys.exit(2)
        conns_by_id = {str(c.get("id")): c for c in (wt_connections() or [])}
    elif args.files:
        d = args.files
        conns_path = os.path.join(d, "conns.json")
        if os.path.exists(conns_path):
            try:
                data = json.load(open(conns_path))
                if isinstance(data, dict):
                    for k, v in data.items():
                        conns_by_id.setdefault(str(k), v)
                else:
                    for c in data:
                        conns_by_id[str(c.get("id"))] = c
            except (json.JSONDecodeError, OSError) as e:
                sys.stderr.write(f"WARN: could not parse {conns_path}: {e}\n")
        for fn in sorted(os.listdir(d)):
            path = os.path.join(d, fn)
            if re.match(r"recipe_.*\.json$", fn):
                try:
                    raw = json.load(open(path))
                    jobs.append((raw, path))
                except (json.JSONDecodeError, OSError) as e:
                    sys.stderr.write(f"WARN: skip {path}: {e}\n")
            elif re.match(r"adapter_.*\.(rb|ruby)$", fn) or fn.endswith(".connector.rb"):
                adapter_sources.append((fn, open(path, encoding="utf-8", errors="replace").read()))
    for a in args.adapter_code:
        adapter_sources.append((os.path.basename(a),
                                open(a, encoding="utf-8", errors="replace").read()))

    all_results = []
    for recipe, path in jobs:
        label = os.path.basename(path) if path else recipe.get("id")
        results = run_rules(recipe, conns_by_id, adapter_sources)
        results = {k: v for k, v in results.items() if k in wanted}
        all_results.append((label, results))

    # adapter-only R5 run (no recipes scanned, e.g. --adapter-code with --rules R5)
    if not all_results and adapter_sources:
        results = {r: [] for r in ("R1", "R2", "R3", "R4", "R5") if r in wanted}
        results["R5"] = rule_r5(adapter_sources, recipe=None)
        all_results.append(("(adapter only)", results))

    print(summarize(all_results, bool(adapter_sources), json_out=args.as_json, color=color))

    any_fail = any(
        f[1] == "FAIL"
        for _, results in all_results for fs in results.values() for f in fs
    )
    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
