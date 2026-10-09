"""apprentice.py — learn from the org's own recipes (the estate as teacher).

The production workspaces hold hundreds of recipes written by BT teammates.
This mines them for PATTERNS (technique-level, never business logic verbatim):
error-handling idioms, retry patterns, naming conventions, connector idioms,
conditional structures. Distilled patterns land as KB chunks (level-3
factlets) tagged source: apprentice — so the fleet learns what colleagues
already know.

Governance: read-only; pattern-level extraction only; no record data, no
tokens verbatim, no PII; recipes are referenced by id+name only.

  kb apprentice scan [--folder F] [-n 25]    # scan recipe codes, extract patterns
  kb apprentice report                       # last scan's distilled patterns
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from .indexer import get_db, get_model

PATTERNS = {
    "error_handler": re.compile(r"(error_handling|on_error|catch)", re.I),
    "retry": re.compile(r"(retry|max_retry|backoff)", re.I),
    "safe_nav": re.compile(r"&\."),
    "to_s_guard": re.compile(r"to_s\s*[=!<>]=?|to_s\s*\}|\{\{[^}]*to_s", re.I),
    "if_blank_guard": re.compile(r"(blank\?|nil\?|present\?|empty\?)", re.I),
    "logging": re.compile(r"(log_message|logger|workato_log)", re.I),
    "monitored_apps": re.compile(r"(workato_recipe_function|callable)", re.I),
    "batching": re.compile(r"(batch|chunk|in_groups_of)", re.I),
    "idempotency": re.compile(r"(upsert|find_or_|first_or_initialize)", re.I),
    "throttle": re.compile(r"(sleep|throttle|rate_limit)", re.I),
}


def scan(folder: int | None = None, n: int = 25, profile: str = "") -> dict:
    """Scan the recipe corpus via wt, extract pattern frequencies + exemplars."""
    import subprocess

    list_cmd = ["wt", "api", "GET", "/api/recipes?per_page=100"]
    r = subprocess.run(list_cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"recipe list failed: {r.stderr[:200]}")
    recipes = json.loads(r.stdout).get("items", [])
    if folder:
        recipes = [r_ for r_ in recipes if r_.get("folder_id") == folder]
    recipes = recipes[:n]

    found: dict[str, Counter] = {k: Counter() for k in PATTERNS}
    exemplars: dict[str, list] = defaultdict(list)
    scanned = 0
    for rec in recipes:
        rid = rec.get("id")
        name = rec.get("name", "")
        try:
            detail = subprocess.run(
                ["wt", "api", "GET", f"/api/recipes/{rid}"], capture_output=True, text=True, timeout=60
            )
            code = json.loads(detail.stdout).get("code", "") or json.dumps(json.loads(detail.stdout).get("config", {}))
        except Exception:  # noqa: BLE001 - skip unfetchable recipes
            continue
        scanned += 1
        for pname, rx in PATTERNS.items():
            hits = len(rx.findall(code))
            if hits:
                found[pname][name] += hits
                if len(exemplars[pname]) < 3:
                    exemplars[pname].append({"recipe": f"{name} ({rid})", "uses": hits})
        # code fetch is the slow part; be polite
        dt_sleep = 0.3
        import time

        time.sleep(dt_sleep)

    digest = {
        "scanned": scanned,
        "pattern_frequency": {k: sum(v.values()) for k, v in found.items() if v},
        "top_users": {k: v.most_common(3) for k, v in found.items() if v},
        "exemplars": {k: v for k, v in exemplars.items()},
    }
    out = Path.home() / ".claude/workato-kb/diffs/apprentice-latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({**digest, "date": dt.datetime.now().isoformat(timespec="seconds")}, indent=2))
    return digest


def report() -> dict:
    out = Path.home() / ".claude/workato-kb/diffs/apprentice-latest.json"
    if not out.exists():
        return {"note": "no scan yet — run kb apprentice scan"}
    return json.loads(out.read_text())


def to_kb() -> dict:
    """Distill the latest scan into KB chunks (apprentice-tagged factlets)."""
    rep = report()
    if "scanned" not in rep:
        return rep
    db = get_db()
    try:
        model = get_model("embed")
        text = (
            f"[source: apprentice | section: estate patterns | scanned: {rep['scanned']} recipes]\n\n"
            "Patterns observed across the org's own recipes (technique-level, learned "
            "from colleagues' work):\n" + json.dumps(rep["pattern_frequency"], indent=1) +
            "\nTop users: " + json.dumps(rep["top_users"], indent=1)
        )
        emb = model.encode([text], normalize_embeddings=True)[0].tolist()
        cur = db.execute(
            "INSERT INTO docs(source,url,path,title,section,sha256) VALUES(?,?,?,?,?,?)",
            ("apprentice", f"apprentice://{dt.date.today().isoformat()}", f"apprentice/{dt.date.today().isoformat()}.md",
             f"Estate pattern digest ({rep['scanned']} recipes)", "apprentice", str(hash(text))[:16]),
        ) if False else None
        # docs table insert + chunk row (keep consistent with indexer schema)
        db.execute(
            "INSERT OR REPLACE INTO docs(source,url,path,title,section,sha256) VALUES(?,?,?,?,?,?)",
            ("apprentice", f"apprentice://{dt.date.today().isoformat()}", f"apprentice/{dt.date.today().isoformat()}.md",
             f"Estate pattern digest ({rep['scanned']} recipes)", "apprentice", str(hash(text))),
        )
        doc_id = db.execute("SELECT doc_id FROM docs WHERE url=?", (f"apprentice://{dt.date.today().isoformat()}",)).fetchone()[0]
        db.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        c = db.execute(
            "INSERT INTO chunks(doc_id,chunk_ord,context,text,sha256) VALUES(?,?,?,?,?)",
            (doc_id, 0, text[:200], text, str(hash(text))),
        )
        db.execute(
            "INSERT OR REPLACE INTO chunks_vec(chunk_id, embedding) VALUES(?,?)",
            (c.lastrowid, struct_pack(emb)),
        )
        db.commit()
        return {"apprentice_digest_indexed": True, "chars": len(text)}
    finally:
        db.close()


def struct_pack(vec):
    import struct

    return struct.pack(f"{len(vec)}f", *vec)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan")
    sc.add_argument("--folder", type=int, default=None)
    sc.add_argument("-n", type=int, default=25)
    sub.add_parser("report")
    sub.add_parser("to-kb")
    a = ap.parse_args()
    if a.cmd == "scan":
        print(json.dumps(scan(a.folder, a.n), indent=2))
    elif a.cmd == "report":
        print(json.dumps(report(), indent=2))
    elif a.cmd == "to-kb":
        print(json.dumps(to_kb(), indent=2))
