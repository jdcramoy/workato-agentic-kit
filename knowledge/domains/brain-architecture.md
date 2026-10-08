# Brain architecture — best practices reference

Loaded by the brain-gardener (Phase 2.3, architecture audit). This file is
the structural rulebook for every file the brain owns: knowledge, memory,
instruction files, skills, agent files. Content quality is the curator's
job (health checks, dedup, claims); THIS file governs shape — size,
modularity, indexes, frontmatter, routing surfaces.

Sources: Anthropic's Claude Code docs (memory/CLAUDE.md conventions,
skill authoring, agent definitions), Josh's house patterns (INDEX.md
router, thin MEMORY.md, claims ledger). Grounded 2026-10-07.

## Size budgets (house defaults)

| File type | Budget | Over budget → |
|---|---|---|
| Knowledge domain/project file | ~300 lines | split into hub + reference files |
| Agent definition (`~/.claude/agents/*.md`) | ~200 lines | move procedure detail to a knowledge file loaded on use |
| Global CLAUDE.md (`~/.claude/CLAUDE.md`) | ~150 lines | extract topic blocks to linked files |
| Project CLAUDE.md | ~150 lines | same |
| Auto-memory file | ~40 lines | split or move state to its project knowledge file |
| MEMORY.md / INDEX.md | one line per entry | nothing else belongs there — ever |
| Skill SKILL.md | ~200 lines (hard ceiling ~500) | move detail to `reference/` files, scripts to `scripts/` |

Budgets are tripwires, not hard walls: a file 10% over with a reason to
stay whole is fine. A file 2× over is always a finding.

## Per-type rules

### Knowledge files (`~/.claude/knowledge/`)

- INDEX.md is a router: one line per file, hook not summary. No content,
  no prose paragraphs, no duplicate state in the index.
- Scope test decides the home: any-project durable → `domains/`; this
  project's next session → `projects/<name>.md`; procedures → skills;
  enforced rules → mods/hooks. Content in the wrong layer is a finding.
- Hub-and-reference pattern for big topics: keep the hub (what it is,
  current state, pointers) in `domains/`; push deep reference material
  (full SOPs, append-only logs, long tables) to a sibling `*-reference.md`
  or into the project repo. Pointer links both ways.
- POINTER pattern: when state ownership moves (e.g. a memory file points
  at a project knowledge file), leave a one-line POINTER, don't copy.
- Dated assertions: every "current state" claim carries an absolute date
  so temporal rot is detectable.

### Auto-memory (`memory/` + MEMORY.md)

- One memory = one fact, with complete frontmatter (name, description,
  metadata.type: user/feedback/project/reference).
- MEMORY.md is a thin index: `- [Title](file.md) — hook`. One line per
  memory. Any real content in MEMORY.md is a finding.
- Don't store what the repo already records (code structure, git history,
  CLAUDE.md contents). Stale-workflow memories pointing at moved files are
  worse than no memory.
- Large per-project state belongs in the project knowledge file, with the
  memory reduced to a POINTER.

### Instruction files (CLAUDE.md, global and project)

- Every line is rent paid on EVERY session in scope — the global file
  loads unconditionally. Ruthless economy; link, don't inline.
- Shared content across files → `@import` or pointer, never a copy
  (the VUA contradiction class is born of copies).
- Rules that must be ENFORCED belong in hooks/settings.json, not prose.
  A behavioral rule written only as prose is a wish, not a rule — flag
  prose-that-should-be-a-hook as a finding (proposal: hook spec).
- When a file mirrors another (e.g. workbench CLAUDE.md mirroring
  ~/Documents), say "parent file is authoritative" in the mirror.
- Never inline large reference material (tool catalogs, gotcha lists) —
  those live in skills/knowledge files loaded on use.

### Skills (`~/.claude/skills/`)

- The `description` field is the ROUTING SURFACE: it must say WHEN to use
  the skill (trigger phrases, "use when", "use whenever"), not just what
  it is. A skill with a label-description won't be invoked.
- Progressive disclosure: SKILL.md stays lean (budget above); deep detail
  goes in `reference/` files loaded on demand, executable helpers in
  `scripts/`. Claude reads the frontmatter always, the body when relevant,
  references only when needed.
- One skill = one capability. A skill accreting a second unrelated
  procedure is a split finding.
- Skills are procedures, not facts: durable facts go to knowledge files;
  the skill references them, doesn't restate them.

### Agent files (`~/.claude/agents/*.md`)

- Same routing-surface rule for `description`: name the invocation
  triggers ("use when Josh asks to...", "use PROACTIVELY on a schedule").
- The agent file holds role + procedure skeleton; lookup-heavy content
  (checklists, catalogs, glossaries) goes in a knowledge file the agent
  loads on use — the agent file should survive being read fresh every run
  without flooding context.
- Overlap check: two agents claiming the same trigger is a routing
  conflict — propose the boundary line or a merge.
- `tools:` frontmatter is intentional scope, not decoration; flag agents
  with unconstrained `*` tools that are advisory-only by design.

## Anti-patterns (each is a Phase 2.3 finding)

1. **Index bloat** — content creeping into MEMORY.md/INDEX.md.
2. **Monolith drift** — file grown past budget by accretion; propose the
   split map (what stays, what moves, what links where).
3. **Copy drift** — same rule/content in 2+ files, versions diverging.
   Propose canonical home + pointers.
4. **Prose that should be a hook** — enforced behavior written as
   instruction text.
5. **Dead label skills** — description doesn't say when to use; skill
   silently never invoked.
6. **Layer violation** — content living in the wrong ground (facts in a
   skill, procedure in a knowledge file, project state in a memory).
7. **Routing conflict** — overlapping agent/skill triggers with no
   boundary rule.
8. **Pointer rot** — POINTER/index lines naming files that moved or died.

## Modularization SOP (how to propose a split)

1. Measure: `wc -l` every candidate; list over-budget files with counts.
2. For each, draw the split map: hub keeps identity + current state +
   pointers; reference gets the deep material; every moved section leaves
   a pointer line behind.
3. Name the new files before creating content — file names are API.
4. Proposals land like all others: `gardener/*` branch, diff vs main,
   evidence (line counts + the sections that motivated the split).
5. After any accepted split, update INDEX.md/MEMORY.md lines in the same
   commit — an unmoved index makes the split worse than the monolith.
