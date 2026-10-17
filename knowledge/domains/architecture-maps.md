# Architecture maps — per-project diagram lifecycle (arch-diagram)

Built 2026-10-08 (Josh's "full documentation lifecycle" idea, grill-gated:
4 recommendations accepted — extend project-dreamer not a 4th agent; skill
auto-invoked by handoff; knowledge tree + Confluence home; two levels).

## What exists

- **Skill `arch-diagram`** (`~/.claude/skills/arch-diagram/SKILL.md`): the
  convention + update procedure. Two mermaid files per project at
  `knowledge/projects/<slug>/architecture/` — `system-map.mmd` (systems/
  flows/triggers) + `asset-graph.mmd` (Workato assets + edges), rendered to
  `.svg` via `npx -y @mermaid-js/mermaid-cli` (~26 s first run incl.
  Chromium, faster after; render IS the syntax check). Node citations
  `src: kf L<n>; tracker`; partial families declared REPRESENTED/OMITTED.
- **Trigger:** handoff skill auto-invokes it ("Architecture diagram
  (auto-step)" in Filing it) whenever Workato/repo assets changed; also
  manually invocable. Confluence SVG publish stays draft-then-approve
  (outward-facing).
- **QA loop:** project-dreamer agent section 5b — nightly per-project lens:
  drift-check asset-graph vs live dependency tracker (diagram usually
  wrong, verify with recipe_get before claiming platform drift), 2-3 `kb`
  best-practice queries with cited doc URLs, findings file through the
  normal dissent-gated proposal pipeline.

## TDD evidence (both tests real)

- RED: fresh subagent, no skill, cold "document the architecture" ask →
  good instincts (chose mermaid) but ad-hoc home, no asset graph, no
  tracker, no trigger, no QA. (Its Multi-Genie output survives as that
  workspace's deep-detail doc, linked from the convention.)
- GREEN: fresh subagent + skill on HR-Genie → both diagrams built, every
  node cited, both rendered clean, AND caught real docs rot (Consumer
  Endpoints folder 35693717 → 35712142, tracker-verified by main session
  same night; correction appended to projects/hr-genie.md).

## Hard-won syntax rules

**Now living in the `mermaid-drafting` skill (2026-10-08) — a SELF-TRAINING
mermaid skill**: `~/.claude/skills/mermaid-drafting/SKILL.md` +
`traps.md` ledger. Loop: read traps → draft → render (the render is the
test) → on ANY failure/visual defect, append the trap (discovery IS
recording; no bare `%%` lines → phantom node confirmed tonight, T-001).
Visual PNG inspection is mandatory. Gardener/dreamer consolidate. Ledger
live-proven: T-007 appended by the skill test agent itself (green test,
same night). Traps T-001..T-007 seeded from the hr-genie pilot night.

Tracker verifies NODES not EDGES (search_recipe_dependencies returns no
caller→callee rows); edge truth = knowledge file, or recipe_get for a
single critical edge (~226 KB flood — deliberate). Tracker node data
outranks the knowledge file.

## First-mover state + gaps

Pilot done: hr-genie. Every other project starts at "no diagram yet" —
created fresh at first handoff that touches assets. Multi-Genie's baseline
deep doc MOVED into the knowledge tree 2026-10-08 (location rule enforced:
architecture docs never live in external workspaces; pointer left behind).
Open: repo copies (docs/architecture/) only when a canonical repo exists,
remaining HR-Genie families (Intelligence Platform etc.) expand
mechanically from the OMITTED header.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [HR Genie — Architecture Map](../../kb-corpus/confluence/extbt/2939977789-hr-genie-architecture-map.md)
- [Talks](../../kb-corpus/eip/talks.md)
- [The Workato KB: RAG++ over all documentation, and the dreaming team](../../kb-corpus/confluence/extbt/2938929237-the-workato-kb-rag-over-all-documentation-and-the-dreaming-team.md)
- [The agents: a nervous system of specialists](../../kb-corpus/confluence/extbt/2938961981-the-agents-a-nervous-system-of-specialists.md)
<!-- kb-bridges:end -->
