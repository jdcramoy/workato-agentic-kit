# <Person Name> — people file template

One file per person you work with regularly, at `knowledge/people/<first-last>.md`.
The file exists so any session can draft to, about, or around this person with
the relationship already loaded: who they are, how they communicate, what your
standing context with them is. Build it by MINING EVIDENCE (Slack history, org
chart, past threads), never by guessing; every claim carries its source and
date the same way knowledge files do.

Copy this file to start a new one. Delete the guidance comments as you fill it.

```markdown
# <Person Name>

- Slack: @handle (member ID)
- Email: address
- Pronouns: as stated on Slack, or "not stated (do not guess; use the name)"
- Timezone: <tz>
- Title: <title>
- Org: <team, reports-to>
- Your chain to them: <you → … → them>, distance N
- Tenure: hired <date> if known
- Source: <where this came from — org-chart snapshot, Slack mining pass>, <date>

## Comms style with you (Slack-mined <date>)

- How they actually write to you: fragments or prose, formality, banter level.
  Quote 2-3 REAL lines as anchors.
- What they come to you for, and what you go to them for.
- Response-time expectations and channel norms (DM vs channel, async vs urgent).

## Shared context (running)

- Standing threads, in-flight work, promises made either way, open loops.
- Date every line; drop or archive resolved ones.

## Drafting notes

- What lands: formats, lengths, tones that have worked with this person.
- What does not: the specific things to avoid with THIS person.

## Never in this file

- Opinions you would not say to their face, performance judgments, HR-class
  information (comp, health, personal circumstances), anything from
  confidential channels. The file makes you a better correspondent, not a
  dossier-keeper.
```

## How people files and the voice skill interact

The voice skill (`<owner>-writing-voice`) is the BASE REGISTER: your punctuation,
structure, and tone, mined from your own sent samples. It applies to every
draft. The people file is the PER-RECIPIENT OVERLAY: shared context, comms
style, and drafting notes for one relationship. A drafting session reads both:
voice skill first (how you write), people file second (how you adapt to this
reader). No people file exists? Voice alone carries it.

## Privacy rules (load-bearing)

- `knowledge/people/` and the voice skill are PERSONAL. They are gitignored in
  the brain repo and excluded from every shared export. Verify before any push
  or export: the mechanical sweep in `knowledge-export.sh` fails the export if
  a people-file last name appears in shipped content.
- Mining builds these files from YOUR work relationship. Do not paste
  third-party confidential material, other people's private messages beyond
  what your shared thread shows, or HR-class data.
