# Getting started with the knowledge base

How knowledge moves through the harness: where it lives, how it lands in the
right place, and the mechanism that carries it from a personal session to the
team corpus. Read this before writing your first knowledge file.

## The two layers (and the one rule that separates them)

**The knowledge tree** (`~/.claude/knowledge/`) is a git repo. It holds
durable, written knowledge: what the platform does, what a project decided,
what a failure taught. This is the layer the team corpus is built from.

**Memory** (per-project `MEMORY.md` files) is a thin pointer index: one line
per fact, the fact itself lives in a knowledge file. Memory tells a session
what to go read. It never carries the content itself.

The one rule: if it would help someone who was not in the conversation, it is
knowledge and gets a file. If it only mattered to that session, it stays in
memory or nowhere.

## Where knowledge goes

`INDEX.md` routes the tree. Everything is one of these:

| You learned | It goes in | Example |
|---|---|---|
| How the platform behaves | `claims/` | "a CLI start read-back confirms the start took" |
| A cross-project technique or trap | `domains/<topic>.md` | AIRO silent-failure patterns, gateway model routing |
| Something only true of one project | `projects/<name>.md` | a build's state, decisions, next steps |
| A reusable procedure | a skill in `~/.claude/skills/` | the manifest-creation SOP |
| A process the whole team follows | standing orders / CLAUDE.md | the manifest rule, the red-team gate |

When in doubt: `domains/` for anything that makes ANY project better,
`projects/<name>.md` for this-project-only state.

## How to write a knowledge file that survives

- One fact cluster per file. A file that is about three things gets consulted
  for none of them.
- Every claim carries its evidence: a job ID, an API response, a file path,
  a count. "Verified 2026-10-15 by live probe" beats "should work".
- Absolute dates only. "As of 2026-10-15" not "recently". The write linter
  flags relative dates, missing frontmatter, and knowledge writes with no
  INDEX update; it annotates rather than blocks, but the annotation is a
  real gap.
- Claims supersede, never edit. A claim that stopped being true gets a new
  line superseding it, so the verification history survives.
- Secrets never live in knowledge files. Tokens go to the keychain; a file
  that names a keychain item is fine, a file that contains a token is an
  incident.

## The mechanism: session to team corpus

1. **You (or an agent) write the knowledge file** in the right directory and
   add the INDEX.md line. The mods record the write.
2. **The live tree is your working set.** Every session that loads the
   harness reads INDEX.md first and follows the pointers. This is why the
   INDEX line is not optional: unwritten pointers mean the file does not
   exist as far as any other session is concerned.
3. **The nightly backup commits the tree** to the brain repo (secrets
   redacted, token-shaped strings refused at push).
4. **The weekly export (Tuesdays 07:27) rebuilds the team corpus repo**
   (`Workato-All/knowledge-corpus`): every knowledge directory is copied,
   operational directories are stubbed, and four sweeps gate the push:
   secrets, people-file names, personal identifiers, non-org emails. A sweep
   failure stops the export; it never edits your source files to pass.
5. **Anyone on the team clones the corpus repo** and reads the same knowledge
   layer your sessions use, minus the operational state and anything
   personal.

## What never leaves your machine

Three classes are denied by the exporter and gitignored in the brain repo:

- **People files** (`knowledge/people/`): your working relationships, mined
  from your own threads. Personal by design.
- **Voice content**: your writing-voice skill and any voice practice reps.
  Teammates build their own from the templates in the kit
  (`personal-identity-templates/`).
- **Operational state**: fleet reports, triage queues, estate snapshots,
  ledgers. The corpus repo carries stubs for these directories so the
  structure stays visible and a policy change can populate them later.

If you find personal content tracked in any repo: `git rm --cached` it, add
the ignore rule, and tell the harness owner. The exporter sweeps for the
known names, but new personal content is a human decision first.

## Seeding your knowledge tree (do this BEFORE the first session)

The kit installer gives you the knowledge-tree SCAFFOLD (scripts, INDEX
template, dreams scaffold) but not the knowledge itself. The team's
accumulated knowledge layer lives in
[Workato-All/knowledge-corpus](https://github.com/Workato-All/knowledge-corpus),
and your harness reads `~/.claude/knowledge/INDEX.md` from one location, so
the corpus clones INTO that location:

    git clone https://github.com/Workato-All/knowledge-corpus.git ~/.claude/knowledge

Order matters if you already ran the kit installer: the installer preserves an
existing `INDEX.md` and adds its scripts on top, so cloning the corpus first
and running (or re-running) `install.sh` after is the clean sequence. A fresh
tree with no corpus clone works, it just starts empty.

No extra configuration is needed: the harness, the mods, the dreamer, and the
exporter all read `~/.claude/knowledge/` because that is where INDEX.md lives.

## How your knowledge reaches the team

Your local tree is a clone of the corpus. Write knowledge locally as above,
commit, and push — but coordinate before pushing new TOP-LEVEL content: the
harness owner's weekly exporter rebuilds the corpus from the owner's tree, so
a teammate file the owner's tree does not have can be removed by the next
export. The safe contribution path today is a pull request (or a heads-up in
the kit channel) so the file lands in the owner's tree too. Files the exporter
does not manage are never touched inside stubbed directories, and personal
content (people files, voice) never commits anywhere.

## Getting started checklist

1. Install the kit (`onboard.sh`, `install.sh`, `verify.sh`), then install
   the KB pack (`workato-dev-kb`: clone, `./install.sh`) so the docs corpus
   and fractal memory are local. The kit installer points at the pack; the
   pack is the library, not the brain.
2. Seed your knowledge tree: clone `knowledge-corpus` into
   `~/.claude/knowledge` (see the section above).
3. Read `knowledge/INDEX.md` end to end once. It is the map.
4. Write one knowledge file about something you learned this week. Put it in
   `domains/` or `projects/`, add the INDEX line, cite one piece of evidence.
5. Contribute it back: commit and push, or open a pull request.
6. Build your own voice skill and people files from the kit templates. Keep
   them personal; they never export.
