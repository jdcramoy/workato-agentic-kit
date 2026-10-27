#!/usr/bin/env python3
"""workspace_access_check.py - pre-check that a ticket's target Workato
workspace is inside Josh's accessible set BEFORE the triage loop proposes
a build on it.

Born from the 2026-10-25 finance-AHQ incident: jira-autotriage proposed an
auto-build on a finance-workspace ticket Josh has no access to. This check
runs before any plan/build proposal and returns one of:

  ACCESSIBLE      target workspace matches a wt profile that verifies live
  NOT-ACCESSIBLE  target workspace has no verifying wt profile
  UNKNOWN         cannot resolve the target (no ref, no project mapping,
                  or probe failed) - treat as needs-Josh, never accessible

Accessible set: the wt profiles in ~/.workato/profiles, each verified live
(`wt api --profile <p> get /api/users/me` returns that workspace's id).
A profile file entry alone is NOT proof of access - the probe is. Probe
results cache for 30 minutes at
~/.claude/knowledge/cache/workspace-access-cache.json.

Usage (from the jira-autotriage loop, per ticket):
  python3 ~/.claude/knowledge/scripts/workspace_access_check.py \
      --project BSYS --workspace "finance AHQ"     # ref from the ticket
  python3 ~/.claude/knowledge/scripts/workspace_access_check.py --project BSYS

  --workspace REF   numeric id, name, or fragment of the target Workato
                    workspace as named on the ticket (optional)
  --project KEY     Jira project key; mapped to workspaces via
                    knowledge/config/jira-project-workspaces.json
                    (defaults for known projects are built in)
  --offline         trust the profile list, skip live probes (cache only)
  --json            machine-readable output

Exit codes: 0 ACCESSIBLE, 1 NOT-ACCESSIBLE, 2 UNKNOWN, 3 usage error.
Every run ends with an EVIDENCE line (JSON), same convention as jira.py.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
PROFILES_PATH = os.path.join(HOME, ".workato", "profiles")
CACHE_PATH = os.path.join(HOME, ".claude", "knowledge", "cache",
                          "workspace-access-cache.json")
PROJECT_MAP_PATH = os.path.join(HOME, ".claude", "knowledge", "config",
                                "jira-project-workspaces.json")
PROBE_CMD = ["wt", "api", "--profile", "{profile}", "get", "/api/users/me"]
PROBE_TIMEOUT_S = 45
CACHE_TTL_S = 30 * 60

# Builtin Jira project key -> Workato workspace ids the project's work
# targets. Extend without code edits via PROJECT_MAP_PATH (same shape:
# {"KEY": [id, ...]}); file values override builtins.
BUILTIN_PROJECT_MAP = {
    "BSYS": [3535597, 3535598],   # Workato AHQ | AI (dev + prod)
    "BTSUP": [3535597, 3535598],
    "HROPS": [1672047, 1672048],  # Workato AHQ | HR and People Ops
}

VERDICT_EXIT = {"ACCESSIBLE": 0, "NOT-ACCESSIBLE": 1, "UNKNOWN": 2}


def evidence(cmd, verdict, **kw):
    print("EVIDENCE: " + json.dumps(
        {"cmd": cmd, "verdict": verdict, **kw}, default=str))


def load_profiles():
    try:
        with open(PROFILES_PATH) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        sys.exit(f"FAIL: cannot read {PROFILES_PATH}: {e}")
    return data.get("profiles", {})


def load_project_map():
    m = dict(BUILTIN_PROJECT_MAP)
    if os.path.exists(PROJECT_MAP_PATH):
        try:
            with open(PROJECT_MAP_PATH) as fh:
                m.update({k.upper(): v for k, v in json.load(fh).items()})
        except (OSError, json.JSONDecodeError) as e:
            print(f"NOTE: ignoring unreadable {PROJECT_MAP_PATH}: {e}",
                  file=sys.stderr)
    return m


def probe_profile(profile):
    """One live probe; returns {ok, workspace_id, name} or {ok: False, err}."""
    cmd = [c.replace("{profile}", profile) for c in PROBE_CMD]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=PROBE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"ok": False, "err": f"probe timed out after {PROBE_TIMEOUT_S}s"}
    except OSError as e:
        return {"ok": False, "err": str(e)}
    blob = r.stdout + r.stderr
    m = re.search(r'"id"\s*:\s*(\d+)', blob)
    name = re.search(r'"name"\s*:\s*"([^"]+)"', blob)
    if r.returncode == 0 and m:
        return {"ok": True, "workspace_id": int(m.group(1)),
                "name": name.group(1) if name else profile}
    err = re.search(r'(40[13][^\n"]*|missing_privilege[^\n"]*|'
                    r'Session expired[^\n"]*|invalid[^\n"]*token[^\n"]*)', blob, re.I)
    return {"ok": False, "err": (err.group(1)[:120] if err
                                 else f"rc={r.returncode} {blob[:120]}")}


def verified_profiles(offline=False):
    """{profile: {workspace_id, name}} for every profile that verifies.
    Cached 30 min; failed probes are retried on the next run (never cached
    as accessible)."""
    cache = {}
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH) as fh:
                raw = json.load(fh)
            if time.time() - raw.get("ts", 0) < CACHE_TTL_S:
                cache = raw.get("ok", {})
        except (OSError, json.JSONDecodeError):
            cache = {}
    profiles = load_profiles()
    live = {}
    for prof in profiles:
        if prof in cache:
            live[prof] = cache[prof]
            continue
        res = probe_profile(prof)
        if res.get("ok"):
            live[prof] = {"workspace_id": res["workspace_id"],
                          "name": res["name"]}
        # failures are NOT cached: the next run retries them
    if not offline and live != cache:
        try:
            os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
            with open(CACHE_PATH + ".tmp", "w") as fh:
                json.dump({"ts": time.time(), "ok": live}, fh)
            os.replace(CACHE_PATH + ".tmp", CACHE_PATH)
        except OSError as e:
            print(f"NOTE: cache write failed: {e}", file=sys.stderr)
    return live


def match_ref(ref, profiles):
    """Match a workspace reference (id or name fragment) against verified
    profiles. Returns (profile, ws) or (None, None) plus what was seen."""
    ref_s = str(ref).strip()
    if re.fullmatch(r"\d+", ref_s):
        wid = int(ref_s)
        for prof, ws in profiles.items():
            if ws["workspace_id"] == wid:
                return prof, ws
        return None, None
    frag = ref_s.lower()
    for prof, ws in profiles.items():
        label = next((p.get("label", "") for p in load_profiles().values()
                      if p.get("workspace_id") == ws["workspace_id"]), "")
        if frag in ws["name"].lower() or frag in label.lower():
            return prof, ws
    return None, None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--project", help="Jira project key, e.g. BSYS")
    ap.add_argument("--workspace", help="target Workato workspace id, "
                                        "name, or fragment from the ticket")
    ap.add_argument("--offline", action="store_true",
                    help="skip live probes; use cached results only")
    ap.add_argument("--json", action="store_true", help="machine output")
    a = ap.parse_args()
    if not a.project and not a.workspace:
        ap.error("pass --project KEY and/or --workspace REF")

    live = verified_profiles(offline=a.offline)
    pm = load_project_map()
    project = (a.project or "").upper()

    # Resolve the target workspace(s): explicit ref first, else the project map.
    if a.workspace:
        prof, ws = match_ref(a.workspace, live)
        if prof:
            print(f"VERDICT: ACCESSIBLE - workspace {ws['workspace_id']} "
                  f"({ws['name']}) verified live via wt profile '{prof}'")
            evidence("workspace-access-check", "ACCESSIBLE", profile=prof,
                     workspace_id=ws["workspace_id"], workspace_name=ws["name"],
                     source=f"--workspace {a.workspace!r}")
            return VERDICT_EXIT["ACCESSIBLE"]
        # No verified profile matches the ref. A numeric id is decisive;
        # a name fragment fails closed the same way (the gate's whole job
        # is to refuse what it cannot verify) but records the phrasing.
        known_ids = sorted(p["workspace_id"] for p in live.values())
        mapped = pm.get(project, [])
        if mapped:
            return decide_mapped(project, mapped, live, hint=a.workspace)
        print(f"VERDICT: NOT-ACCESSIBLE - no verified wt profile matches "
              f"workspace ref {a.workspace!r} "
              f"({len(live)} verified: "
              f"{', '.join(str(i) for i in known_ids)})")
        evidence("workspace-access-check", "NOT-ACCESSIBLE",
                 workspace=a.workspace, verified=known_ids,
                 project=project or None)
        return VERDICT_EXIT["NOT-ACCESSIBLE"]
    # No --workspace: fall back to the Jira project map.
    mapped = pm.get(project)
    if not mapped:
        print(f"VERDICT: UNKNOWN - no workspace ref on the ticket and no "
              f"mapping for Jira project {project or '(none)'}; pass "
              f"--workspace with the ref named on the ticket")
        evidence("workspace-access-check", "UNKNOWN", project=project,
                 verified=[p["workspace_id"] for p in live.values()])
        return VERDICT_EXIT["UNKNOWN"]
    return decide_mapped(project, mapped, live)


def decide_mapped(project, mapped_ids, live, hint=None):
    """Project-mapped path. ACCESSIBLE if every mapped workspace the loop
    would build in is verified; NOT-ACCESSIBLE if none of them is; UNKNOWN
    if mapped targets exist but could not be verified."""
    verified = {p["workspace_id"]: (prof, p) for prof, p in live.items()}
    hits = [(wid, verified[wid]) for wid in mapped_ids if wid in verified]
    misses = [wid for wid in mapped_ids if wid not in verified]
    if hits and not misses:
        names = ", ".join(f"{w['workspace_id']} ({w['name']})" for _, (p, w)
                          in [(h[0], h[1]) for h in hits])
        print(f"VERDICT: ACCESSIBLE - project {project} maps to workspace(s) "
              f"{names}, all verified live via wt profiles")
        evidence("workspace-access-check", "ACCESSIBLE", project=project,
                 mapped=mapped_ids, verified=[h[0] for h in hits])
        return VERDICT_EXIT["ACCESSIBLE"]
    if not hits:
        print(f"VERDICT: NOT-ACCESSIBLE - project {project} maps to workspace "
              f"{'id(s) ' + ', '.join(str(w) for w in misses) if misses else '(none)'} "
              f"and no wt profile verifies any of them "
              f"({len(live)} verified: "
              f"{', '.join(str(p['workspace_id']) for p in live.values())})"
              + (f"; ticket hint {hint!r} matches none" if hint else ""))
        evidence("workspace-access-check", "NOT-ACCESSIBLE", project=project,
                 mapped=mapped_ids, verified=sorted(verified.keys()))
        return VERDICT_EXIT["NOT-ACCESSIBLE"]
    print(f"VERDICT: UNKNOWN - project {project} maps to {mapped_ids}; "
          f"accessible: {hits[0][0]}; could not verify: {misses}")
    evidence("workspace-access-check", "UNKNOWN", project=project,
             mapped=mapped_ids, verified=hits[0][0], unverified=misses)
    return VERDICT_EXIT["UNKNOWN"]


if __name__ == "__main__":
    sys.exit(main())
