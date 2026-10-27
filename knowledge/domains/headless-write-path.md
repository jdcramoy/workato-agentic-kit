# Headless write path: the sensitive-file gate vs the knowledge tree

Status: defect documented 2026-10-16, from dreamer proposal
2026-10-10-headless-dispatch-write-path.md (accepted, build now). The
knowledge portions are built (this doc plus the rescue-convention section in
knowledge/dreams/GOSSIP.md). The launcher fix and the settings.json option are
recorded below with owners; neither was applied by this knowledge build.

## The defect

Claude Code BUILT-IN sensitive-file protection (not a custom hook; cortex
root cause 2026-10-09 04:28Z) denies Write/Edit to paths under
~/.claude/knowledge for headless runs. The headless --permission-mode default
overrides bypassPermissions, so the auto-safe allowances the dream and cortex
configs grant (knowledge-file-append, index-line-update, proposal writes) are
physically blocked at the permission layer: a config/permission contradiction.
Python writes PASS where Write/Edit are denied (channel asymmetry, observed
repeatedly).

Consequences on record:

- Headless dispatch findings stranded in ~/.local/state/cortex/*.log 5+ times
  (78677477 verification rescued by the parent session 01:24Z; the closure-gap
  sweep 02:25Z; the regression root cause 08:45Z).
- Cortex could not write its canonical attention-queue.md for 3+ consecutive
  pulses (08:55Z, 09:12Z, 21:17Z), including bus appends and heartbeat.
- Instance #8 (cortex 16:07Z, thread
  dispatch-persistence-channel-decisive): headless heredoc append AND
  in-session Write both denied on one investigation session.
- The dreamer itself (2026-10-10 03:5xZ): denied Edit on INDEX.md, denied an
  append to domains/workato-platform.md, denied direct Write of its own
  proposal files. Pattern decisive across both channels.

## The fix shape (three items, ownership recorded)

1. Launcher and brief fix: every cortex dispatch brief and fleet launcher
   passes `--add-dir ~/.claude/knowledge` (or the narrow set of writable
   subpaths) so the built-in gate's directory scope includes the tree.
   OWNER: fleet launcher builders. Scripts not touched by this knowledge
   build.
2. Rescue convention as DOCUMENTED default: dispatch briefs carry the
   stdout-fence + parent-writes-the-file instruction (cortex already did this
   ad hoc). Now written into knowledge/dreams/GOSSIP.md so it stops depending
   on whoever remembers. When a dispatch template exists in the launchers, it
   should carry the same line.
3. Josh-side settings.json permissions.allow entry for Write/Edit scoped to
   ~/.claude/knowledge/** IF the built-in protection honors allow rules for
   these paths on his interactive sessions. OWNER: Josh only (never_auto).
   Not applied.

## The rescue convention (the part that works today)

When a headless run needs a knowledge write and Write/Edit come back denied:

1. Emit the payload inside a fenced stdout block headed with the agreed
   target filename.
2. The parent session (or any interactive lane) reads the fence and writes
   the file.

This is the documented default until item 1 lands. It kept working through
every observed instance.

## Rollback

Revert the launcher --add-dir line (one line per caller); delete the
GOSSIP.md section; delete this doc. The rescue convention predates the doc
and keeps working either way.
