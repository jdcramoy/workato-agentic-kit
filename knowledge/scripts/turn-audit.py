#!/usr/bin/env python3
"""turn-audit.py — turn-discipline auditor (built 2026-10-12, Josh-approved).

Classifies assistant turns in session transcripts into PRODUCTIVE / VERIFICATION
(protected) / WASTE, splits identical-command retries into poll vs blind-thrash,
and pairs the waste trend with quality-guard metrics (evidence FALSE verdicts,
regression canon results, AIRO stale-error rate). Zero-LLM; runs in the fleet.

Usage: turn-audit.py [--days N] [--sample-only]
Output: knowledge/reports/turn-audit-latest.md (+ .json), trend row appended to
knowledge/reports/turn-audit-trend.jsonl, gossip-bus post.
"""
import glob, json, os, re, sys, time
from collections import Counter, defaultdict
from pathlib import Path

HOME = Path.home()
KB = HOME / ".claude" / "knowledge"
CORPUS = HOME / ".claude" / "projects"
PROJECTS = ["-Users-YOUR-USER-Documents-workbench"]  # main working corpus
REPORT = KB / "reports" / "turn-audit-latest.md"
TREND = KB / "reports" / "turn-audit-trend.jsonl"
BUS = KB / "dreams" / "bus" / "turn-audit.jsonl"

DAYS = 7
args = sys.argv[1:]
# --help/-h gate (2026-10-16): this script executes its audit AT MODULE LEVEL
# (no main guard), so a naive `--help` ran the full pass — reports, trend row,
# bus post. Exit before anything side-effecting.
if "--help" in args or "-h" in args:
    print(__doc__)
    sys.exit(0)
if "--days" in args:
    DAYS = int(args[args.index("--days") + 1])

cutoff = time.time() - DAYS * 86400

# --- signatures ------------------------------------------------------------
# v2 (2026-10-23, finding turn-audit-verif-def-false-positives): the bare
# `\bkb\b` alternation counted EVERY Bash command merely containing the word
# "kb" as verification — the rate swung with KB-corpus churn, not with actual
# verification behavior. Dropped; `kb_search` (a real read-back shape) stays.
# v3 (2026-10-27, recalibration after the cortex-detected drift, dream
# 2026-10-25 errors section): v1's 13% was inflated by the bare-kb artifact;
# v2 removed it but credited only a narrow tool-name slice, so the SAME corpus
# re-scored 2.76% while verification behavior held steady. v3 credits the
# shapes recent sessions actually verify with (grounded in turn-audit-
# fixtures.json, drawn from real 7d transcripts):
#   - wt CLI live probes: wt recipes get / wt recipes job* / wt jobs list /
#     wt fixture run (asset read-backs, job traces, test execution)
#   - live log probes: gcloud logging read
#   - GET-shaped curl probes (curl with no POST/PUT/PATCH/DELETE and no
#     -d/--data payload); write-shaped curl stays productive
#   - verification-tier MCP tool-name suffixes: job traces (job_get/job_list),
#     asset read-backs (recipe_get/get_recipe/genie_get/data_table_get/
#     data_table_query/lookup_table_lookup/status_get), kb_search/kb_read,
#     dependency traces, slide visual-QA renders (Get_Slide_Thumbnail/
#     Render_Slide/Inspect_Render/Measure_Slide/Check_Widowing)
#   - read-backs: a read of a file THIS SESSION wrote (Bash cat/tail/grep or
#     Read tool) or a getJiraIssue of an issue THIS SESSION posted to (the
#     render-check standing rule). Generic reads stay productive.
# Conservative by design: bare-word tools (Get_Slide, generic getJiraIssue,
# ls/cat of untouched files) are NOT credited, so the rate cannot inflate.
SIG_VERSION = "v3-wt-probes+curl-get+readback"
STALE_SIG = re.compile(r"404 Not Found|Unknown data table field|schema_version|"
                       r"not on the appropriate screen", re.I)
VERIFY_SIG = re.compile(r"unittest|pytest|\btest\b|job_get|job handle|trace|"
                        r"verify|read.?back|kb_search|"
                        r"wt recipes get|wt recipes job|wt jobs list|wt job\b|"
                        r"wt fixture run|gcloud logging read", re.I)
VERIFY_TOOL_SIG = re.compile(r"job_get|job_list|recipe_get|get_recipe|"
                             r"genie_get|data_table_get|data_table_query|"
                             r"lookup_table_lookup|status_get|kb_search|kb_read|"
                             r"search_recipe_dependencies|"
                             r"get_slide_thumbnail|render_slide|inspect_render|"
                             r"measure_slide|check_widowing|verify|trace", re.I)
VERIFY_READ_SIG = re.compile(r"trace|verif|audit|evidence|report|regression",
                             re.I)
