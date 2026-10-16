#!/usr/bin/env python3
"""decisions.py — typed-judgment primitive for the harness (Decisions API pattern).

Rips off OpenAI's Decisions API CONTRACT (not the endpoint): shared evidence in,
a batch of typed questions out — predicate (probability), choice (argmax over
options), score (probability-weighted average over ordered levels) — served by
any gateway model the harness already pays for. Every call appends to the
decision ledger; outcomes close the loop; calibrate scores the model's own
probabilities (Brier/accuracy/MAE per surface+question). The queues
(decision-inbox, proposal-decide, triage-decide) decide NOTHING; this gives
them a cheap, comparable, logged judgment layer underneath.

  decisions.py decide --evidence FILE | --evidence-text "..." \
      --q 'name:predicate:instruction' \
      --q 'name:choice:instruction|opt1,opt2,...' \
      --q 'name:score:instruction|1-5' \
      [--surface proposal-prescreen] [--model baseten/deepseek-v4.1-flash]

  decisions.py outcome --id <id> --name <qname> --observed true|false|opt|N
  decisions.py calibrate [--surface S] [--window 30]
  decisions.py show [--id <id>] [--surface S] [--last N]

Ledger: knowledge/decisions/decisions.jsonl (append-only, atomic)
        knowledge/decisions/outcomes.jsonl (append-only, atomic)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from atomic_io import atomic_append  # noqa: E402

BASE = "https://ai.preview.workato.com/v1"
STORE = Path.home() / ".claude/knowledge/decisions/decisions.jsonl"
OUTCOMES = Path.home() / ".claude/knowledge/decisions/outcomes.jsonl"
DEFAULT_MODEL = "baseten/deepseek-v4.1-flash"  # cheap tier, vision-capable (playbook)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _token() -> str:
    env = json.load(open(os.path.expanduser("~/.claude/settings.json")))
    return env["env"]["ANTHROPIC_AUTH_TOKEN"]


def _parse_q(spec: str) -> dict:
    """'name:type:rest' where rest for choice/score is 'instruction|args'."""
    parts = spec.split(":", 2)
    if len(parts) < 3 or parts[1] not in ("predicate", "choice", "score"):
        raise SystemExit(f"bad --q spec (want name:type:instruction[|args]): {spec}")
    name, qtype, rest = parts
    q = {"name": name, "type": qtype}
    if qtype == "predicate":
        q["instruction"] = rest
    else:
        if "|" not in rest:
            raise SystemExit(f"bad --q {name}: {qtype} needs instruction|args")
        q["instruction"], args = rest.split("|", 1)
        if qtype == "choice":
            q["options"] = [o.strip() for o in args.split(",") if o.strip()]
        else:
            lo, _, hi = args.partition("-")
            q["levels"] = list(range(int(lo), int(hi) + 1))
    return q


def _ask(model: str, evidence: str, questions: list[dict], max_tokens: int) -> tuple[dict, dict]:
    levels = "\n".join(
        f'- {q["name"]} ({q["type"]}): {q["instruction"]}'
        + (f" options={q['options']}" if "options" in q else "")
        + (f" levels={q['levels']}" if "levels" in q else "")
        for q in questions)
    sys_prompt = (
        "You are a calibration-grade judge. Answer ONLY with a JSON object, no prose:\n"
        '{"answers": [{"name": <question name>, "probabilities": {<label>: <float 0-1>}}]}\n'
        "Rules: probabilities over EXACTLY the labels given, they must sum to ~1.0.\n"
        "- predicate questions: labels are \"true\" and \"false\".\n"
        "- choice questions: labels are the exact option strings.\n"
        "- score questions: labels are the level numbers as strings (\"1\", \"2\", ...).\n"
        "Be honest about uncertainty — spread probability rather than pretending certainty.")
    user = f"EVIDENCE:\n{evidence}\n\nQUESTIONS:\n{levels}"
    body = json.dumps({"model": model, "max_tokens": max_tokens, "temperature": 0,
                       "messages": [{"role": "system", "content": sys_prompt},
                                    {"role": "user", "content": user}]})
    req = urllib.request.Request(f"{BASE}/chat/completions", data=body.encode(), method="POST",
                                 headers={"Authorization": f"Bearer {_token()}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.load(r)
    text = resp["choices"][0]["message"]["content"]
    return _extract_json(text), resp.get("usage", {})


def _extract_json(text: str) -> dict:
    start = text.find("{")
    if start < 0:
        raise SystemExit(f"no JSON in judge response:\n{text[:400]}")
    depth = 0
    for i, ch in enumerate(text[start:], start):
        depth += (ch == "{") - (ch == "}")
        if depth == 0:
            return json.loads(text[start:i + 1])
    raise SystemExit(f"unbalanced JSON in judge response:\n{text[:400]}")


def _answers(questions: list[dict], raw: dict) -> list[dict]:
    by_name = {a.get("name"): a.get("probabilities", {}) for a in raw.get("answers", [])}
    out = []
    for q in questions:
        probs = {str(k): float(v) for k, v in by_name.get(q["name"], {}).items()}
        if not probs:
            raise SystemExit(f"judge returned no probabilities for '{q['name']}'")
        if q["type"] == "predicate":
            value = "true" if probs.get("true", 0) >= probs.get("false", 0) else "false"
            confidence = probs.get(value, 0.0)
        elif q["type"] == "choice":
            value = max(probs, key=probs.get)
            confidence = probs[value]
        else:  # score: probability-weighted average of level indices
            value = round(sum(float(k) * v for k, v in probs.items() if k in
                              {str(l) for l in q["levels"]}), 3)
            confidence = None
        out.append({"name": q["name"], "type": q["type"], "probabilities": probs,
                    "value": value, "confidence": confidence})
    return out


def cmd_decide(a):
    questions = [_parse_q(s) for s in a.q]
    if a.evidence_text:
        evidence, src = a.evidence_text, "inline"
    else:
        p = Path(a.evidence)
        evidence, src = p.read_text(), str(p)
    raw, usage = _ask(a.model, evidence, questions, a.max_tokens)
    answers = _answers(questions, raw)
    did = f"dec-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"
    rec = {"id": did, "ts": _now(), "surface": a.surface, "model": a.model,
           "evidence_src": src, "questions": questions, "answers": answers,
           "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens")}}
    atomic_append(STORE, rec)
    print(f"decision {did}  surface={a.surface}  model={a.model}")
    for ans in answers:
        conf = f"  conf={ans['confidence']:.2f}" if ans["confidence"] is not None else ""
        print(f"  {ans['name']:28s} [{ans['type']:9s}] -> {ans['value']}{conf}")
    print(f"  tokens: {rec['usage']}")


def cmd_outcome(a):
    if a.observed not in ("true", "false") and not _is_num(a.observed):
        # allow any choice label; numbers/bools are the calibratable kinds
        pass
    atomic_append(OUTCOMES, {"ts": _now(), "decision_id": a.id, "name": a.name,
                             "observed": _coerce(a.observed), "note": a.note or ""})
    print(f"outcome recorded: {a.id}/{a.name} = {a.observed}")


def _is_num(s):
    try:
        float(s)
        return True
    except ValueError:
        return False


def _coerce(s):
    if s in ("true", "false"):
        return s == "true"
    return float(s) if _is_num(s) else s


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def cmd_calibrate(a):
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=a.window)).isoformat(timespec="seconds")
    decisions = {r["id"]: r for r in _load(STORE) if r.get("ts", "") >= cutoff}
    # last-wins per (decision_id, name): a corrected observation supersedes
    # an earlier one (append-only store, compaction on read)
    seen_out: dict[tuple, dict] = {}
    for o in _load(OUTCOMES):
        if o.get("ts", "") >= cutoff:
            seen_out[(o["decision_id"], o["name"])] = o
    outcomes = list(seen_out.values())
    buckets: dict[tuple, list] = {}
    for o in outcomes:
        rec = decisions.get(o["decision_id"])
        if not rec:
            continue
        if a.surface and rec.get("surface") != a.surface:
            continue
        ans = next((x for x in rec["answers"] if x["name"] == o["name"]), None)
        if not ans:
            continue
        buckets.setdefault((rec.get("surface", "?"), o["name"], ans["type"]), []).append((ans, o["observed"]))
    if not buckets:
        print(f"no closed outcomes in the last {a.window}d" + (f" for surface={a.surface}" if a.surface else ""))
        return
    print(f"{'surface':22s} {'question':24s} {'type':10s} {'n':>3s} {'metric':>8s}  detail")
    for (surface, name, qtype), pairs in sorted(buckets.items()):
        if qtype == "predicate":
            brier = sum((x["probabilities"].get("true", 0) - (1 if obs else 0)) ** 2
                        for x, obs in pairs)
            acc = sum(1 for x, obs in pairs if (x["probabilities"].get("true", 0) > 0.5) == obs) / len(pairs)
            print(f"{surface:22s} {name:24s} {qtype:10s} {len(pairs):3d} {acc:8.2f}  brier={brier/len(pairs):.3f}")
        elif qtype == "choice":
            acc = sum(1 for x, obs in pairs if x["value"] == str(obs)) / len(pairs)
            print(f"{surface:22s} {name:24s} {qtype:10s} {len(pairs):3d} {acc:8.2f}  argmax-accuracy")
        else:
            mae = sum(abs(x["value"] - float(obs)) for x, obs in pairs) / len(pairs)
            print(f"{surface:22s} {name:24s} {qtype:10s} {len(pairs):3d} {mae:8.2f}  MAE (lower=better)")


def cmd_show(a):
    rows = _load(STORE)
    if a.surface:
        rows = [r for r in rows if r.get("surface") == a.surface]
    if a.id:
        rows = [r for r in rows if r["id"] == a.id]
    for r in rows[-(a.last or 5):]:
        print(f"{r['id']}  {r['ts']}  surface={r['surface']}")
        for ans in r["answers"]:
            print(f"  {ans['name']:28s} -> {ans['value']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("decide")
    d.add_argument("--evidence"); d.add_argument("--evidence-text")
    d.add_argument("--q", action="append", required=True)
    d.add_argument("--surface", default="ad-hoc"); d.add_argument("--model", default=DEFAULT_MODEL)
    d.add_argument("--max-tokens", type=int, default=800)
    o = sub.add_parser("outcome")
    o.add_argument("--id", required=True); o.add_argument("--name", required=True)
    o.add_argument("--observed", required=True); o.add_argument("--note")
    c = sub.add_parser("calibrate")
    c.add_argument("--surface"); c.add_argument("--window", type=int, default=30)
    s = sub.add_parser("show")
    s.add_argument("--id"); s.add_argument("--surface"); s.add_argument("--last", type=int, default=5)
    a = ap.parse_args()
    {"decide": cmd_decide, "outcome": cmd_outcome, "calibrate": cmd_calibrate, "show": cmd_show}[a.cmd](a)


if __name__ == "__main__":
    main()
