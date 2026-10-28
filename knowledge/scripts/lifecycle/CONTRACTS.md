# Lifecycle build CONTRACTS — 2026-10-23 (three builders, one integration pass)

Header law (carried from frontier/CONTRACTS.md): pure Python3, zero-LLM, stdlib only.
Every script: `--help`, exit 0 on success / 1 on validation error, JSONL append-only where
the artifact is a ledger, human summary printed to stdout. No pip installs. No network calls
except documented read-only `wt api GET` (none expected in this build).

**HARD RULE: each builder owns DISJOINT paths. Never write outside your ownership block.
If you need something from another block, read it — never write it.**

## Ownership map

- **LATENCY** (claim-latency instrument):
  - `~/.claude/knowledge/scripts/claim-latency.py`
  - `~/.claude/knowledge/claim-latency/**`
  - `~/.claude/knowledge/config/fleet/jobs/frontier-nightly.script` — APPEND one line only
    (then run `~/.claude/knowledge/scripts/fleet-deploy.sh` and diff-verify all three copies)
- **AUTONOMY** (earned-autonomy engine):
  - `~/.claude/knowledge/scripts/autonomy.py`
  - `~/.claude/knowledge/autonomy/**`
  - `~/.claude/knowledge/config/fleet/jobs/autonomy-nightly.script` (new)
  - `~/Library/LaunchAgents/com.josh.fleet.autonomy-nightly.plist` (CREATE ONLY — never
    `launchctl load`; the integration pass loads it)
- **CLOSEOUT** (session auto-closeout drafts):
  - `~/.claude/knowledge/scripts/session-closeout.py`
  - `~/.claude/knowledge/mission-control/drafts/**`
  - `~/.claude/knowledge/scripts/morning-digest.py` — ADD a bounded "draft closeouts pending"
    surfacing block (read drafts dir, print count + one-line-per-draft; no refactor of
    existing logic)
- **INTEGRATION (main session, nobody else):** `~/.claude/settings.json` (SessionEnd hook
  wiring), `launchctl load`, `~/.claude/knowledge/INDEX.md`, `domains/claim-lifecycle.md`,
  mission-control rows, memory files.

## Read-only inputs (schema pinned from live inventory, 2026-10-23)

- Mission control: `~/.claude/knowledge/mission-control/events.jsonl` — rows
  `{ts, event: claim|closeout|state|note, workstream, state: in-flight|needs-josh|blocked|done,
  by, project?, jira?, what?, why?, end?, needs?, session_id?, ttl_hours?}`.
  Closure = later row, same workstream, state=done. Fold = last event per workstream wins.
- Proposals: `~/.claude/knowledge/dreams/proposals/*.md` — filename `YYYY-MM-DD-<slug>.md`;
  frontmatter FIRST `status:` line is authoritative (a duplicate-status bug exists — take the
  first). Outcomes: `~/.claude/knowledge/garden-reports/proposal-outcomes.jsonl` rows
  `{date (day granularity), proposal, action: accepted|rejected-false-alarm|accepted-modified|built, notes, by}`.
- Predictions (calibration ledger): `~/.claude/knowledge/predictions/predictions.jsonl` —
  submission rows `{id: prd-NNN, ts, agent, claim, confidence 0-1, resolve_by, resolver_query,
  status: open}`; resolution rows `{id, ts, type: resolution, status: resolved_true|resolved_false,
  outcome: 0|1, brier, resolved_at, evidence}`; also `type: flag|extension` rows (skip).
- Decisions engine ledgers: `~/.claude/knowledge/decisions/decisions.jsonl`
  (`{id: dec-..., ts, surface, model, questions[], answers[{name,type,probabilities,value,confidence}]}`)
  and `~/.claude/knowledge/decisions/outcomes.jsonl`
  (`{ts, decision_id, name, observed, note}`, last-wins per decision_id+name).
