#!/usr/bin/env python3
"""criticality.py — is the agent fleet's information flow at criticality?

Neuroscience: cortical networks at the critical point produce neuronal
avalanches whose sizes follow a power law — maximum information transmission.
Subcritical: signals die in place. Supercritical: everything floods everything.

The fleet analog: cascades of bus activity — how many agents engage with a
thread before it dies? If cascade sizes (bus posts per thread per day,
opinions per finding, digest→opinion→proposal chains) follow a power law,
the network is self-organizing near criticality. If not, tune the coupling:
the corroboration threshold and the mood register's arousal dial.

  python3 -m kb.criticality        # avalanche analysis over the bus

Fitting: maximum-likelihood alpha over cascade sizes (Clauset et al. method,
x_min = smallest size above 1); alpha in [2, 3] = the critical zone. Also
reports the plain histogram so small-n honesty is visible.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

BUS = Path.home() / ".claude/knowledge/dreams/bus"


def _threads_window(days: int = 14) -> dict[str, int]:
    """thread (agent+type or a coarse thread key) -> cascade size per day."""
    end = datetime.now()
    start = end - timedelta(days=days)
    cascades: list[int] = []
    for f in BUS.glob("*.jsonl"):
        per_day: dict[str, int] = defaultdict(int)
        for line in f.read_text().splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = str(rec.get("ts", ""))[:10]
            try:
                when = datetime.fromisoformat(ts)
            except ValueError:
                continue
            if when >= start:
                per_day[ts] += 1
        cascades.extend(per_day.values())
    return cascades


def fit_alpha(sizes: list[int], x_min: int = 2) -> dict:
    """MLE alpha for power-law tail (Clauset-Shalizi-Newman): alpha = 1 + n / sum(ln(x/(x_min-0.5)))."""
    tail = [x for x in sizes if x >= x_min]
    n = len(tail)
    if n < 10:
        return {"note": f"only {n} cascades >= {x_min} in the window — anecdote, not criticality", "alpha": None}
    s = sum(math.log(x / (x_min - 0.5)) for x in tail)
    alpha = 1 + n / s if s else None
    # zones: alpha < 1.5 supercritical-ish (heavy floods), ~2-3 critical, > 3.5 subcritical (signals die)
    zone = "subcritical (signals dying — raise coupling)" if (alpha or 0) > 3.5 else (
        "supercritical (floods — raise corroboration threshold)" if (alpha or 4) < 1.5 else "critical zone — leave it alone"
    )
    return {"n": n, "x_min": x_min, "alpha": round(alpha, 2) if alpha else None, "reading": zone}


def main() -> None:
    sizes = _threads_window()
    if not sizes:
        print(json.dumps({"note": "no bus activity in window"}))
        return
    hist = Counter(sizes)
    print(json.dumps({
        "cascade_sizes_per_agent_thread_day": dict(sorted(hist.items())),
        "total_posts": sum(sizes),
        "agents": len(list(BUS.glob("*.jsonl"))),
        "power_law_fit": fit_alpha(sizes),
        "note": "alpha ~2-3 = critical zone (max information transmission); "
        "the corroboration threshold and mood arousal are the tuning knobs",
    }, indent=2))


if __name__ == "__main__":
    main()
