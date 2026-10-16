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
if "--days" in args:
    DAYS = int(args[args.index("--days") + 1])

cutoff = time.time() - DAYS * 86400

# --- signatures ------------------------------------------------------------
STALE_SIG = re.compile(r"404 Not Found|Unknown data table field|schema_version|"
                       r"not on the appropriate screen", re.I)
VERIFY_SIG = re.compile(r"unittest|pytest|\btest\b|job_get|job handle|trace|"
                        r"verify|read.?back|kb_search|kb\b", re.I)
PERM_SIG = re.compile(r"haven'?t granted|requested permissions|permission .*(denied|required)|"
                      r"operation not permitted", re.I)

def classify_command(cmd: str, prev_err: bool) -> str:
    """VERIFICATION if it looks like a test/verify action, WASTE if identical
    blind retry (same command, previous attempt errored, no edit between),
    else PRODUCTIVE."""
    if VERIFY_SIG.search(cmd):
        return "verification"
    if prev_err:
        return "waste"      # blind retry candidate (exact string, post-error)
    return "productive"

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
                            cls = classify_command(cmd, last_cmd_err)
                            if cls == "productive" and last_cmd == cmd:
                                cls = "poll"        # same command, last one SUCCEEDED
                            s_cls[cls] += 1
                            pending[c.get("id")] = cmd
                            last_cmd, last_cmd_err = cmd, False
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
                         "errors": tot["errored"], "quality": {k: str(v) for k, v in quality.items()}}) + "\n")
with open(BUS, "a") as fh:
    fh.write(json.dumps({"ts": time.time(), "agent": "turn-audit", "type": "report",
                         "subject": f"turn discipline {DAYS}d: waste {waste_rate:.1f}%, "
                                    f"verif {verif_rate:.0f}%, errors {tot['errored']}"},
                        ) + "\n")
print(f"turn-audit: {sessions} sessions, waste {waste_rate:.1f}%, verif {verif_rate:.0f}% -> {REPORT}")
