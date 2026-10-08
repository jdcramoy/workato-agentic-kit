
## Part 2 — the fractal memory layer + dreaming-team science (added same night)

The five harness scripts in `knowledge/scripts/` complete the system; copy them
into your knowledge tree's `scripts/`:

| Script | What it gives you |
|---|---|
| `fractal.py` (in kb/) | self-similar memory: one factlet schema at every scale (topic/file/section/chunk), zoom retrieval, coverage auditor (`kb fractal coverage` must read AIRTIGHT) |
| `predict.py` | prediction-error protocol: open a prediction before consequential actions, close against reality; deviations spike to the bus |
| `mood.py` | neuromodulation: one broadcast state file (arousal/exploration/risk/verification), 24h decay, spike coupling |
| `calibration.py` | per-agent accuracy + overconfidence gap; weekly calibration cards |
| `dissent_ledger.py` | the dissenter triad with a learning rule — critics that predict real rejections gain weight |
| `rehearsal.py` | counterfactual replay: extract a recipe's historical job fixtures before changing it |

**Memory-authoring rules** (add to your brain/memory rulebook): one file one
topic (H1 = the factlet title); sections are `## `-delimited and written AS
queries (headings are the factlet API); structured facts go in the claims
ledger, not prose; every file has an INDEX line; frontmatter values quoted.

**How you interact with memory does not change**: files stay the source of
truth (human-editable, git-versioned); the fractal layer is a projection
rebuilt incrementally on read. Cutover means the READ path prefers zoom —
never that agents write into SQLite.
