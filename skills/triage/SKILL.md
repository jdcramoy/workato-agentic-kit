---
name: triage
description: Interactive approval queue for development, bugfix, and build triage findings discovered by the fleet (watchdog autopsies, regression failures, gardener actionable items, estate-architect recommendations, cortex work-shaped attention items, jira-autotriage findings including inbound Jira attention items: tickets assigned to Josh, new comments, aging tickets). Cards ranked by urgency then age. Use when Josh says "triage findings", "show the triage queue", "what needs fixing", "what needs my attention", "work the findings", or invokes /triage. Renders every open finding as a decision card, collects verdicts in one batched pass, records them via triage-decide.py, creates the BSYS Story or Bug for approved work, and dispatches approved dev work.
---

# Triage — the silver platter for discovered work

One interactive pass over every open finding the fleet filed. The
mechanical recorder already exists (`knowledge/scripts/triage-decide.py`);
this skill is the face on it. Distinct from `/proposals`: THAT queue holds
dreamer IDEAS (what the harness or a project should become); THIS queue
holds evidence-backed DISCOVERIES (what is broken, rotting, or costing
time, ready to become work).

## Procedure

1. **Load the queue:**

   ```bash
   python3 ~/.claude/knowledge/scripts/triage-decide.py list
   ```

   If nothing is open: say so in one line, done. No ceremony. Sources:
   the watcher SOPs file findings as they run, and the jira-autotriage
   loop files every Jira attention item each pass (plans awaiting your
   authorization, hotfix-class bugs, ambiguous tickets, and inbound
   signals: new tickets assigned to you, new comments, tickets aging
   without movement).

2. **Build one decision card per open finding.** Compact, scannable —
   but never at the cost of the ticket link or the full finding text
   (Josh, 2026-10-10: every card MUST carry the Jira URL and the
   verbatim description; "you had to be there" cards are a defect):

   - slug, `kind` (bugfix | playbook | test | hygiene | build), source
     agent, age in days, points estimate
   - **direct Jira link(s)**: every ticket the finding touches, as the
     full clickable URL `https://workato.atlassian.net/browse/<KEY>`.
     Take keys from the finding's `jira` field AND scan slug/title/
     evidence for BSYS/BTSUP/other keys — a card may reference more
     than one. `triage-decide.py list` already prints these under
     `Jira:`; copy them through, never drop them.
   - the finding's own title, proposed work line, and evidence field
     VERBATIM and UNTRUNCATED (not your paraphrase, not "see evidence")
   - for anything touching a live Workato asset: run the blast-radius
     skill and put the radius on the card
   - for anything touching a live Workato asset: run the blast-radius
     skill and put the radius on the card
   - urgency: from the finding's `urgency` field if set, upgraded by
     blast radius (a P1 blast radius on a low-urgency finding renders it
     high), downgraded for findings that are pure noise repeats
   - your recommended verdict, marked as a recommendation

   RANK by urgency first (high → low), then age (oldest first) within
   each band. Time-sensitive work never hides behind old hygiene.

3. **Collect verdicts in ONE batched pass.** Use AskUserQuestion, up to 4
   findings per call (loop batches until done). Options per finding:

   - **File story/bug** — create the Jira work item now (see step 4),
     record `filed --jira KEY`
   - **Build now (dev)** — dev-estate fixes only, executed in this
     session (see step 5), then record `build`
   - **Queue only** — record `accept` (queued for a promotion batch or a
     later session, no ticket yet)
   - **Reject** — recorded rejected; the note is the taste signal
   - **Defer** — untouched, re-offered next time

   Josh's "Other" free-text becomes the logged note. Never call
   AskUserQuestion twice for the same finding.

