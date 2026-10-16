#!/usr/bin/env python3
"""Model benchmark for the Workato AI gateway (~/knowledge/scripts/model-bench.py).

Sends fixed probes to gateway models via POST /v1/chat/completions (streaming),
measures TTFT / total wall / tok-s / token usage, appends one JSONL row per run
to ~/.claude/knowledge/models-evals/bench.jsonl.

Usage:
  model-bench.py                          # default shortlist, 3 runs, 2 probes
  model-bench.py --models fireworks/kimi-k3,baseten/kimi-k3 --runs 1
  model-bench.py --list                   # list available models and exit
Pricing has no gateway endpoint yet; token counts are logged so cost can be
derived later (or pass --prices '{"model": {"in": x, "out": y, "cached": z}}').
"""
import argparse, base64, json, os, subprocess, sys, tempfile, time, urllib.request

BASE = "https://ai.preview.workato.com/v1"
LEDGER = os.path.expanduser("~/.claude/knowledge/models-evals/bench.jsonl")
FIXTURE_DIR = os.path.expanduser("~/.claude/knowledge/fixtures")

# Probes: fixed, cheap, deterministic-ish. Scored by string match where possible.
PROBES = {
    "reasoning": {
        "prompt": "A recipe processes 5 batches of 12 records each, but every 3rd record is skipped. How many records are processed? Reply with just the number.",
        "verify": lambda txt: "40" in txt,
        "max_tokens": 256,
    },
    "code": {
        "prompt": ("Write a Python function `slugify(s)` that lowercases, replaces spaces with hyphens, "
                   "strips non-alphanumeric chars except hyphens, and collapses runs of hyphens. "
                   "Reply with ONLY the function in a ```python block."),
        "verify": lambda txt: "def slugify" in txt and "-" in txt,
        "max_tokens": 512,
    },
}

# 1x1 red PNG — used only by --vision-probe to test image support.
VISION_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)


def token():
    env = json.load(open(os.path.expanduser("~/.claude/settings.json")))
    return env["env"]["ANTHROPIC_AUTH_TOKEN"]


def chat(model, messages, max_tokens, timeout=120):
    """Stream one completion. Returns dict(text, prompt_t, completion_t, cached_t, ttft, wall)."""
    body = json.dumps({"model": model, "messages": messages, "max_tokens": max_tokens,
                       "stream": True}).encode()
    req = urllib.request.Request(f"{BASE}/chat/completions", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {token()}",
                                          "Content-Type": "application/json"})
    t0 = time.time(); ttft = None; text = []; usage = {}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.strip()
                if not line or line.startswith(b"event:") or line.startswith(b":"):
                    continue
                if not line.startswith(b"data:"):
                    continue
                payload = line[5:].strip()
                if payload == b"[DONE]":
                    break
                evt = json.loads(payload)
                if evt.get("usage"):
                    usage = evt["usage"]
                for ch in evt.get("choices", []):
                    delta = ch.get("delta", {}).get("content")
                    if delta:
                        if ttft is None:
                            ttft = time.time() - t0
                        text.append(delta)
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    wall = time.time() - t0
    full = "".join(text)
    decode_s = wall - (ttft or wall)
    return {"text": full, "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0),
            "ttft_s": round(ttft, 3) if ttft else None,
            "wall_s": round(wall, 3),
            "tps": round(usage.get("completion_tokens", 0) / decode_s, 1) if decode_s > 0.05 else None}


def vision_probe(model):
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": "What color is this image? One word."},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64.b64encode(VISION_PNG).decode()}"}}]}]
    r = chat(model, msgs, 32)
    if "error" in r:
        return {"model": model, "vision": "NO", "evidence": r["error"]}
    return {"model": model, "vision": "YES", "answer": r["text"].strip()[:60],
            "ttft_s": r["ttft_s"]}


# ---- fixture mode: canon regression fixtures become eval tasks ----
# Each usable fixture (non-empty input + expect) is a behavior contract:
# the model writes a Ruby `transform` lambda; we execute it on the fixture
# input and judge the output with the same expect ops `wt fixture run` uses.

def load_fixtures():
    out = []
    if not os.path.isdir(FIXTURE_DIR):
        return out
    for fn in sorted(os.listdir(FIXTURE_DIR)):
        try:
            fx = json.load(open(os.path.join(FIXTURE_DIR, fn)))
        except (json.JSONDecodeError, OSError):
            continue
        if fx.get("input") and fx.get("expect"):
            fx["_file"] = fn
            out.append(fx)
    return out


def get_path(obj, dotted):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None, "missing"
        cur = cur[part]
    return cur, None


def check_expect(output, expects):
    results = []
    for e in expects:
        val, err = get_path(output, e.get("path", ""))
        op = e.get("op", "present")
        want = e.get("value")
        if err:
            ok = op in ("absent",)
        elif op == "present":
            ok = val is not None
        elif op == "absent":
            ok = val is None
        elif op == "eq":
            ok = val == want
        elif op == "ne":
            ok = val != want
        elif op == "contains":
            ok = isinstance(val, (list, str, dict)) and want in val
        elif op in ("gt", "lt"):
            try:
                ok = (float(val) > float(want)) if op == "gt" else (float(val) < float(want))
            except (TypeError, ValueError):
                ok = False
        else:
            ok = False
        results.append((ok, f"{e.get('path')} {op} {want!r}: {ok}"))
    return results


