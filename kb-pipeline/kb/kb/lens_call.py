"""Cross-model lens caller for the dreaming team (Josh-provided model fleet).

Three model priors, dispatched through the Workato AI gateway (Anthropic-
compatible messages API; base URL + token come from the harness env or the
settings.json/keychain):

  kimi     fireworks/kimi-k3            FRONTIER — expensive, budget-governed
  glm      fireworks/glm-5.3-flash      harness-native, cheap
  deepseek fireworks/deepseek-v4.1-flash cheap, different training lineage

Cost governance (Josh: Kimi is an expensive frontier model):
  - Kimi gets ONE lens per night (rotating), the Sunday deep pass gets the
    full-board Kimi treatment. Flash models carry the rest.
  - A nightly token ledger is kept in ~/.claude/workato-kb/kimi-ledger.jsonl.

    python3 -m kb.lens_call --model kimi --persona artist --digest <file>
    python3 -m kb.lens_call --model deepseek --persona engineer --prompt "..."
    python3 -m kb.lens_call --models            # registry + tonight's rotation
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import urllib.request
from pathlib import Path

MODELS = {
    "kimi": "fireworks/kimi-k3",
    "glm": "fireworks/glm-5.3-flash",
    "deepseek": "fireworks/deepseek-v4.1-flash",
}
# nightly rotation: which ONE lens earns the frontier model tonight
KIMI_ROTATION = ["artist", "contrarian", "musician", "doctor", "ceo", "analogist", "cto"]
LEDGER = Path.home() / ".claude/workato-kb/kimi-ledger.jsonl"

PERSONAS = {
    "artist": "The Artist: judge what is worth making at all. Taste, elegance, whether this deserves to exist.",
    "musician": "The Musician: harmony and counterpoint between systems; dissonance as information; rhythm and cadence.",
    "doctor": "The Doctor: diagnosis before treatment; symptoms vs root cause; first do no harm to working systems.",
    "lawyer": "The Lawyer: compliance, governance, liability, precedent.",
    "ceo": "The CEO: opportunity cost, strategy, what Josh should STOP doing to start this.",
    "engineer": "The Engineer: feasibility, failure modes, what breaks first at 10x.",
    "accountant": "The Accountant: real costs (tokens, hours, cron budget), depreciation, where ROI accrues.",
    "pm": "The Product Manager: who is the user, what's the job to be done, the MVP slice.",
    "cto": "The CTO: build vs buy, technical debt, platform leverage, does this compound.",
    "architect": "The Architect: what should this system become; structure, composition, compounding.",
    "contrarian": "The Contrarian: invert the obvious; what does everyone take for granted that is wrong or about to be wrong.",
    "analogist": "The Analogist: force cross-domain transfer; take a pattern from another industry/domain and apply it here.",
}


def _gateway() -> tuple[str, str]:
    base = os.environ.get("ANTHROPIC_BASE_URL", "")
    token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    if not (base and token):
        import subprocess

        out = subprocess.run(
            ["security", "find-generic-password", "-s", "FireworksAI", "-w"],
            capture_output=True,
            text=True,
        )
        token = out.stdout.strip() if out.returncode == 0 else ""
        base = "https://ai.preview.workato.com/anthropic"
    if not (base and token):
        raise SystemExit("gateway unavailable: ANTHROPIC_BASE_URL/AUTH_TOKEN not in env and FireworksAI not in keychain")
    return base.rstrip("/"), token


def _call(model_key: str, system: str, user: str, max_tokens: int | None = None) -> dict:
    base, token = _gateway()
    # glm's thinking is verbose — it needs headroom or the text block never fits
    if max_tokens is None:
        max_tokens = 4500 if model_key == "glm" else 2000
    body = {
        "model": MODELS[model_key],
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if model_key != "glm":
        # kimi/deepseek emit thinking blocks that eat the token budget before
        # any text — disable where the gateway supports it (glm's route 400s
        # on this param; its thinking just gets skipped by the extractor)
        body["thinking"] = {"type": "disabled"}
    payload = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base}/v1/messages",
        data=payload,
        headers={"Content-Type": "application/json", "x-api-key": token, "Authorization": f"Bearer {token}", "anthropic-version": "2023-06-01"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.load(resp)
    blocks = data.get("content", [])
    text = " ".join(b.get("text", "") for b in blocks if b.get("type") == "text")
    if not text.strip() and blocks:  # thinking-only fallback: surface the thinking
        text = " ".join(b.get("thinking", "") for b in blocks if b.get("type") == "thinking")
    usage = data.get("usage", {})
    return {"model": MODELS[model_key], "text": text.strip(), "usage": usage}


def _ledger_note(model_key: str, usage: dict) -> None:
    if model_key != "kimi":
        return
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(
            json.dumps(
                {
                    "ts": dt.datetime.now().isoformat(timespec="seconds"),
                    "input_tokens": usage.get("input_tokens"),
                    "output_tokens": usage.get("output_tokens"),
                }
            )
            + "\n"
        )


def tonight_kimi_lens() -> str:
    day = dt.date.today().weekday()  # 6 = Sunday
    if day == 6:
        return "ALL (Sunday deep pass — full board on the frontier model)"
    return KIMI_ROTATION[day % len(KIMI_ROTATION)]


def call(model_key: str, persona: str, digest: str | None = None, prompt: str | None = None) -> dict:
    if model_key == "kimi":
        lens_tonight = tonight_kimi_lens()
        if lens_tonight != "ALL" and lens_tonight != persona:
            return {
                "skipped": f"cost governance: kimi's lens tonight is '{lens_tonight}' — use glm or deepseek for '{persona}' (or wait for the Sunday full-board pass)"
            }
    system = f"You are {PERSONAS.get(persona, persona)} You give a 2-3 line opinion in your professional voice, concrete, no preamble. Where relevant, cite the evidence you were given."
    user = prompt or (f"Digest of what changed and what was observed:\n\n{digest}\n\nYour opinion as {persona}:")
    result = _call(model_key, system, user)
    _ledger_note(model_key, result.get("usage", {}))
    result["persona"] = persona
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", choices=MODELS, required=True)
    ap.add_argument("--persona", default=None)
    ap.add_argument("--digest", default=None)
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--models", action="store_true")
    a = ap.parse_args()
    if a.models:
        print(json.dumps({"models": MODELS, "kimi_lens_tonight": tonight_kimi_lens()}, indent=2))
        raise SystemExit(0)
    digest = Path(a.digest).read_text() if a.digest else None
    print(json.dumps(call(a.model, a.persona or "artist", digest, a.prompt), indent=2))