# GET-only curl probe: curl WITHOUT write flags/payload
CURL_WRITE_SIG = re.compile(r"curl[^|;&\"']*(?:-X\s*(?:POST|PUT|PATCH|DELETE)"
                            r"|--data|\s-d\s)", re.I)
# bash read shapes eligible for read-back credit
BASH_READ_SIG = re.compile(r"(?:^|[;&|]\s*|\bsudo\s+)"
                           r"(?:cat|head|tail|grep|sed|awk|less|more|wc|rg)\b")
# bash write shapes that register a read-back target
BASH_WRITE_PATH = re.compile(r"(?:>>?|tee\s+(?:-a\s+)?)\s*(\S+)")
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit"}
JIRA_WRITE_TOOLS = {"mcp__atlassian__addCommentToJiraIssue",
                    "mcp__atlassian__editJiraIssue",
                    "mcp__atlassian__createJiraIssue"}
JIRA_READ_TOOLS = {"mcp__atlassian__getJiraIssue"}
CONF_WRITE_TOOLS = {"mcp__atlassian__updateConfluencePage"}
CONF_READ_TOOLS = {"mcp__atlassian__getConfluencePage"}
PERM_SIG = re.compile(r"haven'?t granted|requested permissions|permission .*(denied|required)|"
                      r"operation not permitted", re.I)


def classify_command(cmd: str, prev_err: bool, written_paths=frozenset()) -> str:
    """VERIFICATION if it looks like a test/verify action, a GET-only live
    probe, or a read-back of something this session wrote; WASTE if identical
    blind retry (same command, previous attempt errored, no edit between);
    else PRODUCTIVE."""
    if VERIFY_SIG.search(cmd):
        return "verification"
    if "curl" in cmd and not CURL_WRITE_SIG.search(cmd) and \
       re.search(r"\bcurl\b", cmd):
        return "verification"   # GET-shaped live probe
    if written_paths:
        # a redirect makes this a WRITE, not a read-back (even via cat >>)
        is_write = re.search(r"(?<![0-9&])>", cmd)
        if not is_write:
            # heredoc bodies name files the command WRITES; matching them
            # would credit the write as a read-back (drift-v3 trap)
            cmd_head = re.split(r"<<-?\s*['\"\\w]+", cmd)[0]
            # basename-level match: a write into a directory must NOT make a
            # later ls/grep of that directory a "read-back" (drift-v3 trap,
            # seen in the 7d recount); only reading the file itself counts
            for p in written_paths:
                base = os.path.basename(p)
                if len(base) > 3 and base in cmd_head and \
                   BASH_READ_SIG.search(cmd_head):
                    return "verification"   # read-back of own write
    if prev_err:
        return "waste"      # blind retry candidate (exact string, post-error)
    return "productive"


def classify_turn(cmd: str, prev_err: bool, prev_cmd: str,
                  written_paths=frozenset()) -> str:
    """Full turn class including the poll split (same command repeated after a
    SUCCESSFUL previous run is a legitimate poll, not waste). Single code path
    for the audit loop and --selftest."""
    cls = classify_command(cmd, prev_err, written_paths)
    if cls == "productive" and prev_cmd == cmd:
        cls = "poll"        # same command, last one SUCCEEDED
    return cls


def _selftest() -> int:
    fx_path = Path(__file__).parent / "turn-audit-fixtures.json"
    fixtures = json.loads(fx_path.read_text())
    fails = 0
    for fx in fixtures:
        kind = fx.get("kind", "bash")
        expected = fx["expected"]
        if kind == "bash":
            got = classify_turn(fx["cmd"], bool(fx.get("prev_err")),
                                fx["cmd"] if fx.get("prev_same") else None,
                                frozenset(fx.get("written", [])))
        elif kind == "tool":
            name = fx.get("name", "")
            if VERIFY_TOOL_SIG.search(name):
                got = "verification"
            else:
                got = "productive"
        elif kind == "jira_read":
            got = "verification" if fx.get("key") in set(
                fx.get("written_keys", [])) else "productive"
        elif kind == "read":
            got = "verification" if fx.get("file_path") in set(
                fx.get("written", [])) else "productive"
        else:
            got = None
        ok = got == expected
        if not ok:
            fails += 1
        mark = "ok  " if ok else "FAIL"
        label = kind if kind == "bash" else f"{kind}:{fx.get('name', fx.get('file_path', ''))}"
        print(f"[{mark}] {label[:60]:60s} {expected} -> {got}  "
              f"({fx.get('why', '')[:60]})")
    print(f"\nfixtures: {len(fixtures) - fails}/{len(fixtures)} pass, {fails} fail")
    return 1 if fails else 0

