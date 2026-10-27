# Error canon loop — deterministic error → memory → canon reinforcement

Born 2026-10-26. Josh: the error→memory→canon mechanism "still needs reinforcement" — the
error-ledger standing order was 100% voluntary (model discipline), and the only deterministic
layer (airo-error-guide.py) had a frozen, hand-curated signature list that never learned.

## The loop (three pieces, all deterministic)

1. **Capture — `~/.claude/hooks/error-sensor.py`** (PostToolUse + PostToolUseFailure, matcher `*`)
   Every tool error (Bash stderr / MCP `is_error` / error markers) appends one event to
   `~/.claude/knowledge/error-events.jsonl`: `{ts, session, tool, sig_hash, signature, snippet}`.
   Signature normalization: lowercase, UUIDs/hex→placeholders, paths→`<path>`, quotes→`<q>`,
   digits→`<n>`, truncate; cluster key = tool + first 40 chars (error text leads with its
   stable part). Zero model cooperation. Never blocks. Runs a promoter pass at most hourly.

2. **Promote — `~/.claude/knowledge/scripts/error-canon-promoter.py`**
   Clusters events by `sig_hash`; a signature seen **≥3 times across ≥2 sessions** becomes a
   canon row in `~/.claude/knowledge/error-canon/error-canon.jsonl`. The session-boundary
   requirement is the retry-storm guard: flailing 5× on one bug in one session does NOT canonize.
   Knobs: `ERRCANON_THRESHOLD` / `ERRCANON_MIN_SESSIONS` env vars.

3. **Replay — same sensor hook**
   On a repeat of a canon signature (fuzzy match: same tool + token overlap coefficient ≥0.7,
   robust to short sigs; one injection per signature per session), the sensor injects:
   `CANON ERROR (seen Nx across Ms): <lesson>` plus the exact `--record` command that
   permanently records the correction. Lesson recorded → subsequent occurrences start corrected.

## The closing command (what a resolving session MUST run)

    python3 ~/.claude/knowledge/scripts/error-canon-promoter.py --record <sig_hash> --lesson "<one line>"

`--list` shows canon rows (hash, count, sessions, lesson status). Recording sets status
`lesson-recorded` — that lesson is what gets injected from then on.

## Division of labor with existing layers

- `error-ledger.md` — voluntary, rich, human-readable; KEEP. The sensor guarantees capture even
  when the ledger row never gets written; canon rows are the machine-readable subset.
- `airo-error-guide.py` — hardcoded immediate remediation for known signatures; unchanged. The
  sensor's canon layer is the LEARNING complement (new errors → counted → guidance).
- `canonize-failure.py` / regression-canon — Workato JOB failures (4-artifact weld). Orthogonal:
  that canon is about recipes; this one is about harness/tool behavior.
- Dreamer — mines transcripts nightly; error-events.jsonl is a new cheap corpus for it.

## Design notes

- Injection-only auto-promotion is deliberate: canon guidance is advice context, never a gate,
  so no Josh sign-off needed for the automatic tier. Lessons that imply behavior beyond retry
  discipline belong in the knowledge tree (the dreamer/gardener promote from there).
- Signature hygiene tradeoff: coarse (40-char) sigs merge same-class errors; the fuzzy matcher
  (0.7 overlap) patches residual token drift. Worst case of a false match is advice text.
- fired.jsonl grows one line per injection (session:hash) — prune with the gardener if large.
