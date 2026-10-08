---
name: arch-diagram
description: Use when a project session is ending and Workato/repo assets changed, when writing a handoff (handoff skill auto-invokes this), or when Josh asks to "update the architecture diagram", "map the architecture", or "diagram this project". Also the diagram-refresh entry point for project-dreamer's architecture-QA lens. Produces the project's two-level mermaid architecture map and its rendered SVGs.
---

# Arch Diagram

Every project gets a **two-level architecture map as mermaid source**, living
in the knowledge tree, updated at session end, rendered to SVG, and QA'd by
the project-dreamer. Mermaid source is the source of truth: diffable, git-
trackable, renders on GitHub/VS Code; SVG is the Confluence-ready render.

## Where it lives (fixed convention — never invent a new home)

```
~/.claude/knowledge/projects/<project-slug>/architecture/
  system-map.mmd      # level 1: systems, connections, data flows, triggers
  asset-graph.mmd     # level 2: the project's Workato assets and their links
  system-map.svg      # rendered (npx -y @mermaid-js/mermaid-cli -i x.mmd -o x.svg)
  asset-graph.svg
```

`<project-slug>` matches the knowledge file name (`projects/hr-genie.md` →
`projects/hr-genie/architecture/`). **Enforcement: ALL architecture
documents live in the knowledge tree — never in an external project
workspace.** If a deep-detail diagram doc already exists in a workspace,
MOVE it here (leave a pointer file behind) rather than linking across
trees; workspace docs rot silently, the knowledge tree is curated. Deep
docs linked from `system-map.mmd` comments must also live here.

## The two levels

**Level 1 — system map** (`flowchart LR` or `TD`): external systems, the
Workato project as one node (or a few for large projects), connections,
data flows, trigger sources (cron, webhook, Slack event), downstream
consumers. This is the map a new joiner reads first.

**Level 2 — asset graph** (`flowchart TD`): every recipe/function/data
table/API endpoint in the project, edges for caller→callee, recipe→table
read/write, and MCP/Genie attachment. Node label = asset name + ID. Every
node MUST cite a source in a `src:` tag — `src: kf L<n>` for knowledge-file
lines, `; tracker` when the dependency tracker confirmed it live. **No
vibes: an asset you cannot source does not go in.** A partially-mapped
project states this in a header comment block: an explicit
`REPRESENTED: ...` / `OMITTED: <family> (asset IDs, kf lines)` list, so
expansion later is mechanical.

**Node vs edge truth:** the dependency tracker verifies NODES (which
recipes/tables exist, where) but not EDGES — `search_recipe_dependencies`
returns recipe rows with no caller→callee relations. Edge truth comes from
the knowledge file (or a `recipe_get` — ~226 KB per recipe, deliberate
flood, use only when one edge really matters). Tracker node data outranks
the knowledge file on conflict: the knowledge file is where docs rot hides.

**Mermaid syntax rules (learned the hard way):** header `%%` comments
usually work, but a bare `%%` line or certain comment forms before the
diagram-type declaration produce a confusing `Expecting NEWLINE got
NODE_STRING` parse error. If a render fails with that message, the fix is
to make the declaration (`flowchart LR`) LINE 1 and move comments after
it — asset-graph needed this, system-map did not. When in doubt,
declaration first. Change-log lines live at the bottom:
`%% 2026-10-08 <what changed and why> %%` (cap 10, drop oldest).

## Update procedure (run at handoff, or on "update the diagram")

1. Read the project knowledge file + this session's asset changes.
2. If Workato assets changed this session, get live truth: dependency
   tracker (`search_recipe_dependencies`) for the project's recipes, or an
   AIRO folder/recipe list. Docs rot; the tracker and recipe_get do not.
3. Read the existing `.mmd` files (if any). Update ONLY what changed; keep
   the rest byte-identical so git diffs stay meaningful.
4. Append one line to the change-log comment block at the bottom of each
   file: `%% 2026-10-08 <one-line what changed and why> %%` (cap 10, drop
   oldest).
5. Render both to `.svg` with mermaid-cli. A render failure = a mermaid
   syntax error — fix it, never ship an unrendered diagram.
   **REQUIRED SUB-SKILL: use `mermaid-drafting`** for all mermaid craft —
   read its `traps.md` before drafting, and every render failure or visual
   defect discovered here gets appended to that ledger (self-training:
   discovery IS recording).
6. Repo copy: if the project has a canonical repo, copy the `.mmd` sources
   into its `docs/architecture/` too (knowledge tree stays the master).

## Confluence (the documentation lifecycle)

If the project has a Confluence page: draft the SVG attach/embed (Confluence
does not render mermaid natively — the SVG is the deliverable) and show the
draft for approval before publishing, per the handoff rule. Publishing is
outward-facing; never post silently.

## QA loop (who checks the diagrams)

project-dreamer's architecture-QA lens reads these diagrams nightly for the
active project and cross-checks them against the live dependency-tracker
graph and Workato best practices (`kb`). Drift and violations come back as
dissent-gated proposals. You do not self-certify the diagram — the dreamer
is the second pair of eyes.

## Common mistakes

| Excuse | Reality |
|--------|---------|
| "I'll draw it from memory of the session" | Session memory is not a source. Dependency tracker + knowledge file, or nothing. |
| "One big diagram is fine" | One mega-diagram drifts fast and renders unreadable. Two levels, always. |
| "SVG skipped this time" | Unrendered = unverified. Render is the syntax check. |
| "New project, no diagram yet" | Create both files fresh at first handoff — that IS the convention's start state. |
