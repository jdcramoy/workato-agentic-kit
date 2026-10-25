# Claim lifecycle layer — built 2026-10-23

The build that answers the dreamer's converged diagnosis (visions
[10-13 decision-throughput](../dreams/visions/2026-10-13-decision-throughput.md),
[10-18 core-of-the-system](../dreams/visions/2026-10-18-the-core-of-the-system.md),
[10-20 kill-layer](../dreams/visions/2026-10-20-the-kill-layer.md)): the harness's bottleneck
is the claim lifecycle — born-to-closed latency, unearned static trust, and sessions dying
without depositing state. Josh's go: "build it all" (2026-10-23). Three zero-LLM components,
one squad build under `scripts/lifecycle/CONTRACTS.md` (disjoint ownership, same pattern as
frontier/CONTRACTS.md).

## The three components

### 1. Claim-latency instrument — `scripts/claim-latency.py`
Read-only measurement of claim-born-to-closed latency across three sources: mission-control
events (per-workstream episodes, re-openings handled), proposals (filename date → outcome
date, day-granularity, unmatched outcome rows logged not dropped), predictions ledger
(submission → resolution, carries mean Brier). Appends one row/run to
`claim-latency/snapshots.jsonl`; writes `report-latest.{json,md}`. Runs nightly inside
frontier-nightly (04:43, line 12; three fleet copies shasum-verified identical).
CLI: `--report` | `--json` | default collect.

**Day-1 baseline (2026-10-23, real run):** 356 open mission-control claims (53 needs-josh,
0 missing close condition), open-age median 155h / p90 224h; 532 closed episodes with TTC
median <1m (born+done in one row) vs slow tail 7d+. Proposals: 36 open (median 6.2d),
70 closed (time-to-decision median 3.0d). Predictions: 14 open, 6 resolved (TTR median 5.6h,
Brier 0.198). **Bimodality verdict: NOT yet bimodal in OPEN claims — fast mode exists only
in closed claims. Days of data: 1 — INSUFFICIENT until ~2026-10-30.** The interesting
early signal: the 10-18 vision's hypothesis is half-confirmed already — closure is fast
when machines close, and the open pool is a slow-claim swamp.

### 2. Earned-autonomy engine — `scripts/autonomy.py` (`score|authority|recommend`)
Trust-from-data: per-(agent|surface, claim-class) evidence from the predictions ledger
(per-agent Brier), decisions engine ledgers (per-surface accuracy), and proposal outcomes
(base rates by kind/risk). Writes `autonomy/evidence.json`, `autonomy/authority.json`
(56 classes), `autonomy/recommendations-latest.json` (envelope: `candidates[]`, 114 rows).
Nightly via `com.josh.fleet.autonomy-nightly.plist` (04:53, loaded 2026-10-23).

**SELF-GATING LAW:** every class is born `mode: "josh-only"`. Evidence can only set
`eligible_mode: "recommend"` (promotion rule: n>=20 AND accuracy>=0.8 over trailing 30d).
`auto-close` exists as a mode value but the engine contains NO code path that writes it —
only Josh hand-editing authority.json flips a class:
`python3 -c "import json;p='~/.claude/knowledge/autonomy/authority.json';d=json.load(open(p));d['classes']['<class>']['mode']='auto-close';json.dump(d,open(p,'w'),indent=2)"`
The engine never mutates mission-control/proposals/claim stores — reads, scores, recommends.

**Day-1 evidence (honest thin):** exactly 1 class eligible for recommend (`proposal.unknown`,
n=132, acc 0.955 — but note the title-join caveat: 132/141 outcome rows didn't match a
proposal file, so that bucket is "unknown risk", reported not papered over). Closest miss:
`needs-josh.harness` n=18 acc 0.889, blocked only on n<20. Recommend: 25 of 114 open
needs-josh rows carry an honest pattern (conf 0.89-1.0), 89 are no-pattern/null-confidence.

### 3. Session auto-closeout — `scripts/session-closeout.py`
SessionEnd hook (wired into `~/.claude/settings.json` between session-drop-guard and the
orca dispatcher, backup `settings.json.bak-20261023-session-closeout-hook`). Parses the
session transcript (zero-LLM heuristics: files touched, Jira keys, Workato assets, first
ask, last assistant text, crude state guess) and writes a DRAFT closeout to
`mission-control/drafts/<session_id>.json` (status pending → adopted|discarded via
`--adopt/--discard`; consumed drafts never resurrect). Skips sessions < 3 turns.
Hook law: always exit 0, <5s (measured 0.17s on a 55MB transcript), exceptions log to
`drafts/_errors.log` and exit 0. morning-digest.py surfaces pending drafts at SessionStart
("DRAFT CLOSEOUTS PENDING REVIEW: N", fail-open if the dir is missing).

Flips the death-side default: closeout becomes correct-the-draft instead of
remember-to-write. Born from 25 dropped sessions in 48h.

## Design notes for future editors

- proposals frontmatter may carry a DUPLICATED `status:` line (set_status insert bug) —
  always take the FIRST.
- Prediction ledger has non-ISO `-0400` timestamps in old rows — claim-latency handles;
  copy that guard if you parse the same file.
- Mission-control closure = later row, same workstream, state=done; born+done in ONE row
  (same-ts closeouts) is a legitimate episode, not a bug — 381 of 532 closed episodes.
- `recommendations-latest.json` root keys: `candidates, generated, law,
  open_needs_josh_rows, sweep_generated` (envelope, not a bare list).

## Not yet verified / open items

- SessionEnd hook's first REAL firing (fires when the build session ends; prediction
  pred-20261023-013350-39 open on it). Whether SessionEnd fires on kill/crash paths is
  unverified.
- autonomy-nightly's first real launchd fire (04:53 tonight).
- The 7-day INSUFFICIENT→sufficient transition on the bimodality claim.
- Kill-layer's smallest experiment (time one verified-kill → canonized-fix loop) remains
  UNBUILT — it was the fourth named item in the visions and is the natural next build once
  a week of latency data exists.
