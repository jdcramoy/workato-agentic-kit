#!/usr/bin/env python3
"""backtest-jevish.py — spike: Jev-style calibrated judgment WITHOUT the licensed model.

Jev (TypeSafe System One) sells one hard thing: probability distributions over typed
answers, trained/calibrated against outcomes. Its `confidence` is just arithmetic on
the distribution. This spike replaces the trained model with:
  raw distribution  = empirical vote share from a diverse N=5 panel
                      (2 cheap models x 2 providers x 3 phrasings, single-label answers
                       — no verbalized probabilities),
  calibration       = isotonic regression fit CROSS-FITTED (5-fold, folds by md5(slug))
                      on Josh's historical triage verdicts — never fit on scored rows.

Arms (all scored on the CURRENT last-wins labels, exemplars excluded):
  majority        always-reject baseline
  source-rule     dissenter's one-liner: workato-health/ops-visibility -> reject,
                  josh/cortex -> accept, else majority
  single          decisions.py-style single call, verbalized probabilities (temp 0)
  single+iso      single, cross-fitted isotonic on top
  ensemble        N=5 vote-share distribution
  ensemble+iso    ensemble, cross-fitted isotonic on top

Metrics: acc@0.5, Brier, ECE(10 bins), AUROC, urgency separation (accepted vs rejected),
confident-FALSE label mix (p<0.2), jira-autotriage within-source discrimination.

  backtest-jevish.py --limit 2   # smoke
  backtest-jevish.py             # full run (79 findings x 6 calls)

Ledger: knowledge/decisions/backtest-jevish.jsonl (append-only, one row per finding).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import importlib.util
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import decisions as D  # noqa: E402  (gateway _ask, _answers, _now)
from atomic_io import atomic_append  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "btmod", Path(__file__).parent / "backtest-decisions.py")
BT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BT)  # reuses QS (iteration-2 questions) + evidence()

QUEUE = Path.home() / ".claude/knowledge/triage/queue.jsonl"
OUT = Path.home() / ".claude/knowledge/decisions/backtest-jevish.jsonl"
EXCLUDE = {"gym-canon-auto-close-deleted-recipes", "bsys-29438-ae-freshdesk-plan-ready"}
SINGLE_MODEL = "baseten/deepseek-v4.1-flash"

# 5-vote panel: (model, phrasing). Phrasing+provider+model diversity; temp 0.7
# for within-cell stochasticity. glm thinking models need max_tokens >= 1500.
VOTES = [
    ("baseten/deepseek-v4.1-flash", "A"),
    ("fireworks/deepseek-v4.1-flash", "B"),
    ("fireworks/glm-5.3-flash", "A"),
    ("baseten/deepseek-v4.1-flash", "C"),
    ("fireworks/glm-5.3-flash", "B"),
]

PRED_PHRASING = {
    "A": ("Is this finding FRESH and still unaddressed — describing work that has NOT "
          "already been done, superseded, or covered through another channel (Jira "
          "ticket, other agent, later fix)? Set worth_surfacing=false if the finding is "
          "stale, a duplicate of an already-handled issue, or its own text says the work "
          "is done or planned elsewhere ('plan ready', 'root cause found', 'superseded', "
          "'awaiting X'). Set true only if acting on it now would not duplicate "
          "existing work."),
    "B": ("Is this finding STALE or already covered — work done, superseded, duplicated "
          "elsewhere, or already routed to another channel (Jira, another agent, a later "
          "fix)? If stale or covered, set worth_surfacing=false. Set true only for fresh "
          "findings where acting now duplicates nothing."),
    "C": ("Imagine someone acted on this finding right now. Would they be redoing work "
          "that is already done, already planned, or owned by another channel? If yes, "
          "set worth_surfacing=false. If acting now adds genuinely new value, set true."),
}

URGENCY_RUBRIC = ("Also set urgency, an integer 1-5: 1=cosmetic/hygiene, "
                  "2=nice-to-have, 3=worth doing soon, 4=should schedule this week, "
                  "5=drop everything / live incident risk.")

VOTE_SYS = (
    "You are a fast judgment module. Answer ONLY with one JSON object, no prose, no "
    'markdown: {"worth_surfacing": "true" or "false", "urgency": <integer 1-5>}. '
    "Commit to a single answer; do not hedge, do not explain.")

# ----------------------------------------------------------------------------- helpers


def labeled():
    rows = {}
    for line in QUEUE.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("slug"):
            rows[r["slug"]] = r  # last row wins (fixed post-dissenter)
    return [(r, 1 if r["status"] == "accepted" else 0)
            for r in rows.values()
            if r.get("status") in ("accepted", "rejected")
            and r["slug"] not in EXCLUDE]


def _post(model, sys_p, user_p, max_tokens=1500, temperature=0.7):
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


def vote(model, phrasing, evidence_text):
    user = (f"EVIDENCE:\n{evidence_text}\n\nQUESTION 1: {PRED_PHRASING[phrasing]}\n"
            f"QUESTION 2: {URGENCY_RUBRIC}")
    last_err = None
    for _ in range(2):
        try:
            resp = _post(model, VOTE_SYS, user)
            msg = resp["choices"][0]["message"]
            text = msg.get("content") or ""
            if not text.strip() and msg.get("reasoning_content"):
                text = msg["reasoning_content"]  # glm thinking-then-answer
            j = D._extract_json(text)
            ws = str(j.get("worth_surfacing", "")).strip().lower()
            urg = int(float(j.get("urgency")))
            if ws not in ("true", "false") or not 1 <= urg <= 5:
                raise ValueError(f"bad vote payload: {j}")
            return {"ws": ws == "true", "urgency": urg,
                    "usage": resp.get("usage", {})}
        except (Exception, SystemExit) as e:  # vote-level fault isolation
            # (decisions.py raises SystemExit on unparseable judge output)
            last_err = e
            time.sleep(2)
    return {"error": str(last_err)[:200], "usage": {}}


def single_call(model, evidence_text):
    raw, usage = D._ask(model, evidence_text, BT.QS, 2000)
    answers = D._answers(BT.QS, raw)
    p = next(a for a in answers if a["name"] == "worth_surfacing")["probabilities"].get("true", 0.0)
    urg = next(a for a in answers if a["name"] == "urgency")["value"]
    return p, urg, usage


# ------------------------------------------------------- calibration / metrics (stdlib)


def isotonic_fit(ps, ys):
    """PAV: returns block boundaries [(x_lo, x_hi, g)] of the fitted step function."""
    pts = sorted(zip(ps, ys))
    xs = [p for p, _ in pts]
    gs = [float(y) for _, y in pts]
    ws = [1.0] * len(gs)
    blocks = [[xs[i], xs[i], gs[i], ws[i]] for i in range(len(xs))]  # lo,hi,mean,w
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][2] > blocks[i + 1][2] + 1e-12:
            w = blocks[i][3] + blocks[i + 1][3]
            m = (blocks[i][2] * blocks[i][3] + blocks[i + 1][2] * blocks[i + 1][3]) / w
            blocks[i:i + 2] = [[blocks[i][0], blocks[i + 1][1], m, w]]
            i = max(0, i - 1)
        else:
            i += 1
    return [(b[0], b[1], b[2]) for b in blocks]


def isotonic_apply(blocks, p):
    if not blocks:
        return p
    if p <= blocks[0][0]:
        return blocks[0][2]
    if p >= blocks[-1][1]:
        return blocks[-1][2]
    for lo, hi, g in blocks:
        if lo <= p <= hi:
            return g
    for i in range(len(blocks) - 1):  # gap between blocks: linear interp
        if blocks[i][1] < p < blocks[i + 1][0]:
            x0, x1, g0, g1 = blocks[i][1], blocks[i + 1][0], blocks[i][2], blocks[i + 1][2]
            return g0 + (g1 - g0) * (p - x0) / (x1 - x0)
    return blocks[-1][2]


def crossfit(items, key):
    """items: [{slug,label,key:p_raw}]; returns {slug: calibrated p} via 5-fold PAV."""
    folds = {}
    for it in items:
        folds.setdefault(int(hashlib.md5(it["slug"].encode()).hexdigest(), 16) % 5,
                         []).append(it)
    out = {}
    for f, held in folds.items():
        train = [it for ff, its in folds.items() if ff != f for it in its]
        blocks = isotonic_fit([it[key] for it in train], [it["label"] for it in train])
        for it in held:
            out[it["slug"]] = isotonic_apply(blocks, it[key])
    return out


def ece(ps, ys, bins=10):
    tot = len(ps)
    e = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, p in enumerate(ps) if lo <= p < hi or (b == bins - 1 and p == 1.0)]
        if idx:
            conf = sum(ps[i] for i in idx) / len(idx)
            acc = sum(ys[i] for i in idx) / len(idx)
            e += len(idx) / tot * abs(acc - conf)
    return e


def auroc(ps, ys):
    pos = sorted(p for p, y in zip(ps, ys) if y == 1)
    n_pos, n_neg = len(pos), sum(1 for y in ys if y == 0)
    if not n_pos or not n_neg:
        return float("nan")
    import bisect
    wins = sum(bisect.bisect_left(pos, p) + (pos.count(p) / 2 if p in pos else 0)
               for p, y in zip(ps, ys) if y == 0)
    # ties: count equal pairs as 0.5
    from collections import Counter
    posc = Counter(pos)
    wins = 0.0
    for p, y in zip(ps, ys):
        if y == 0:
            wins += bisect.bisect_left(pos, p) + 0.5 * posc.get(p, 0)
    return 1.0 - wins / (n_pos * n_neg)


def metrics(ps, ys):
    n = len(ps)
    acc = sum(1 for p, y in zip(ps, ys) if (p > 0.5) == bool(y)) / n
    brier = sum((p - y) ** 2 for p, y in zip(ps, ys)) / n
    return acc, brier, ece(ps, ys), auroc(ps, ys)


# ----------------------------------------------------------------------------- run


def process(rec_label):
    r, label = rec_label
    ev = BT.evidence(r)
    votes, vusage = [], []
    for model, phr in VOTES:
        v = vote(model, phr, ev)
        votes.append(v)
        vusage.append((model, v.get("usage", {})))
    ok = [v for v in votes if "ws" in v]
    try:
        p_single, u_single, susage = single_call(SINGLE_MODEL, ev)
    except (Exception, SystemExit) as e:
        p_single, u_single, susage = None, None, {}
        print(f"  WARN single-call failed for {r['slug']}: {str(e)[:120]}", flush=True)
    row = {"ts": D._now(), "slug": r["slug"], "label": label,
           "source": r.get("source", ""), "votes": [
               {k: v[k] for k in ("ws", "urgency") if k in v} |
               ({"error": v["error"]} if "error" in v else {})
               for v in votes],
           "p_single": p_single, "urg_single": u_single}
    if len(ok) >= 3:
        row["p_ens"] = sum(1 for v in ok if v["ws"]) / len(ok)
        row["urg_ens"] = sum(v["urgency"] for v in ok) / len(ok)
        row["n_votes"] = len(ok)
    atomic_append(OUT, row)
    tokens = {}
    for model, u in vusage + [(SINGLE_MODEL, susage)]:
        t = tokens.setdefault(model, [0, 0])
        t[0] += u.get("prompt_tokens", 0)
        t[1] += u.get("completion_tokens", 0)
    return row, tokens


def source_rule(src):
    s = (src or "").split(":")[0]
    if s in ("workato-health", "ops-visibility"):
        return 0.0
    if s in ("josh", "cortex"):
        return 1.0
    return None  # abstain -> caller substitutes majority


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    data = labeled()
    if a.limit:
        data = data[:a.limit]
    print(f"labeled findings: {len(data)} ({sum(l for _, l in data)} accepted / "
          f"{sum(1 for _, l in data if not l)} rejected); exemplars excluded: "
          f"{sorted(EXCLUDE)}", flush=True)

    rows, tokens = [], {}
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for row, tk in ex.map(process, data):
            rows.append(row)
            for m, (pi, po) in tk.items():
                t = tokens.setdefault(m, [0, 0])
                t[0] += pi
                t[1] += po
            print(f"  {row['slug'][:52]:52s} label={row['label']} "
                  f"p_single={row['p_single']:.2f} "
                  f"p_ens={row.get('p_ens', float('nan')):.2f}", flush=True)

    ys = [r["label"] for r in rows]
    ens = [r for r in rows if "p_ens" in r]
    sng = [r for r in rows if r.get("p_single") is not None]
    maj = sum(ys) / len(ys)
    majority_p = [1.0 if maj > 0.5 else 0.0] * len(ys)

    # isotonic cross-fit (on its own arm's raw probabilities)
    iso_single = crossfit([{**r, "p": r["p_single"]} for r in sng], "p")
    iso_ens = crossfit([{**r, "p": r["p_ens"]} for r in ens], "p")

    arms = {
        "majority(always-reject)": (majority_p, ys),
        "source-rule(+majority)": ([(source_rule(r["source"]) if source_rule(r["source"])
                                     is not None else majority_p[0]) for r in rows], ys),
        "single verbalized": ([r["p_single"] for r in sng],
                              [r["label"] for r in sng]),
        "single+isotonic": ([iso_single[r["slug"]] for r in sng],
                            [r["label"] for r in sng]),
        "ensemble votes (N=5)": ([r["p_ens"] for r in ens], [r["label"] for r in ens]),
        "ensemble+isotonic": ([iso_ens[r["slug"]] for r in ens],
                              [r["label"] for r in ens]),
    }

    print(f"\n{'arm':26s} {'n':>3s} {'acc':>6s} {'brier':>7s} {'ece':>6s} {'auroc':>6s}")
    for name, (ps, yy) in arms.items():
        acc, br, ec, au = metrics(ps, yy)
        print(f"{name:26s} {len(ps):3d} {acc:6.2f} {br:7.3f} {ec:6.3f} {au:6.2f}")

    print("\nurgency separation (accepted mean vs rejected mean):")
    for name, ukey in (("single", "urg_single"), ("ensemble", "urg_ens")):
        sub = [r for r in rows if r.get(ukey) is not None]
        pos = [r[ukey] for r in sub if r["label"]]
        neg = [r[ukey] for r in sub if not r["label"]]
        if not pos or not neg:
            print(f"  {name:9s}: n/a (one-sided slice)")
            continue
        print(f"  {name:9s}: {sum(pos)/len(pos):.2f} vs {sum(neg)/len(neg):.2f}"
              f"  ({'INVERTED' if sum(pos)/len(pos) < sum(neg)/len(neg) else 'ok'})")

    print("\nconfident-FALSE region (p<0.2) label mix — accepted share (lower=better):")
    for name, pkey in (("single", "p_single"), ("ensemble", "p_ens"),
                       ("ens+iso", None)):
        if pkey:
            sub = [(r[pkey], r["label"]) for r in rows
                   if r.get(pkey) is not None and r[pkey] < 0.2]
        else:
            sub = [(iso_ens[r["slug"]], r["label"]) for r in ens
                   if iso_ens[r["slug"]] < 0.2]
        if sub:
            print(f"  {name:9s}: n={len(sub)}  accepted={sum(y for _, y in sub)}"
                  f" ({sum(y for _, y in sub)/len(sub):.2f})")

    ja = [r for r in rows if (r["source"] or "").startswith("jira-autotriage")]
    if ja:
        js = [r for r in ja if r.get("p_single") is not None]
        acc_s = (sum(1 for r in js if (r["p_single"] > 0.5) == bool(r["label"]))
                 / len(js)) if js else float("nan")
        sub = [r for r in ja if "p_ens" in r]
        acc_e = (sum(1 for r in sub if (r["p_ens"] > 0.5) == bool(r["label"]))
                 / len(sub)) if sub else float("nan")
        print(f"\njira-autotriage within-source acc: single={acc_s:.2f} "
              f"ensemble={acc_e:.2f} (n={len(ja)}, "
              f"{sum(r['label'] for r in ja)} accepted)")

    print("\nest. cost (rate card):")
    price = {"deepseek": (0.22, 0.66), "glm": (0.15, 0.50)}
    total = 0.0
    for m, (pi, po) in tokens.items():
        pr = price["deepseek"] if "deepseek" in m else price["glm"]
        c = pi / 1e6 * pr[0] + po / 1e6 * pr[1]
        total += c
        print(f"  {m:32s} {pi:>9,} in / {po:>8,} out  ~= ${c:.4f}")
    print(f"  {'TOTAL':32s} {'':>22s} ~= ${total:.4f}")


if __name__ == "__main__":
    main()
