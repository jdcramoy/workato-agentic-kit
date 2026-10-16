#!/usr/bin/env python3
"""Fusion: same prompt to N gateway models, side-by-side verdicts (mechanics only).

The DECISION of whether to fuse lives in the fusion skill — this script is the
fan-out + diff. For tasks that need tools (file edits, recipe pulls), do NOT use
this script: spawn Agent-tool subagents with per-model models instead.

Usage:
  fusion-run.py --task-file /tmp/task.txt
  fusion-run.py --prompt "one-shot question" --models m1,m2 [--max-tokens 2048]
Writes one ledger row per model to knowledge/models-evals/fusion.jsonl and prints
a per-model block plus a naive agreement summary (exact-similarity heuristics;
the JUDGMENT of disagreement is the caller's — a session or Josh, never this script).
"""
import argparse, difflib, json, os, sys, time, urllib.request

BASE = "https://ai.preview.workato.com/v1"
LEDGER = os.path.expanduser("~/.claude/knowledge/models-evals/fusion.jsonl")
DEFAULT_MODELS = "fireworks/kimi-k3,baseten/kimi-k3,fireworks/glm-5.3-flash"


def token():
    return json.load(open(os.path.expanduser("~/.claude/settings.json")))["env"]["ANTHROPIC_AUTH_TOKEN"]


def chat(model, prompt, max_tokens, timeout=300):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": max_tokens}).encode()
    req = urllib.request.Request(f"{BASE}/chat/completions", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {token()}",
                                          "Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            d = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    msg = (d.get("choices") or [{}])[0].get("message", {})
    text = msg.get("content") or ""
    if not text.strip() and (msg.get("reasoning_content") or msg.get("reasoning")):
        return {"error": ("empty content: model's reasoning consumed --max-tokens before answering "
                          "(thinking models need headroom) — rerun with a higher cap"),
                "reasoning_len": len(msg.get("reasoning_content") or msg.get("reasoning") or ""),
                "wall_s": round(time.time() - t0, 2)}
    return {"text": text,
            "wall_s": round(time.time() - t0, 2),
            "prompt_tokens": d.get("usage", {}).get("prompt_tokens"),
            "completion_tokens": d.get("usage", {}).get("completion_tokens")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt")
    ap.add_argument("--task-file")
    ap.add_argument("--models", default=DEFAULT_MODELS)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--label-outcome", help="JSON file {prompt_sha, models, correct_models, labeled_by} — append outcome rows and exit (wave-3 amendment 6b)")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)

    if args.label_outcome:
        oc = json.load(open(args.label_outcome))
        with open(LEDGER, "a") as f:
            for m in oc["models"]:
                f.write(json.dumps({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "model": m,
                    "prompt_sha": oc["prompt_sha"],
                    "outcome": "correct" if m in oc["correct_models"] else "incorrect",
                    "labeled_by": oc.get("labeled_by", "unknown"),
                }) + "\n")
        print(f"labeled {len(oc['models'])} model(s) for prompt_sha {oc['prompt_sha']}")
        return

    prompt = args.prompt or (open(args.task_file).read() if args.task_file else None)
    if not prompt:
        sys.exit("need --prompt or --task-file")
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if len(models) < 2:
        sys.exit("fusion needs >=2 models")

    # stable cross-process prompt id — builtin hash() is process-randomized,
    # which made every pre-wave3 prompt_sha row unjoinable (integration find)
    import hashlib
    prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()[:16]

    results = {}
    for m in models:
        results[m] = chat(m, prompt, args.max_tokens)
        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "model": m, "prompt_sha": prompt_sha, **{k: v for k, v in results[m].items() if k != "text"}}
        with open(LEDGER, "a") as f:
            f.write(json.dumps(row) + "\n")

    texts = {}
    for m in models:
        r = results[m]
        print(f"\n===== {m} ({r.get('wall_s')}s, {r.get('completion_tokens')} out tokens)" + (f" ERROR: {r['error']}" if "error" in r else ""))
        if "text" in r:
            texts[m] = r["text"]
            print(r["text"][:4000])
            import os as _os
            _ansdir = _os.path.expanduser("~/.claude/knowledge/models-evals/answers")
            _os.makedirs(_ansdir, exist_ok=True)
            _fname = _os.path.join(_ansdir, f"{_os.environ.get('FUSION_RUN_ID','run')}-{m.replace('/','_')}.md")
            with open(_fname, "w") as _f:
                _f.write(r["text"])

    if len(texts) >= 2:
        keys = list(texts)
        print("\n===== pairwise similarity (difflib ratio, text-only heuristic) =====")
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                a, b = texts[keys[i]], texts[keys[j]]
                print(f"{keys[i]} vs {keys[j]}: {difflib.SequenceMatcher(None, a, b).ratio():.2f}")
        print("\nDISAGREEMENT IS A SIGNAL, NOT A BUG — the caller (session or Josh) judges which answer is right. Never average; pick or escalate.")


if __name__ == "__main__":
    main()
