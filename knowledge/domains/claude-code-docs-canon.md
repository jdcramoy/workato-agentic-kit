# Claude Code docs canon — official best practices for knowledge, memory, skills, file trees

The Brain Gardener's rulebook for auditing Josh's instruction files, auto
memory, skills, and settings layout. Every rule below is from OFFICIAL
documentation, fetched 2026-10-07 (sources listed at bottom). Where Josh's
harness deliberately diverges, the divergence is stated — the harness policy
wins, never the default.

## 1. Instruction files (CLAUDE.md / rules)

Load model: CLAUDE.md + CLAUDE.local.md load from cwd and every directory
above it, concatenated root-down (closer to cwd loads last, reads last).
Subdirectory CLAUDE.md files load on demand when Read/Write/Edit touches a
file there. `@path` imports expand at launch (max depth 4 hops; imports do
NOT save context — they all load). Block-level HTML comments are stripped
from context (use them for human-only notes).

- **Size: target under 200 lines per CLAUDE.md file.** Longer = more context
  consumed AND measurably lower adherence. Move single-topic content to
  path-scoped rules.
- **Concrete over vague:** "Use 2-space indentation" not "format properly".
  Instructions Claude can verify follow reliably; vague ones don't.
- **Contradictions are poison:** if two instruction files conflict, Claude
  may pick either arbitrarily. Cross-file consistency is an audit item.
- **`.claude/rules/`**: one topic per file; `paths:` frontmatter scopes a
  rule to file globs (loads only on matching Read/Write/Edit). User-level
  rules live in `~/.claude/rules/` and load before project rules. User rule
  vs project rule conflict = either may win — keep them consistent.
- **CLAUDE.md is context, not enforcement:** anything that MUST happen at a
  lifecycle point (pre-commit, post-edit) belongs in a hook, not a rule.
  Settings (`permissions.deny` etc.) are client-enforced; CLAUDE.md is not.
- `/doctor prompt-audit` (v2.1.283+) audits all instruction surfaces for
  outdated refs, dead file paths, cross-file contradictions. `/doctor` trims
  code-derivable content (directory layouts, dependency lists) keeping
  pitfalls, rationale, and non-default conventions.
- **Audit hooks for the gardener:** CLAUDE.md over 200 lines; instructions
  restating what the code shows; dead `@path`/file references; cross-file
  contradictions; multi-step procedures living in CLAUDE.md that belong in
  a skill; "always do X at moment Y" rules that belong in a hook.

## 2. Auto memory (`~/.claude/projects/<slug>/memory/`)

Per-project (derived from git repo; all worktrees/subdirs share one dir);
machine-local, never synced. MEMORY.md is the index — first **200 lines or
25KB** loaded at session start, whichever first; the rest silently dropped.
Topic files are NOT loaded at startup — read on demand. Claude Code stamps
a `modified` ISO-8601 frontmatter field on writes (v2.1.214+).

- **Type taxonomy is closed:** `user` (role, expertise, preferences),
  `feedback` (corrections + confirmed approaches), `project` (ongoing work,
  deadlines, decisions not derivable from code/git), `reference` (pointers
  outside the project). Memory type = frontmatter `type` field.
- **Skip rule:** never save what's derivable from the codebase (architecture,
  file paths, past fixes) or already stated in CLAUDE.md.
- **Index hygiene:** one line per memory in MEMORY.md; detail lives in topic
  files; Claude Code warns near the limit and errors (rewrite required) when
  over it, because overflow is dropped on next load.
- **Audit hooks for the gardener:** MEMORY.md line count + byte size vs the
  200-line/25KB caps; entries whose detail leaked into the index instead of
  a topic file; wrong/missing `type`; stale entries (cross-check `modified`);
  memory content duplicated in a knowledge file (and vice versa); derivable-
  from-repo content that should never have been saved.

## 3. Skills (Agent Skills spec + authoring best practices)

Three-tier progressive disclosure: (1) metadata ~100 tokens pre-loaded at
startup for EVERY skill; (2) SKILL.md body loaded on activation (<500 lines,
<5000 tokens recommended); (3) bundled files/scripts loaded or executed only
on demand. The description is the routing surface — Claude selects from 100+
skills by description alone.

- **Frontmatter rules:** `name` ≤64 chars, lowercase letters/numbers/hyphens
  only, no leading/trailing/double hyphens, no "anthropic"/"claude" reserved
  words, MUST match the parent directory name. `description` ≤1024 chars,
  non-empty, no XML tags. Optional: `license`, `compatibility` (≤500 chars,
  only when env requirements exist), `metadata` (string→string map),
  `allowed-tools` (experimental).
- **Description = what + when,** third person, with concrete trigger terms
  ("Use when..."). Vague descriptions ("helps with documents") cause missed
  or wrong activation — the #1 discoverability failure.
