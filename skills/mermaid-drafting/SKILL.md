---
name: mermaid-drafting
description: Use whenever drafting, editing, rendering, or debugging any mermaid diagram - flowcharts, architecture maps, sequence diagrams, any .mmd source. Self-training: carries a traps ledger that every render failure or visual defect gets appended to, so drafting improves with every discovery without Josh calling traps out.
---

# Mermaid Drafting (self-training)

Drafting craft for mermaid diagrams. The skill has two parts: the
conventions here, and the **traps ledger** (`traps.md` beside this file) —
the accumulated gotchas from every diagram session in this harness. It
improves itself: discovery IS recording.

## The loop

1. **Read `traps.md` first** (same directory). It is small by design. The
   known failure modes are listed there, not here.
2. Draft using the conventions below.
3. **Render — the render is the test.** A diagram that has not rendered
   successfully does not exist. `npx -y @mermaid-js/mermaid-cli -i x.mmd
   -o x.svg` (add `-s 3` for inspection-grade PNGs).
4. **On ANY render failure or visual defect (phantom nodes, unreadable
   layout, clipped labels), fix it AND append the trap to `traps.md`.**
   One line: `T-<next-id> | symptom | cause | fix`. This is a hard rule,
   not a suggestion — a trap you hit twice because you skipped the entry
   the first time is a self-training failure. If a trap turns out wrong
   or too narrow, correct the entry in place.
5. Visual inspection: convert to PNG and LOOK at it (Read tool) before
   calling a diagram done. Grep-verified SVGs still ship phantom boxes.

## Conventions

- Diagram-type declaration first; comments after (trap T-002).
- Label text: `<br/>` for line breaks, `<i>...</i>` for citation/meta
  lines, emoji as role markers work fine.
- `classDef` + `class` for node typing; style subgraphs for family
  grouping; `direction TB` inside subgraphs to control per-family flow.
- Sources/citations live INSIDE node labels (trailing italic line), never
  as external prose — diagrams get detached from their docs.
- Prefer many small files over one mega-diagram; compose at the page level.

## Consolidation

Duplicates in `traps.md` get merged and entries past ~40 lines get
reviewed for promotion into the conventions above — the brain gardener and
project-dreamer's architecture-QA lens (§5b) do this on their existing
schedules. The ledger grows append-only between reviews.