if "--selftest" in args:
    sys.exit(_selftest())

sessions = 0
tot = Counter()          # turn classes
tool_calls = 0
err_by_class = Counter() # waste causes
retries_poll = 0
retries_blind = 0
worst = []
last_cmd_by_session = {}

for proj in PROJECTS:
    for f in glob.glob(str(CORPUS / proj / "*.jsonl")):
        if os.path.getmtime(f) < cutoff:
            continue
        try:
            lines = open(f, errors="replace").read().strip().split("\n")
        except Exception:
            continue
        pending = {}      # toolUseID -> command string (bash)
        last_cmd, last_cmd_err = None, False
        written_paths, written_keys, written_pages = set(), set(), set()
        s_cls = Counter()
        s_tools = 0
        for l in lines:
            try:
                d = json.loads(l)
            except Exception:
                continue
            if d.get("type") == "assistant" and not d.get("isSidechain"):
                for c in (d.get("message") or {}).get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_use":
                        s_tools += 1
                        name = c.get("name", "")
                        inp = c.get("input") or {}
                        if name == "Bash":
                            cmd = str(inp.get("command", ""))[:200]
                            cls = classify_turn(cmd, last_cmd_err, last_cmd,
                                                frozenset(written_paths))
                            s_cls[cls] += 1
                            pending[c.get("id")] = cmd
                            last_cmd, last_cmd_err = cmd, False
                            # v3: register bash write targets as read-back
                            # candidates (redirects and tee); /dev/* targets
                            # (2>/dev/null) are NEVER write targets: they
                            # poisoned the 7d recount with basename "null"
                            for m in BASH_WRITE_PATH.finditer(cmd):
                                p = os.path.expanduser(m.group(1))
                                if p.startswith(("/", "~", "./")) and \
                                   "&" not in p[:2] and \
                                   not p.startswith("/dev/"):
                                    written_paths.add(p)
                        else:
                            # v3: register this session's writes first (the
                            # read-back rule), then credit verification
                            if name in WRITE_TOOLS:
                                fp = os.path.expanduser(
                                    str(inp.get("file_path", "")))
                                if fp:
                                    written_paths.add(fp)
                            elif name in JIRA_WRITE_TOOLS:
                                k = str(inp.get("issueIdOrKey", ""))
                                if k:
                                    written_keys.add(k)
                            elif name in CONF_WRITE_TOOLS:
                                k = str(inp.get("pageId", ""))
                                if k:
                                    written_pages.add(k)
                            # v2/v3: verification-shaped MCP/Read calls credit
                            # the verification class instead of defaulting to
                            # productive (job traces, read-backs, KB checks);
                            # v3 adds own-write read-backs (Read of a file
                            # this session wrote, getJiraIssue of an issue
                            # this session posted to)
                            if name in JIRA_READ_TOOLS and \
                               str(inp.get("issueIdOrKey", "")) in written_keys:
                                s_cls["verification"] += 1
                            elif name in CONF_READ_TOOLS and \
                               str(inp.get("pageId", "")) in written_pages:
                                s_cls["verification"] += 1
                            elif name == "Read" and \
                               os.path.expanduser(str(inp.get("file_path", ""))) in written_paths:
                                s_cls["verification"] += 1
                            elif VERIFY_TOOL_SIG.search(name) or \
                               (name == "Read" and VERIFY_READ_SIG.search(str(inp.get("file_path", "")))):
                                s_cls["verification"] += 1
                            else:
                                s_cls["productive"] += 1
                            last_cmd_err = False
            elif d.get("type") == "user":
                for c in (d.get("message") or {}).get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "tool_result":
                        tid = c.get("tool_use_id")
                        if bool(c.get("is_error")):
                            s_cls["errored"] += 1
                            txt = str(c.get("content"))[:300]
                            if PERM_SIG.search(txt):
                                err_by_class["permission-denied"] += 1
                            elif STALE_SIG.search(txt):
                                err_by_class["stale-schema"] += 1
                            elif "Exit code" in txt:
                                err_by_class["bash-exit"] += 1
                            else:
                                err_by_class["other"] += 1
                            # if this was a bash cmd, mark for blind-retry detection
                            if tid in pending:
                                last_cmd_err = True
        if s_cls["productive"] + s_cls["verification"] + s_cls["waste"] + s_cls["poll"] < 3:
            continue
        sessions += 1
        for k in ("productive", "verification", "waste", "poll", "errored"):
            tot[k] += s_cls.get(k, 0)
        tot["tools"] += s_tools
        retries_poll += s_cls.get("poll", 0)
        retries_blind += s_cls.get("waste", 0)
        worst.append((s_cls["waste"] + s_cls["errored"], os.path.basename(f)[:12], dict(s_cls)))

