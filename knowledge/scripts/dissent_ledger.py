#!/usr/bin/env python3
"""dissent_ledger.py — the dissenter triad and adversarial co-evolution.

Triad: three rotating critic identities (different model + different
professional frame). The learning rule: whichever critic's severity
classifications most often predict Josh's real rejections earns more weight
next week — a critic that learns which criticisms matter.

Co-evolution: the dreamer pre-empts the attack classes that killed past
proposals; the critics sharpen against the dreamer's fixes. Two sides
training each other on the shared ledger. (GAN dynamics for agent
reasoning; curves report whether it's actually working.)

  dissent_ledger.py log --proposal <slug> --critic kimi-lawyer --severity material --class governance --objection "..."
  dissent_ledger.py resolve --proposal <slug> --rejected|built   # called by proposal-decide flow
  dissent_ledger.py weights           # critic leaderboard (catch rate)
  dissent_ledger.py attack-classes    # which attack classes kill proposals (dreamer's pre-empt list)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

K = Path.home() / ".claude/knowledge"
LEDGER = K / "dreams/dissent-ledger.jsonl"
OUTCOMES = K / "garden-reports/proposal-outcomes.jsonl"

CRITICS = {
    # model lineage x professional frame — rotate so priors differ per review
    "frontier-governance": {"model": "kimi", "persona": "lawyer"},
    "flash-engineer": {"model": "deepseek", "persona": "engineer"},
    "flash-contrarian": {"model": "glm", "persona": "contrarian"},
}


def _load() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]


def log(proposal: str, critic: str, severity: str, attack_class: str, objection: str) -> dict:
    rec = {
        "id": f"dis-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "proposal": proposal,
        "critic": critic,
        "model": CRITICS.get(critic, {}).get("model", critic),
        "severity": severity,  # fatal | material | cosmetic | steel
        "attack_class": attack_class,  # governance | feasibility | evidence | scope | cost | timing | novelty
        "objection": objection[:300],
        "logged": dt.datetime.now().isoformat(timespec="seconds"),
        "outcome": None,  # filled when the proposal is decided
    }
    with LEDGER.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def resolve(proposal: str, rejected: bool) -> dict:
    """When Josh decides, credit every critic whose severity called it right."""
    recs = _load()
    for r in recs:
        if r["proposal"] == proposal and r["outcome"] is None:
            if rejected:
                # a real rejection validates fatal/material objections
                r["outcome"] = "caught" if r["severity"] in ("fatal", "material") else "cry-wolf"
            else:
                # accepted proposal: harsh severity was miscalibrated
                r["outcome"] = "false-alarm" if r["severity"] in ("fatal", "material") else "steel"
    LEDGER.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
    return {"resolved": proposal, "rejected": rejected}


def weights() -> dict:
    recs = _load()
    by_critic: dict[str, dict] = defaultdict(lambda: {"caught": 0, "false-alarm": 0, "cry-wolf": 0, "steel": 0})
    for r in recs:
        if r.get("outcome"):
            by_critic[r["critic"]][r["outcome"]] += 1
    out = {}
    for critic, c in by_critic.items():
        judged = c["caught"] + c["false-alarm"]
        out[critic] = {
            **c,
            "catch_rate": round(c["caught"] / judged, 3) if judged else None,
            "n_judged": judged,
        }
    return out


def attack_classes() -> dict:
    """The dreamer's pre-empt list: attack classes that actually killed proposals."""
    recs = _load()
    killed: dict[str, int] = defaultdict(int)
    noise: dict[str, int] = defaultdict(int)
    for r in recs:
        if r.get("outcome") == "caught":
            killed[r["attack_class"]] += 1
        elif r.get("outcome") in ("false-alarm", "cry-wolf"):
            noise[r["attack_class"]] += 1
    ranked = sorted(killed.items(), key=lambda kv: -kv[1])
    return {
        "pre_empt_priority": ranked,
        "noise_classes": dict(sorted(noise.items(), key=lambda kv: -kv[1])),
        "note": "the dreamer pre-answers the top classes before filing; classes that "
        "only produce noise should be ignored by critics (calibrated away)",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("log")
    lg.add_argument("--proposal", required=True)
    lg.add_argument("--critic", required=True)
    lg.add_argument("--severity", required=True, choices=["fatal", "material", "cosmetic", "steel"])
    lg.add_argument("--class_", dest="attack_class", required=True)
    lg.add_argument("--objection", required=True)
    rs = sub.add_parser("resolve")
    rs.add_argument("--proposal", required=True)
    rs.add_argument("--rejected", action="store_true")
    sub.add_parser("weights")
    sub.add_parser("attack-classes")
    a = ap.parse_args()
    if a.cmd == "log":
        print(json.dumps(log(a.proposal, a.critic, a.severity, a.attack_class, a.objection), indent=2))
    elif a.cmd == "resolve":
        print(json.dumps(resolve(a.proposal, a.rejected), indent=2))
    elif a.cmd == "weights":
        print(json.dumps(weights(), indent=2))
    elif a.cmd == "attack-classes":
        print(json.dumps(attack_classes(), indent=2))


if __name__ == "__main__":
    main()
