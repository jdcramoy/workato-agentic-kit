# Fleet config — CANONICAL copy

This directory (knowledge tree `~/.claude/knowledge/config/fleet/`) is the
CANONICAL source for every fleet file: `run-job.sh`, the plists, and
everything under `jobs/` (env, prompt, script).

**Deploy only from canonical.** Never hand-edit the deployed copies
(`~/.local/bin/fleet/...`, what the plists execute) or the kit mirror
(`~/Documents/agentic-workato-kit/bin/fleet/...`) — an edit made directly on a
deployed copy diverges silently and is overwritten by the next deploy.

Deploy:

    ~/.claude/knowledge/scripts/fleet-deploy.sh <name>    # one file
    ~/.claude/knowledge/scripts/fleet-deploy.sh --all     # everything

The script copies atomically (write-temp + mv) and shasum-verifies every
destination against canonical before reporting success. Verify any file any
time:

    shasum ~/.claude/knowledge/config/fleet/jobs/<f> \
           ~/.local/bin/fleet/jobs/<f> \
           ~/Documents/agentic-workato-kit/bin/fleet/jobs/<f>

Three copies must be byte-identical (run-job.sh DEPLOY CHECKLIST contract).
Divergence between deployed and kit copies is the divergence detector firing —
redeploy from canonical, never "fix" the deployed copy in place.

(Rule adopted 2026-10-26, approved needs-josh verdict "fleet deploy
canonical-only"; born from the 2026-10-11 wave3 partial-deploy class and the
frontier-nightly divergence checks.)
