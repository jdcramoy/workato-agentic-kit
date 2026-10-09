#!/usr/bin/env python3
"""proposal-outcome.py — capture Josh's judgment on a dream proposal.

The highest-value signal in the system is whether Josh accepts or rejects a
proposal, and WHY. This records it durably so the dreamer learns his taste.

Usage:
  proposal-outcome.py <proposal-file-or-slug> approve|reject|revise ["reason"]
"""

import glob
import json
import os
import sys
import time
from atomic_io import atomic_append

K = os.path.expanduser("~/.claude/knowledge")
PROPS = os.path.join(K, "dreams", "proposals")
OUTCOMES = os.path.join(K, "dreams", "proposals", "outcomes.jsonl")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    target, verdict = sys.argv[1], sys.argv[2].lower()
    reason = " ".join(sys.argv[3:]) or "(no reason given)"
    if verdict not in ("approve", "reject", "revise"):
        print("verdict must be approve|reject|revise")
        return 1

    matches = glob.glob(os.path.join(PROPS, f"*{target}*"))
    if not matches:
        print(f"no proposal matching '{target}' in {PROPS}")
        return 1
    path = matches[0]
    slug = os.path.basename(path)

    # stamp the proposal's status line
    body = open(path).read()
    if "status: proposed" in body:
        body = body.replace("status: proposed",
                            f"status: {verdict}d" if verdict != "revise" else "status: revise", 1)
        open(path, "w").write(body)

    atomic_append(OUTCOMES, {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "proposal": slug, "verdict": verdict, "reason": reason,
    })
    print(f"recorded: {slug} -> {verdict} ({reason[:60]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
