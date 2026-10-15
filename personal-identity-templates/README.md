# Personal identity templates (voice skill + people files)

The two files that make the harness write AS you and FOR your relationships.
They are deliberately NOT auto-installed and NOT shipped in any shared export:
they become YOUR personal content the moment you fill them in.

## What each one is

- `writing-voice-SKILL-template.md`: the template for a user-scope skill that
  makes every session draft prose in your voice. Copy it to
  `~/.claude/skills/<your-name>-writing-voice/SKILL.md`, fill every section
  from 10-20 REAL sent samples (the template's first section explains the
  mining procedure), and restart Claude Code. Voice only, never subject
  matter: the file must not contain opinions about people, private context,
  or anything you would not post on a wall.
- `people-file-template.md`: the template for `knowledge/people/<first-last>.md`,
  one per regular correspondent. Built by mining your real threads; carries
  comms style with evidence quotes, shared context, and drafting notes.

## How they interact

Voice skill = the base register (how YOU write). People file = the
per-recipient overlay (how you adapt to THEM). A drafting session reads both,
in that order. Neither exists? Drafts fall back to plain assistant voice,
which is why the voice skill is the first one to build.

## Privacy rules (load-bearing)

- Both live under your local harness only. The brain repo's `.gitignore`
  excludes `people/`, `domains/voice-reps/`, and the voice files, and
  `knowledge-export.sh` (the team-corpus export) refuses to ship content
  matching people-file names or personal account identifiers.
- Never commit a filled-in voice skill or people file to ANY repo. If you
  find one tracked anywhere, `git rm --cached` it and add the ignore rule.

## Install (manual, on purpose)

    mkdir -p ~/.claude/skills/<your-name>-writing-voice
    cp personal-identity-templates/writing-voice-SKILL-template.md \
       ~/.claude/skills/<your-name>-writing-voice/SKILL.md
    # then edit it against your real sent samples, and restart Claude Code

    mkdir -p ~/.claude/knowledge/people
    cp personal-identity-templates/people-file-template.md \
       ~/.claude/knowledge/people/_TEMPLATE.md
    # copy it per person as you build out your ring