- **Naming:** gerund form preferred (`processing-pdfs`); avoid vague
  (`helper`, `utils`) and over-generic (`files`, `data`).
- **Conciseness:** assume the model is smart; only add context it doesn't
  have. Cut explanations of well-known concepts.
- **Degrees of freedom:** high freedom (prose guidance) for context-dependent
  work; low freedom (exact scripts, "do not modify") for fragile/critical
  sequences. Match specificity to fragility.
- **References one level deep** from SKILL.md (deep chains get previewed
  with `head`, not fully read). Reference files >100 lines get a table of
  contents. No deeply nested reference chains.
- **No time-sensitive content** ("before August 2025 use X") — use an "old
  patterns" collapsible section instead. Consistent terminology throughout.
- **Scripts:** solve, don't defer (handle errors in the script; don't fail
  and let Claude improvise). No voodoo constants — every value justified.
  State explicitly whether Claude should EXECUTE a script or READ it as
  reference. Prefer scripts for deterministic work (reliable, token-free
  until output).
- **MCP tools in skills: fully qualified `ServerName:tool_name`** — bare
  names fail to resolve with multiple servers installed.
- **Evaluation-first:** build 3+ evaluation scenarios BEFORE writing docs;
  measure baseline without the skill; iterate Claude A (author) vs Claude B
  (user) on real tasks.
- **Audit hooks for the gardener:** every skill's SKILL.md vs this checklist
  (name/dir match, description quality, line count, one-level refs, stale
  date-sensitive content, reserved words). Prioritize by the usage ledger —
  high-traffic skills get audited hardest. Validate frontmatter mechanically
  where possible (skills-ref validate style checks: name charset, dir match,
  description presence/length).

## 4. Settings & config file tree

Four scopes, highest precedence first: **managed → command line → project
local (`.claude/settings.local.json`) → shared project (`.claude/settings.json`)
→ user (`~/.claude/settings.json`)**. Higher setting wins per key. List keys
(permissions.allow etc.) MERGE across scopes instead of overriding. A few
security keys honor the stricter value from any scope.

- Settings are strict JSON — no comments, no trailing commas; broken file =
  Settings Error at startup. `~/.claude.json` is Claude-managed state (never
  hand-edit; backups in `~/.claude/backups/`).
- Repo-committed keys need folder trust before they apply; `deny`/`ask`
  apply immediately, `allow` waits for trust. Some keys NEVER apply from a
  repo file (scoped `User, local, or managed` in the settings index).
- `/status` shows which sources loaded; `claude doctor` lists rejected
  entries. Settings edits hot-reload mid-session (except a few
  session-start-only keys like `model` — use `/model`).
- **Audit hooks for the gardener:** same key set in conflicting scopes;
  permissions sprawl in the wrong file (personal rules in shared files,
  team rules in local files); dead allow/deny patterns; invalid JSON.

## 5. Where Josh's harness deliberately diverges (harness policy wins)

- The knowledge TREE (`~/.claude/knowledge/`) is the durable store, not
  bloated CLAUDE.md files — audit the tree with these rules but never
  propose merging it into CLAUDE.md. Auto-memory MEMORY.md stays a thin
  index INTO the knowledge tree.
- Brain-guard write-lint + usage telemetry already enforce part of section 2
  (frontmatter presence, INDEX.md touch); the gardener cross-checks the
  ledger rather than re-linting.
- Claims ledger (`claims/claims.jsonl`) supersedes plain memory for durable
  platform facts: claims carry evidence + confidence + last_verified. Audit
  claims with the claim-verification skill cadence.

## Sources (official, fetched 2026-10-07)

- Memory / CLAUDE.md / auto memory: https://code.claude.com/docs/en/memory
- Skill authoring best practices: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices
- Agent Skills specification: https://agentskills.io/specification
- Settings files and precedence: https://code.claude.com/docs/en/settings
- Raw fetched copies (for re-checking without refetch):
  `~/.claude/projects/project-transcript-slug/e3d917bf-b780-483c-99a5-2afe643d743c/tool-results/docs/`
  (session-scoped — refetch if gone)

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [Prompting best practices](../../kb-corpus/claude/docs_en_build-with-claude_prompt-engineering_claude-prompting-best-practices.md.md)
- [Prompting Claude Opus 4.8](../../kb-corpus/claude/docs_en_build-with-claude_prompt-engineering_prompting-claude-opus-4-8.md.md)
- [Tool search tool](../../kb-corpus/claude/docs_en_agents-and-tools_tool-use_tool-search-tool.md.md)
- [Prompting Claude Fable 5](../../kb-corpus/claude/docs_en_build-with-claude_prompt-engineering_prompting-claude-fable-5.md.md)
<!-- kb-bridges:end -->
