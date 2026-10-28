# Tech Review Lessons Learned — Final Tech Review feedback, mined from Patricia Guevarra

**Compiled 2026-10-21. Source: every comment Patricia Guevarra (BT Enterprise
Architecture, Final Tech Reviewer) left on Josh-reported Workato deployment
request tickets, 2026-04-02 through 2026-10-21 — 17 tickets, 31 comments.
Every lesson below cites the ticket where she raised it. The enforcement
checklist version lives in `workato-development-playbook/SKILL.md`
("Tech review lessons" section); this file is the evidence-backed reference.**

Tickets reviewed: BSYS-24699, BSYS-27576, BSYS-27921, BSYS-28019, BSYS-28103,
BSYS-28195, BSYS-28225, BSYS-28231, BSYS-28478, BSYS-28483, BSYS-28536,
BSYS-28579, BSYS-28600, BSYS-29281, BSYS-29283, BSYS-29498, BSYS-29592.
(BSYS-28784 also had a Patricia comment but is Pooja V's ticket, not ours.)

---

## Lesson 1: Never hardcode environment-specific values — she flags this on nearly every review

The single most repeated finding, and the one that breaks production on
landing. Her pattern: "Is this a dev recipe ID? ... so that this can be easily
changed between a dev recipe ID and a prod recipe ID without editing the
recipe in production."

Manifestations caught across tickets:

- **Hardcoded recipe IDs.** `OPS | Emit Event360 Signal` wrote a dev recipe ID
  into a data-table record ([BSYS-28478](https://workato.atlassian.net/browse/BSYS-28478)).
  The Gmail MCP Telemetry Collector hardcoded its whole list of monitored
  recipe IDs ([BSYS-28483](https://workato.atlassian.net/browse/BSYS-28483)).
  This is exactly Josh's recurring failure: monitoring recipes ship with dev
  IDs, break in prod, and need manual re-editing.
- **Hardcoded folder ID** in the HR Genie Oct batch ([BSYS-29498](https://workato.atlassian.net/browse/BSYS-29498)) — "should this be remapped?"
- **Hardcoded personal email / Slack user ID** in notification recipes
  ([BSYS-29283](https://workato.atlassian.net/browse/BSYS-29283),
  [BSYS-29592](https://workato.atlassian.net/browse/BSYS-29592)) — "you may want to use a project property ... so you don't have to redeploy for a change in the email address."
- **Monitoring recipes referencing other recipes by ID** — the connection-health
  recipe's List connections step ([BSYS-28600](https://workato.atlassian.net/browse/BSYS-28600)).
- **Invalid/unresolved datapills** discovered in submitted recipes
  ([BSYS-29592](https://workato.atlassian.net/browse/BSYS-29592)) — "there are invalid pills in some recipes, do these need to be remapped?"

**The rule:** every cross-asset reference (recipe ID, folder ID, table ID,
user identity, email) is either a project property, a dynamic lookup
(list recipes by folder), or a trigger/job context datapill. Zero literals.
Before submitting, sweep the recipe config for numeric IDs and email
addresses; each one needs a portable justification or a property.

## Lesson 2: Connection names must be IDENTICAL in dev and prod

- "Having these differently named connections between dev and prod means that
  every deployment requires an update in the recipes to change the connection."
  ([BSYS-29281](https://workato.atlassian.net/browse/BSYS-29281))
- "It looks like the connections are named differently between Dev and Prod.
  We should update either the Dev connection name or the Prod connection name."
  ([BSYS-29283](https://workato.atlassian.net/browse/BSYS-29283))
- She took direct action on [BSYS-24699](https://workato.atlassian.net/browse/BSYS-24699):
  renamed `CON | Workday Rest Dev` to `CON | Workday REST` and
  `CON | Slack Dev` to `CON | Slack (HR Genie)` — strip "Dev" from the name
  the moment a connection will ever travel.

**The rule:** name connections environment-neutral from creation. Never put
"Dev"/"Prod" in a connection name. Identical names in both environments means
an import re-binds by name and no recipe edit is needed.

## Lesson 3: Prod-facing names must not read as dev, demo, or version artifacts

- "any reason why one of the recipes has 'v2' in it lol" +
  "Should this be named 'Dev' even when this is deployed in prod?"
  ([BSYS-29498](https://workato.atlassian.net/browse/BSYS-29498))
- "For the Vegas recipes, maybe we should rename it? Otherwise it may look
  like just demo recipes in prod, someone may mistakenly turn it off"
  ([BSYS-29283](https://workato.atlassian.net/browse/BSYS-29283))
- "Is the intention for this to exist alongside the existing Google Slides by
  Workato MCP, or are we intending to migrate to this 'Enhanced' version?"
  ([BSYS-28579](https://workato.atlassian.net/browse/BSYS-28579)) — if a new
  asset coexists with an old one, say so in the DR ticket; if it replaces one,
  name the retirement plan.

**The rule:** the prod name is final at build time. No "v2", "Dev", "new",
"demo", or proof-of-concept slugs in asset names that will be promoted.
Scrub names before the DR is filed, not after.

## Lesson 4: Connector action names — short, details in description/hint

Raised on at least three deployments: "The connector actions' names seems a
bit long, we may want to shorten the action name and add the details to the
description or hint" ([BSYS-29281](https://workato.atlassian.net/browse/BSYS-29281));
"It's a bit long lol we may want to update the connector to something shorter
and save the rest of the details for the action hint/description"
([BSYS-28536](https://workato.atlassian.net/browse/BSYS-28536)); and again
"the connector action titles are very long again"
([BSYS-29592](https://workato.atlassian.net/browse/BSYS-29592)) — the "again"
means the first fix did not stick. For subsequent deployments she also asked
for the Custom Action name to be visible so reviewers can see what the action
does ([BSYS-27921](https://workato.atlassian.net/browse/BSYS-27921)).

**The rule:** action titles are short verbs (`Get messages`, not
`Get messages with filters reactions pagination and limits for channel X`).
Detail goes in the action hint/description. Same for custom actions in
manifests: the name should self-describe.

## Lesson 5: Loops are flagged every time — prefer batch actions and collections

Her most consistent structural preference, on 8 of 17 tickets:

- **Batch over repeat/loop.** "You should be able to use a batch action
  instead of a repeat action" ([BSYS-29592](https://workato.atlassian.net/browse/BSYS-29592));
  "You should also be able to use a batch update step instead of looping"
  ([BSYS-29498](https://workato.atlassian.net/browse/BSYS-29498));
  "it's looping and then creating data table records, you should be able to
  create records by batch instead"
  ([BSYS-28478](https://workato.atlassian.net/browse/BSYS-28478)).
- **Collections + SQL filter over retrieve-all-then-filter-in-loop.**
  ([BSYS-28478](https://workato.atlassian.net/browse/BSYS-28478),
  [BSYS-28600](https://workato.atlassian.net/browse/BSYS-28600) FUNC | Resolve
  Business Process Assignee, [BSYS-27921](https://workato.atlassian.net/browse/BSYS-27921),
  [BSYS-28103](https://workato.atlassian.net/browse/BSYS-28103)). She notes
  retrieve-all has a real ceiling: "Do we expect there to be only 1000 records
  max in these tables?"
- **Array slicing beats loop-with-index.** "I'm pretty sure you can do
  something like [0..-99] to get the first 100"
  ([BSYS-28103](https://workato.atlassian.net/browse/BSYS-28103)).
- **Dynamic pagination.** "use Repeat While so that it's not paginating a
  static number of times and is more dynamic"
  ([BSYS-28195](https://workato.atlassian.net/browse/BSYS-28195)).
- **Long logic out of repeat loops.** "given the way Workato handles repeat
  actions in job reports, this may eventually be difficult to troubleshoot,
  you may want to consider moving lengthy, complex logic to a recipe function
  (even if that logic is not used elsewhere)"
  ([BSYS-28600](https://workato.atlassian.net/browse/BSYS-28600)).
- **Deduplicate parallel branches.** Two conditional nodes repeating the same
  step sequence means "any update to one node will require an update in the
  other node" — restructure so shared work runs once
  ([BSYS-28600](https://workato.atlassian.net/browse/BSYS-28600)).

**The rule:** default to batch actions for list writes, collections + SQL for
filtering, array slicing for windows, Repeat While for pagination, and recipe
functions for complexity. A per-item loop is a deliberate choice that needs a
reason, not a default.

## Lesson 6: Manifest hygiene — missing dependencies block; archive cruft gets questioned

- **A called function missing from the manifest is a blocker.** "looks like
  there's a recipe function called in the recipe that is not included in the
  manifest" ([BSYS-28579](https://workato.atlassian.net/browse/BSYS-28579)).
  This is the failure class the manifest algorithm (2026-10-15 amendment,
  dependency rule 4) exists to prevent.
- **Archive folders do not belong in a DR manifest.** "I'm sure that these can
  be done..." plus "there are skills in a folder called 'zArchive' are those
  still needed?" ([BSYS-28103](https://workato.atlassian.net/browse/BSYS-28103));
  "I don't recall the archive folder being included in the manifest before but
  now it looks like there is a recipe in the Archive folder, is this still
  needed in the manifest?"
  ([BSYS-28478](https://workato.atlassian.net/browse/BSYS-28478)).
- **Assets already in prod are removed.** "I removed the Confluence assets
  since it should already be in prod"
  ([BSYS-24699](https://workato.atlassian.net/browse/BSYS-24699)). She also
  removed an unused custom action and `Get HR Space` on her own judgment.
- **Doubtful assets get named.** "do we need the assets under 'Vegas Demo
  Cadence'?" ([BSYS-29283](https://workato.atlassian.net/browse/BSYS-29283)) —
  every row a reviewer has to ask about costs a round-trip.

**The rule:** manifest = changed assets + their dependencies, nothing else.
Before filing, answer her three questions in the ticket: what was added and
why, what was excluded and why, and what already exists in prod.

## Lesson 7: Formula mode is not a text editor

"You noticed a lot of steps where you use formula mode to concatenate strings
and datapills — you don't actually need to, you can put them in as normal
text. No real harm, but it saves you the trouble of all the '+' and quotes."
([BSYS-29283](https://workato.atlassian.net/browse/BSYS-29283))

**The rule:** mixed text + datapill fields go in text mode with pills inline.
Formula mode is for functions and logic only. It also removes a class of
quoting/escaping bugs.

## Lesson 8: Genie deployments carry governance questions

- "Who should have access to this Genie, do we need to set up an end user
  group for this?" ([BSYS-29498](https://workato.atlassian.net/browse/BSYS-29498))
  — have the access-control answer IN the DR ticket before filing.
- She added the universal security prompt to the Genie per the org checklist
  ([BSYS-24699](https://workato.atlassian.net/browse/BSYS-24699)) and required
  re-testing after. Genie DRs should include the security-prompt check as
  done, not wait for the reviewer to apply it.

## Lesson 9: Step comments vs version hints

"the step comments are getting so long lol do you feel like they're helpful?
... should these maybe be called out in the version hints rather than the
step comment itself?" ([BSYS-28600](https://workato.atlassian.net/browse/BSYS-28600))

**The rule:** step comments state the step's invariant purpose; per-instance
debugging callouts and incident-specific notes live in version hints.

## Scoreboard

The two findings that have appeared on 5+ separate deployments and should be
considered chronic: **hardcoded environment-specific values** (Lessons 1) and
**loop-heavy logic** (Lesson 5). Connection naming (Lesson 2) recurred on 3.
If a submission fixes nothing else, it must fix these three.

## What "reviewed manifest" means

Several tickets carry only "reviewed manifest" / "reviewed recipe diff" with
no findings ([BSYS-27576](https://workato.atlassian.net/browse/BSYS-27576),
[BSYS-28019](https://workato.atlassian.net/browse/BSYS-28019),
[BSYS-28225](https://workato.atlassian.net/browse/BSYS-28225),
[BSYS-28231](https://workato.atlassian.net/browse/BSYS-28231)) — these are the
clean passes. The pattern in clean passes: focused single-purpose deployments
(3 skills, one pagination change, attachment handling) with no new hardcoded
values and no loops introduced. Small, portable diffs review fast.