- Claims sweep cache: `~/.claude/knowledge/reports/claims-sweep-latest.json`
  (`{generated, headline{...}, needs_josh{under_72h[],d3_7[],over_7d[]}, ...}`).
- Transcripts: `~/.claude/projects/<mangled-cwd>/<session-uuid>.jsonl`, one JSON object per
  line; user rows have `message.content`, assistant rows have `message.content[]` with typed
  items (`text`, `tool_use{name,input}`, `thinking`); all rows carry `timestamp` (ISO Z) and
  `sessionId`. Hook stdin for SessionEnd provides `session_id`, `transcript_path`, `cwd`.

## Schemas this build creates (all three builders conform)

### claim-latency snapshot — `knowledge/claim-latency/snapshots.jsonl` (append one row/run)
```json
{"ts": "ISO-Z", "sources": {
  "mission_control": {"open": 0, "open_age_median_h": 0.0, "open_age_p90_h": 0.0,
    "closed": 0, "ttc_median_h": 0.0, "ttc_p90_h": 0.0,
    "buckets": {"lt1h": 0, "h1_24": 0, "d1_3": 0, "d3_7": 0, "gt7d": 0},
    "needs_josh_open": 0, "needs_josh_missing_close_condition": 0},
  "proposals":     {"open": 0, "open_age_median_d": 0.0, "closed": 0, "ttc_median_d": 0.0,
    "buckets": {"lt1d": 0, "d1_3": 0, "d3_7": 0, "d7_14": 0, "gt14d": 0}},
  "predictions":   {"open": 0, "open_age_median_h": 0.0, "closed": 0, "ttc_median_h": 0.0,
    "brier_mean": 0.0}},
 "bimodality_note": "one sentence: is the open-age distribution bimodal (machine minutes vs josh days)?"}
```
Also writes `knowledge/claim-latency/report-latest.json` (same shape + per-source detail) and
`report-latest.md` (human). "Missing close condition" = needs-josh row with empty `needs`.
Proposals are day-granularity — report honestly, never fabricate hour precision.

### autonomy authority table — `knowledge/autonomy/authority.json` (rewritten atomically)
```json
{"generated": "ISO-Z",
 "classes": {
   "<class-slug>": {"mode": "josh-only|recommend", "eligible_mode": "recommend|auto-close",
     "evidence": {"n": 0, "accuracy": 0.0, "brier": 0.0, "window_days": 30},
     "promotion_rule": "n>=20 AND accuracy>=0.8 AND trend not inverted",
     "since": "YYYY-MM-DD"}},
 "law": "Every class is born josh-only. Evidence can only make a class ELIGIBLE for recommend.
   auto-close exists as a mode value but is only ever set by Josh hand-editing this file."}
```
Recommendations: `knowledge/autonomy/recommendations-latest.json` — batch-approve candidates
for open needs-josh rows, each `{workstream, jira, age_days, matched_pattern, evidence_ref,
confidence, suggested_verdict}`. READ-ONLY against mission control — never mutates it.

### closeout draft — `knowledge/mission-control/drafts/<session_id>.json` (one file, overwrite)
```json
{"session_id": "...", "ended_at": "ISO-Z", "cwd": "...", "duration_min": 0, "turns": 0,
 "files_touched": ["..."], "jira_keys": ["BSYS-..."], "workato_assets": ["recipe:123"],
 "first_ask": "first real user message, trimmed", "last_assistant_text": "tail, trimmed",
 "suggested": {"what": "...", "why": "...", "end": "...", "state": "done|in-flight|needs-josh"},
 "status": "pending"}
```
`status` flows pending → adopted|discarded (set by whoever consumes the draft; the hook only
ever writes pending). Hook law: ALWAYS exit 0, complete < 5s, any exception → log line to
`drafts/_errors.log` and exit 0. Never block session exit.

## Verification bar (each builder, before reporting done)

Run your script(s) against LIVE data and paste the real headline output in your final report.
A claim of done without a real run's output is a failed delivery. List what you did NOT verify.