FIXTURE_PROMPT = """You are writing a Workato-compatible Ruby transformation.

Write a Ruby lambda assigned to the variable `transform`. It takes one argument,
a hash named `input`, and must return a hash `output` satisfying every assertion below.

Input hash:
{input_json}

Assertions on the returned output:
{expects}

Reply with ONLY the Ruby code (no explanation, no fences)."""

JUDGE_BODY = """
begin
  b = binding
  eval(SRC, b)
  t = (b.local_variable_get(:transform) rescue b.eval("method(:transform)"))
  result = t.call(INPUT)
  puts "---JSON---"
  require 'json'
  puts JSON.generate(result)
rescue => e
  puts "---ERROR---#{e.class}: #{e.message}"
end
"""


def run_fixture_probe(model, fx, timeout=60):
    expects = fx["expect"]
    lines = []
    for e in expects:
        line = f"- path {e['path']}: op {e['op']}"
        if "value" in e:
            line += f" value {e['value']!r}"
        lines.append(line)
    prompt = FIXTURE_PROMPT.format(input_json=json.dumps(fx["input"]), expects="\n".join(lines))
    r = chat(model, [{"role": "user", "content": prompt}], 2048, timeout=timeout)
    if "error" in r:
        return {"pass": None, "error": r["error"], **{k: v for k, v in r.items() if k not in ("error", "text")}}
    code = r["text"].strip().removeprefix("```ruby").removeprefix("```").removesuffix("```").strip()
    src = ("require 'json'\nSRC = " + json.dumps(code)
           + "\nINPUT = JSON.parse(" + json.dumps(json.dumps(fx["input"])) + ")\n" + JUDGE_BODY)
    with tempfile.NamedTemporaryFile("w", suffix=".rb", delete=False) as f:
        f.write(src)
        path = f.name
    try:
        proc = subprocess.run(["ruby", path], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        os.unlink(path)
        return {"pass": False, "error": "ruby judge timed out", **{k: v for k, v in r.items() if k != "text"}}
    os.unlink(path)
    if "---JSON---" not in proc.stdout:
        detail = (proc.stdout.replace("---ERROR---", "") or proc.stderr)[:200].strip()
        return {"pass": False, "error": f"ruby exec failed: {detail}",
                **{k: v for k, v in r.items() if k != "text"}}
    output = json.loads(proc.stdout.split("---JSON---", 1)[1].strip() or "{}")
    checks = check_expect(output, expects)
    return {"pass": all(ok for ok, _ in checks),
            "checks": [msg for _, msg in checks],
            **{k: v for k, v in r.items() if k != "text"}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="fireworks/kimi-k3,fireworks/glm-5.3-flash,fireworks/deepseek-v4.1-flash,fireworks/deepseek-v4-pro")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--probes", default="reasoning,code")
    ap.add_argument("--prices", default="{}")
    ap.add_argument("--vision-probe", action="store_true", help="just test image support per model")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    if args.list:
        req = urllib.request.Request(f"{BASE}/models", headers={"Authorization": f"Bearer {token()}"})
        ids = sorted(m["id"] for m in json.load(urllib.request.urlopen(req, timeout=30))["data"])
        print("\n".join(ids)); return

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    prices = json.loads(args.prices)

    if args.vision_probe:
        for m in models:
            print(json.dumps(vision_probe(m)))
        return

    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    for model in models:
        for run in range(1, args.runs + 1):
            for pname in args.probes.split(","):
                if pname == "fixtures":
                    fxs = load_fixtures()
                    print(f"# fixtures mode: {len(fxs)} usable fixture(s)")
                    for fx in fxs:
                        r = run_fixture_probe(model, fx)
                        row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "model": model,
                               "probe": "fixtures", "fixture": fx["_file"], "run": run, **r}
                        with open(LEDGER, "a") as f:
                            f.write(json.dumps(row) + "\n")
                        print(json.dumps(row))
                        time.sleep(1)
                    continue
                probe = PROBES.get(pname)
                if not probe:
                    sys.exit(f"unknown probe: {pname}")
                r = chat(model, [{"role": "user", "content": probe["prompt"]}], probe["max_tokens"])
                row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "model": model, "probe": pname,
                       "run": run, "pass": probe["verify"](r.get("text", "")) if "text" in r else None,
                       **{k: v for k, v in r.items() if k != "text"}}
                if model in prices and "prompt_tokens" in r:
                    p = prices[model]
                    row["cost_usd"] = round(r["prompt_tokens"] / 1e6 * p["in"]
                                            + r["completion_tokens"] / 1e6 * p["out"], 5)
                with open(LEDGER, "a") as f:
                    f.write(json.dumps(row) + "\n")
                print(json.dumps(row))
                time.sleep(1)


if __name__ == "__main__":
    main()