4. **File story/bug (the Jira procedure).** Issue type: **Bug** when the
   finding is a defect (something that worked or should work is broken);
   **Story** for builds, playbook entries, hygiene, and everything else.
   Project **BSYS** (cloudId `99bd32a1-58a6-41d6-8e61-c98194c68259`).
   Rules, in order:

   a. **Parent epic**: use an existing epic ONLY with certainty (its
      summary and scope clearly cover the finding). Search
      `project = BSYS AND issuetype = Epic AND summary ~ "<domain terms>"`
      first. No certain match → create the Epic: house format
      (Background / Objective / Scope / Out of Scope / Success Measures /
      Acceptance Criteria), points 13, labels `V2MOM-FY27` style.
   b. **The FY27 anchor**: new epics file under parent `BSYS-21305`
      ("VMT FY2027 M3: Become IPO-ready by leveraging Enterprise AI to
      prove efficiency at scale") — the V2MOM FY27 work item the BT epic
      tree hangs from. Re-verify the key live the first time each session
      uses it; never quote it from memory.
   c. **The story/bug**: parent = the epic key, assignee = Josh (account
      id `712020:112eb7d5-8a97-41a3-ae23-05513ca0ad72`), points at
      creation via `additional_fields {"customfield_10057": N}` (BSYS
      supports the field; scale: 1 trivial, 2 half day, 3 one day, 5 the
      common build), description per jira-story-standards (Background,
      Business Requirements, Technical Requirements, Acceptance
      Criteria `- [ ]`, UAT Evidence section naming what WILL be
      recorded), labels reusing the epic's set, and the finding's
      evidence refs inline (real asset URLs, job IDs, file paths).
      Descriptions are Josh's prose: draft through `josh-writing-voice`
      (first person, no fleet/process framing; Josh 2026-10-10).
   d. Batch story creation; don't ask per-story. After creation, record
      `triage-decide.py <slug> filed "story created" --jira KEY` and
      include the key + URL in the summary table.

5. **Dispatch Build-now, scoped hard:**

   - **Dev-estate only**: Workato dev recipes/functions/MCP-dev assets,
     knowledge and skill fixes, script fixes. Mandatory cycle:
     snapshot → edit → test → verify with a live trace → build-ledger
     entry. Then record `triage-decide.py <slug> build "<evidence ref>"`.
   - **UAT/prod NEVER via build-now**: production sign-off gates stand
     untouched; file the story instead and let the promotion pipeline
     carry it.
   - **Bigger than a first move**: file the story (step 4) and record
     `accept "story filed, sized for a session"`.

6. **Close with a summary table:** slug | verdict | jira key or evidence |
   what happens next (filed / built + ref / queued / deferred / rejected).
   If 3+ rejections share a reason, append that taste pattern as one line
   to the bus thread `triage-taste` (YOUR outbox, `kind:"finding"`) — that
   is how the watchers learn what not to re-raise.

## Hard rules

- Never decide for Josh. The queue renders facts and a recommendation;
  the verdict is his.
- Never hand-edit the queue file — the recorder is the only writer of
  status changes; findings are appended by their source agent.
- Final states are terminal: rejected and built findings do not get
  re-decided; new evidence means a NEW finding with a new slug.
- Rejected stays rejected: re-raising needs materially new evidence.
- Batch, don't drip: one AskUserQuestion round per ≤4 findings, then move.
- Nothing in this skill bypasses a prod-write gate, a UAT sign-off, or
  the promotion pipeline; those boundaries are constitutional.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [The Workato KB: RAG++ over all documentation, and the dreaming team](../../kb-corpus/confluence/extbt/2938929237-the-workato-kb-rag-over-all-documentation-and-the-dreaming-team.md)
- [2025/04 April Lookback](../../kb-corpus/confluence/intbt/1082851751-202504-april-lookback.md)
- [BT Ops Workflow Guide](../../kb-corpus/confluence/intbt/2060451866-bt-ops-workflow-guide.md)
- [2025/08 August Lookback](../../kb-corpus/confluence/intbt/1419411547-202508-august-lookback.md)
<!-- kb-bridges:end -->
