#!/usr/bin/env python3
"""backtest-jevish4.py — iteration 4: the FACTORIZED cascade (levers 1+2+5).

Spike findings that shaped this:
- spike 1 (text-only): ensemble voting sharpens correlated blindness (0.49 <
  single 0.61); calibration fixes ECE not discrimination.
- spike 3 (state): state assembly is the biggest lever (0.61 -> 0.71); urgency
  inversion is anchor-level — severity rubrics always invert.
- dissenter: the verdict function is "fresh? mine? not covered?" — most of
  that is STATE, not judgment.

This iteration decomposes the verdict (lever 1): the rules layer
(triage_state.factors) settles fresh/covered/mine deterministically; the model
judges ONLY the residue — "valuable?" — plus decay-urgency ("does the cost of
ignoring this grow within a week?", replacing the inverted severity rubric).
Levers 2/5 arrive as arms: +precedents (BM25 k-NN over past verdicts with
Josh's notes), +kimi (stronger judge), +cot (reason against state before
answering), +full stack.

Arms (same 79 labeled findings, verdict-time state, as-of precedents):
  rules-composite      factors only, no model calls
  cascade->flash       rules settle; flash judges candidates
  +precedents          + 3 nearest past verdicts in context
  +kimi                baseten/kimi-k3 as the judge
  +cot                 reasoning-before-answer decode
  +full                kimi + cot + precedents
  +full+iso            cross-fitted isotonic on the full stack

  backtest-jevish4.py --limit 3   # smoke
  backtest-jevish4.py             # full run

Ledger: knowledge/decisions/backtest-jevish4.jsonl (append-only).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import importlib.util
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import decisions as D  # noqa: E402
from atomic_io import atomic_append  # noqa: E402


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parent / filename)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


J1 = _load("jevish1", "backtest-jevish.py")      # metrics, crossfit, labeled
TS = _load("triage_state", "triage-state.py")    # state_block, factors, render
PREC = _load("precedent", "precedent.py")        # PrecedentIndex

OUT = Path.home() / ".claude/knowledge/decisions/backtest-jevish4.jsonl"
FLASH = "baseten/deepseek-v4.1-flash"
KIMI = "baseten/kimi-k3"

JUDGE_SYS = (
    "You are a narrow judgment module inside a decision cascade. A rules layer "
    "has ALREADY established that this finding is fresh (not previously "
    "decided), uncovered (no sibling/ticket handles it), and in Josh's lane. "
    "Those questions are settled — do not relitigate them. You judge only what "
    "remains.\n"
    "Answer ONLY with one JSON object, no prose, no markdown:\n"
    '{"p_valuable": <float 0-1>, "decay_urgency": <int 1-5>}\n'
    "- p_valuable: probability that Josh would consider acting on this finding "
    "a genuinely valuable use of attention (not noise, not hygiene-for-hygiene, "
    "not something with no real consequence).\n"
    "- decay_urgency: if NOBODY acts on this for 7 days, how much does the cost "
    "grow? 1 = flat (pure hygiene, waitable), 2 = mild, 3 = noticeable "
    "accumulation, 4 = compounds fast (blocks others, externally visible), "
    "5 = incident risk / external deadline. Judge DECAY, not loudness: a "
    "screaming alert about something already handled is 1.")

COT_SYS = JUDGE_SYS.replace(
    "Answer ONLY with one JSON object, no prose, no markdown:",
    "First reason briefly (2-4 sentences) against the STATE and PAST VERDICTS "
    "sections — what cuts for and against this being valuable. Then end with a "
    "final line of the form:\nANSWER: ")


def _post(model, sys_p, user_p, max_tokens=1500, temperature=0.0):
    body = json.dumps({"model": model, "max_tokens": max_tokens,
                       "temperature": temperature,
                       "messages": [{"role": "system", "content": sys_p},
                                    {"role": "user", "content": user_p}]})
    req = urllib.request.Request(
        f"{D.BASE}/chat/completions", data=body.encode(), method="POST",
        headers={"Authorization": f"Bearer {D._token()}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.load(r)


def _parse_answer(text):
    m = re.findall(r"ANSWER:\s*(\{[^{}]*\})", text)
    j = json.loads(m[-1]) if m else D._extract_json(text)
    p = float(j["p_valuable"])
    u = int(float(j["decay_urgency"]))
    if not (0.0 <= p <= 1.0 and 1 <= u <= 5):
        raise ValueError(f"out of range: {j}")
    return p, u


def judge(model, cot, evidence_text):
    last_err = None
    for _ in range(2):
        try:
            resp = _post(model, COT_SYS if cot else JUDGE_SYS, evidence_text,
                         max_tokens=1500 if not cot else 2000)
            msg = resp["choices"][0]["message"]
            text = msg.get("content") or ""
            if not text.strip() and msg.get("reasoning_content"):
                text = msg["reasoning_content"]
            p, u = _parse_answer(text)
            return {"p": p, "urg": u, "usage": resp.get("usage", {})}
        except (Exception, SystemExit) as e:
            last_err = e
            time.sleep(2)
    return {"error": str(last_err)[:150], "usage": {}}


def build_evidence(r, by_slug, pindex):
    state = TS.state_block(r["slug"], r, by_slug)
    fac = TS.factors(state, r.get("source", ""))
    ev = J1.BT.evidence(r) + "\n\n" + TS.render(state)
    prec_hits = pindex.query(
        " ".join(str(r.get(k, "")) for k in ("slug", "title", "evidence", "work")),
        exclude_slug=r["slug"], as_of=state["as_of"], k=3)
    ev_prec = ev + "\n\n" + PREC.PrecedentIndex.render(prec_hits)
    return state, fac, ev, ev_prec


def process(rec_label, by_slug, pindex):
    r, label = rec_label
    state, fac, ev, ev_prec = build_evidence(r, by_slug, pindex)
    row = {"ts": D._now(), "slug": r["slug"], "label": label,
           "source": r.get("source", ""),
           "factors": {k: fac[k] for k in ("fresh", "covered", "mine", "candidate")},
           "n_precedents": 0, "judges": {}}
    tokens = {}
    if fac["candidate"]:
        specs = [("flash", FLASH, False, ev), ("flash_prec", FLASH, False, ev_prec),
                 ("kimi", KIMI, False, ev), ("flash_cot", FLASH, True, ev),
                 ("full", KIMI, True, ev_prec)]
        for name, model, cot, evid in specs:
            res = judge(model, cot, evid)
            u = res.get("usage", {})
            t = tokens.setdefault(model, [0, 0])
            t[0] += u.get("prompt_tokens", 0)
            t[1] += u.get("completion_tokens", 0)
            if "p" in res:
                row["judges"][name] = {"p": res["p"], "urg": res["urg"]}
            else:
                row["judges"][name] = {"error": res["error"]}
        if "flash_prec" in row["judges"] and "p" in row["judges"]["flash_prec"]:
            row["n_precedents"] = ev_prec.count("PAST VERDICTS") and 3
    atomic_append(OUT, row)
    return row, tokens


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    data = J1.labeled()
    if a.limit:
        data = data[:a.limit]
    qrows = [json.loads(l) for l in
             Path.home().joinpath(".claude/knowledge/triage/queue.jsonl")
             .read_text().splitlines() if l.strip()]
    by_slug = TS.build_index(qrows)
    pindex = PREC.PrecedentIndex(qrows)
    print(f"labeled: {len(data)} ({sum(l for _, l in data)} accepted); "
          f"precedent index: {len(pindex.docs)} decided rows", flush=True)

    rows, tokens = [], {}
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(process, rl, by_slug, pindex) for rl in data]
        for f in cf.as_completed(futs):
            row, tk = f.result()
            rows.append(row)
            for m, (pi, po) in tk.items():
                t = tokens.setdefault(m, [0, 0])
                t[0] += pi
                t[1] += po
            print(f"  {row['slug'][:50]:50s} y={row['label']} "
                  f"cand={int(row['factors']['candidate'])} "
                  + " ".join(f"{k}={v.get('p', 'ERR') if not isinstance(v.get('p'), float) else round(v['p'],2)}"
                             for k, v in row["judges"].items()), flush=True)

    ys = [r["label"] for r in rows]
    cand = [r for r in rows if r["factors"]["candidate"]]
    settled = [r for r in rows if not r["factors"]["candidate"]]
    print(f"\nrules layer: {len(settled)}/{len(rows)} settled by factors "
          f"(acc on settled: "
          f"{sum(1 for r in settled if not r['label'])/max(1,len(settled)):.2f} "
          f"reject-accuracy); residue {len(cand)} rows "
          f"({sum(r['label'] for r in cand)} accepted, "
          f"{sum(r['label'] for r in cand)/max(1,len(cand)):.0%} base rate)")

    def cascade(jkey, default=0.05):
        ps, yy = [], []
        for r in rows:
            if not r["factors"]["candidate"]:
                ps.append(0.05)
            else:
                j = r["judges"].get(jkey, {})
                if "p" not in j:
                    continue
                ps.append(j["p"])
            yy.append(r["label"])
        return ps, yy

    arms = {"rules-composite": ([0.9 if r["factors"]["candidate"] else 0.1
                                 for r in rows], ys)}
    for jkey, label in (("flash", "cascade->flash"), ("flash_prec", "+precedents"),
                        ("kimi", "+kimi"), ("flash_cot", "+cot"),
                        ("full", "+full")):
        ps, yy = cascade(jkey)
        if ps:
            arms[label] = (ps, yy)
    if arms.get("+full"):
        full_rows = [r for r in rows if r["factors"]["candidate"]
                     and "p" in r["judges"].get("full", {})]
        if full_rows:
            iso = J1.crossfit([{**r, "p": r["judges"]["full"]["p"]}
                               for r in full_rows], "p")
            arms["+full+iso"] = ([iso[r["slug"]] if r["factors"]["candidate"]
                                  else 0.05 for r in rows
                                  if r["slug"] in iso or not r["factors"]["candidate"]],
                                 [r["label"] for r in rows
                                  if r["slug"] in iso or not r["factors"]["candidate"]])

    print(f"\n{'arm':22s} {'n':>3s} {'acc':>6s} {'brier':>7s} {'ece':>6s} {'auroc':>6s}")
    for name, (ps, yy) in arms.items():
        acc, br, ec, au = J1.metrics(ps, yy)
        gate = "  GATE-OK" if acc >= 0.8 else ""
        print(f"{name:22s} {len(ps):3d} {acc:6.2f} {br:7.3f} {ec:6.3f} {au:6.2f}{gate}")

    print("\njudge-only accuracy on the residue (candidates):")
    for jkey in ("flash", "flash_prec", "kimi", "flash_cot", "full"):
        sub = [r for r in cand if "p" in r["judges"].get(jkey, {})]
        if sub:
            acc = sum(1 for r in sub
                      if (r["judges"][jkey]["p"] > 0.5) == bool(r["label"])) / len(sub)
            print(f"  {jkey:11s}: {acc:.2f} (n={len(sub)}, "
                  f"{sum(r['label'] for r in sub)} accepted)")

    print("\ndecay-urgency separation on candidates (accepted vs rejected):")
    for jkey in ("flash", "full"):
        sub = [r for r in cand if "urg" in r["judges"].get(jkey, {})]
        pos = [r["judges"][jkey]["urg"] for r in sub if r["label"]]
        neg = [r["judges"][jkey]["urg"] for r in sub if not r["label"]]
        if pos and neg:
            verdict = "INVERTED" if sum(pos)/len(pos) < sum(neg)/len(neg) else "ok"
            print(f"  {jkey:11s}: {sum(pos)/len(pos):.2f} vs "
                  f"{sum(neg)/len(neg):.2f}  ({verdict})")

    print("\nconfident-FALSE (p<0.2) accepted share:")
    for name, (ps, yy) in arms.items():
        sub = [(p, y) for p, y in zip(ps, yy) if p < 0.2]
        if sub:
            print(f"  {name:22s}: n={len(sub)} accepted={sum(y for _, y in sub)}"
                  f" ({sum(y for _, y in sub)/len(sub):.2f})")

    print("\nreference: spike1 single=0.61 ens=0.49 | spike3 single+state=0.71 "
          "rule=0.81 cascade=0.77 | urgency INVERTED in all prior judge arms")

    print("\nest. cost:")
    price = {"deepseek": (0.22, 0.66), "glm": (0.15, 0.50), "kimi": (3.00, 15.00)}
    total = 0.0
    for m, (pi, po) in tokens.items():
        pr = next(v for k, v in price.items() if k in m)
        c = pi / 1e6 * pr[0] + po / 1e6 * pr[1]
        total += c
        print(f"  {m:28s} {pi:>9,} in / {po:>8,} out  ~= ${c:.4f}")
    print(f"  {'TOTAL':28s} {'':>22s} ~= ${total:.4f}")


if __name__ == "__main__":
    main()
