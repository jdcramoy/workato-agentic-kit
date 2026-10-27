# Decisions judgment: the Jev replica arc

What this file is: the plain primer for the 2026-10-23/24 judgment-engine arc.
A future session asking "why is there a STATE block on triage cards", "can we
use an ensemble judge", or "is the decisions engine allowed to filter" gets the
whole story here. Primary state lives in the memory
`jev-typesafe-system-one.md`, the scripts, and the verdict ledgers; this file
explains the arc and the doctrine, it does not restate every number.

## What is Jev and why did we replicate it

Jev is TypeSafe AI's "System One" model (https://docs.typesafe.ai, evaluated
2026-10-23): send state plus typed questions, get typed answers with full
probability distributions (Choice, Score, Noul, Box). No text generation, only
calibrated judgment. Josh's ruling: costs money, needs a license, probably
cannot be adopted, so the house replicates the functionality.

The decode that made replication plausible: confidence is not model output, it
is arithmetic on the probability distribution (for Choice with k options,
`(k*max_p - 1)/(k-1)`). The only licensed layer is a distribution trained for
calibrated decisions. Everything else, the typed contract, the confidence stat,
the patterns, is code. decisions.py (banked 2026-10-14 from OpenAI's Decisions
API contract) already implements that contract 1:1; what was missing was a
trustworthy judgment engine.

## What the four backtests found

Four backtests against Josh's actual triage verdict corpus settled the design.
Scripts: `scripts/backtest-jevish.py` (spike 1), `scripts/backtest-jevish3.py`
and `scripts/triage-state.py` (iteration 3), `scripts/backtest-jevish4.py` and
`scripts/precedent.py` (iteration 4). Vote ledgers:
`knowledge/decisions/backtest-jevish.jsonl`, `backtest-jevish3.jsonl`. Total
model spend about $1.86.

1. Spike 1 (2026-10-23, 79 findings x 6 calls, $0.15): the ensemble is dead.
   N=5 voting scored 0.49 accuracy, WORSE than fresh single-call verbalized
   (0.61) and below the 0.63 majority baseline. Root cause read from the vote
   ledger: 19 of 50 rejected rows got UNANIMOUS true votes. The blindness is
   correlated across voters, so voting sharpens bias instead of canceling it.
   Isotonic calibration worked as theory predicts (ECE 0.249 to 0.132) but
   monotone transforms cannot fix ranking. Urgency was inverted.
2. Iteration 3 (2026-10-23, $0.19): state assembly is the product. Building
   leak-free state (lane semantics, prior decisions with Josh's notes, sibling
   verdicts, ticket coverage, lexical flags, age) lifted single-judge accuracy
   0.61 to 0.71, the first judge above the majority baseline, and collapsed the
   unanimous-TRUE-on-rejected failure (mc-fixloop cluster 1.00 to 0.0-0.35).
   Still: no arm cleared the 0.8 flip gate and urgency stayed inverted.
3. Iteration 4 (2026-10-24, 80 findings, $1.52): precedent retrieval is the
   biggest model-side lever in the whole arc. On the 48-row residue (54.2
   percent reject), flash plus precedents scored 0.62 where flash alone
   scored 0.25 (+37 points, against a 0.54 always-reject baseline), while
   kimi, a pricier model (about 14x input by the script's price table),
   scored 0.35 and CoT 0.38. Corrected 2026-10-25 after the dissenter
   recomputed the ledger: the earlier "25x" and "79-percent-reject" figures
   were misquotes; the +37 partly reflects flash-alone miscalibration. Two
   falsifications: the
   aggressive composite rules underperformed the conservative spike-3 source
   rule (0.59 vs 0.81, over-settling on sibling-coverage semantics), and
   decay-anchored urgency stayed inverted (8 of 8 configs across the arc).
   LLM-judged urgency is dead on this surface, full stop.

## What shipped live

All live wiring landed 2026-10-23/24, Josh-approved:

- STATE blocks on every open triage card: `triage-decide.py list` renders a
  compact block under each card, assembled by `scripts/triage-state.py`
  (verdict-time for the backtest path, as-of-now for open cards). The triage
  SKILL.md instructs cards to carry it verbatim. Graceful degrade on assembler
  error plus a `TRIAGE_STATE=off` kill switch. Verified live on 59 open cards
  (2026-10-23), wiring re-verified by the gardener 2026-10-24.
- Reason codes: `--reason` on triage-decide writes explanation codes to
  `knowledge/triage/verdict-reasons.jsonl` (44 backfilled by 2026-10-24; 33 of
  44 stale, confirming the dissenter's original staleness diagnosis).
- Precedent index: `scripts/precedent.py`, 413-row k-NN over the verdict
  ledger including Josh's notes. Precedent notes are the taste-transfer
  channel.
- Shadow judge: `scripts/shadow-judge.py` runs blind predictions in /triage
  step 1. First live run 2026-10-24: 54 of 66 cards rule-settled with zero
  model calls, 12 judged.
- Corpus exporter: `scripts/verdict-corpus.py` (413 verdicts, 50 reason-coded
  as of 2026-10-24). The fine-tune endgame ("Jev at home") self-tracks its own
  gate at 200 reason-coded verdicts.

## The standing doctrine

- Final architecture: CONSERVATIVE rules only (source lanes plus same-slug
  prior decisions, settle where near-certain, abstain elsewhere), then a flash
  judge with state plus precedents on the residue, then isotonic calibration,
  then Josh. Skip ensembles, skip kimi, skip CoT. Note the empirical ordering:
  the single best measured arm was a one-line source RULE (0.81), ahead of
  every cascade; context is the strongest model-side lever, rules are the
  strongest lever overall. No arm passed the 0.8 flip gate.
- Build a better judge in this order: decompose into factors with per-factor
  evidence channels (only "valuable?" is judgmental residue), precedent
  retrieval, reason codes at verdict time, shadow mode with live calibration,
  model upgrades last, fine-tune at 200 coded verdicts.
- Urgency must come from objective fields (prod, blast radius, deadline) or
  not at all. Never from an LLM rating text.
- ORDER-NEVER-FILTER stands: no arm cleared the flip gate (0.8 accuracy plus
  non-inverted urgency on 20 or more blind verdicts), so no automated judge
  filters Josh's queue. The judge informs cards; Josh decides.

## House lessons worth keeping

1. Context beats model class. On the identical residue, a small model with
   state and precedents beat a 25x-more-expensive model without them. The
   correlated-blindness finding explains WHY ensembles fail: shared blind spots
   survive voting.
2. Calibration fixes confidence, not ranking. Fit isotonic on your own verdict
   ledger rather than trusting a vendor's generic distribution.
3. Verdict-time reason codes are the only way Josh's private state becomes
   training data. Collect them from day one.

## Related

- Memory: `~/.claude/projects/-Users-YOUR-USER-Documents-workbench/memory/jev-typesafe-system-one.md` (full spike detail)
- INDEX line: scripts/triage-state.py entry; decision ledgers in `knowledge/decisions/`
- Predecessor: `domains/` decisions-engine-uat-failure memory (decisions.py banked contract)
- Position piece: `positions/context-beats-model-class.md` (2026-10-25, dissent logged)