# --- quality guard ----------------------------------------------------------
def _ts(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        try:
            import datetime
            return datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
        except Exception:
            return 0.0

def false_rate():
    v = KB / "claims" / "verifications.jsonl"
    if not v.exists():
        return None
    rows = [json.loads(x) for x in open(v) if x.strip()]
    recent = [r for r in rows if time.time() - _ts(r.get("ts", 0) or 0) < DAYS * 86400]
    if not recent:
        return None
    f = sum(1 for r in recent if str(r.get("verdict", "")).lower() == "false")
    return f, len(recent)

quality = {"false_claims": false_rate(),
           "regression": None}
reg = KB / "garden-reports" / "regression-latest.md"
if reg.exists() and time.time() - reg.stat().st_mtime < DAYS * 86400:
    txt = reg.read_text()
    m = re.search(r"(\d+)\s*/\s*(\d+)\s*(pass|fail)", txt, re.I)
    quality["regression"] = m.group(0) if m else "see file"

# --- report -----------------------------------------------------------------
n_turns = sum(tot[k] for k in ("productive", "verification", "waste", "poll"))
waste_rate = (tot["waste"] / n_turns * 100) if n_turns else 0
verif_rate = (tot["verification"] / n_turns * 100) if n_turns else 0
rep = [f"# Turn-discipline audit — last {DAYS} days ({sessions} sessions)", ""]
rep.append(f"| Metric | Value |\n|---|---|")
rep.append(f"| Assistant turns (classified) | {n_turns:,} |")
rep.append(f"| Productive | {tot['productive']:,} ({tot['productive']/max(n_turns,1)*100:.0f}%) |")
rep.append(f"| Verification (PROTECTED) | {tot['verification']:,} ({verif_rate:.0f}%) |")
rep.append(f"| WASTE (blind retries) | {tot['waste']:,} ({waste_rate:.1f}%) |")
rep.append(f"| Same-command polls (legit) | {tot['poll']:,} |")
rep.append(f"| Tool errors | {tot['errored']:,} |")
rep.append(f"| Error causes | {dict(err_by_class)} |")
rep.append(f"| Quality guard — false claims | {quality['false_claims']} |")
rep.append(f"| Quality guard — regression | {quality['regression']} |")
rep.append("")
rep.append("Worst sessions (waste+errors):")
for w, name, cls in sorted(worst, reverse=True)[:8]:
    rep.append(f"- {name}: waste={cls.get('waste',0)} errors={cls.get('errored',0)} "
               f"verif={cls.get('verification',0)} prod={cls.get('productive',0)}")
rep.append("")
rep.append(f"_Interpretation: waste = blind retries after errors. Permission/stale-schema errors")
rep.append(f"are rule-known failures (playbook); their fix is nudge hooks, not more rules._")

REPORT.parent.mkdir(parents=True, exist_ok=True)
REPORT.write_text("\n".join(rep))
with open(TREND, "a") as fh:
    fh.write(json.dumps({"ts": time.time(), "sessions": sessions, "turns": n_turns,
                         "waste_rate": round(waste_rate, 2), "verif_rate": round(verif_rate, 2),
                         "errors": tot["errored"], "quality": {k: str(v) for k, v in quality.items()},
                         "sig": SIG_VERSION,
                         "note": "sig v3 2026-10-27: recalibrated after cortex-detected drift "
                                 "(dream 2026-10-25). v1 13% was inflated by bare \\bkb\\b; v2 "
                                 "removed it but credited too narrow a slice (same corpus fell "
                                 "13%->2.76% with behavior steady). v3 credits the real "
                                 "verification shapes: wt CLI live probes (recipes get / jobs "
                                 "list / job-counts / fixture run), gcloud logging read, "
                                 "GET-only curl probes, verification-tier MCP tool suffixes "
                                 "(job traces, asset read-backs, slide visual QA), and "
                                 "own-write read-backs (Read/cat of a file this session wrote, "
                                 "getJiraIssue of an issue it posted to). Generic reads stay "
                                 "productive. Fixtures: scripts/turn-audit-fixtures.json "
                                 "(--selftest). Rows before 10-23 use v1, 10-23..now use v2"}) + "\n")
with open(BUS, "a") as fh:
    fh.write(json.dumps({"ts": time.time(), "agent": "turn-audit", "type": "report",
                         "subject": f"turn discipline {DAYS}d (sig v3 recalibrated 10-27): "
                                    f"waste {waste_rate:.1f}%, verif {verif_rate:.0f}%, "
                                    f"errors {tot['errored']}"},
                        ) + "\n")
print(f"turn-audit: {sessions} sessions, waste {waste_rate:.1f}%, verif {verif_rate:.0f}% -> {REPORT}")
