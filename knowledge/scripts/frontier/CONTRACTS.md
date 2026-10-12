# Frontier build contracts (2026-10-11) — shared schemas for the 10-idea build

All scripts: pure Python3, zero LLM calls, stdlib only (urllib for API via wt pattern
— read `~/.claude/knowledge/scripts/fusion-run.py` request() for the gateway/Workato
token pattern; Workato API auth via WORKATO_API_TOKEN env or keychain like wt).
Every script: `--help`, exit codes 0/1, writes JSONL append-only, prints a human
summary. Each idea owns DISJOINT paths — never write outside your ownership block.

## File ownership map (disjoint — hard rule)
- Twin:        scripts/twin-snapshot.py, scripts/twin-query.py, knowledge/twin/
- Integrity:   scripts/claim-submit.py, scripts/reconcile.py, knowledge/integrity/
- Coverage:    scripts/coverage.py, knowledge/coverage/
- Calibration: scripts/prediction-submit.py, scripts/brier-resolve.py, knowledge/predictions/
- Radar:       scripts/precursor-radar.py (reads workato-health/, writes predictions/ via documented format)
- Saga:        scripts/saga.py, knowledge/sagas/
- Skill League:scripts/skill-fitness.py, knowledge/skills-telemetry/
- Standing:    scripts/standing-orders.py, knowledge/policies/
- Canary:      scripts/chaos-canary.py, knowledge/chaos/
- Shadow:      scripts/shadow-estate.py (reads now/decision-inbox.json)

## Schemas (JSONL, one JSON object per line)

**predictions.jsonl** (calibration):
{"id","ts","agent","claim","confidence" (0-1),"resolve_by" (ISO date),"resolver_query"
(string: how to check),"status":"open|resolved_true|resolved_false|void","resolved_at","brier"}
- Brier = (outcome - confidence)^2, computed at resolution. Boldness field: "consequential": true|false.

**Claim receipt** (integrity mesh, wraps existing claims/ entries):
{"claim_id","ts","agent","statement","proof":{"kind":"jira_transition|workato_job|file_hash|api_digest","uri","fetched_at","digest","postcondition_query","postcondition_result"},"tier":"proved|asserted"}
- No proof object => tier "asserted" (second-class). reconcile.py flags asserted older than 24h.

**Coverage line** (denominator oracle):
{"ts","job_or_run_id","population","expected_n","observed_n","coverage" (0-1),"source_of_expected","status":"ok|undercollect|unbounded-sampled"}

**Saga journal** (knowledge/sagas/<mission_id>.jsonl):
{"seq","ts","prev_hash","step_hash","action","state_in","state_out","compensation" (null or {action, params})}
- Resume = replay last state_out; fingerprint: {"git_sha","queues","clock"} checked before resume; mismatch => force re-plan.

**Standing order** (knowledge/policies/<id>.json):
{"id","name","match":{"field":"op":"value",...},"action":"auto_execute|draft_for_review","dollar_cap","risk_class" (1-4),"expires_at","ratchet":{"breach_shrinks":true},"created_from" (decision ids)}
- Matcher: first-match-wins; any breach auto-expires the policy.

**Twin layout** (knowledge/twin/v1/): recipes.jsonl, connections.jsonl, schedulers.jsonl, meta.json {"snapshot_at","workato_env","counts"}; twin-query.py answers dependency questions offline; every answer prints snapshot age.

## Data sources available (read-only)
- `wt api GET /api/recipes?per_page=100` (etc.) — Workato REST; wt at ~/.local/bin/wt
- build-ledger.jsonl, claims/, workato-health/, watchdog-reports/, now/decision-inbox.json
- Workato envs: dev + prod keys both exist; scripts default to DEV; --env prod prints WARNING + requires --confirm
