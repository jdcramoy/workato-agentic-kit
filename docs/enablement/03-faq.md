# Builder Enablement FAQ

The questions builders actually ask, answered from the governance policy and the processes rolling out around it. If your question is not here, ask BT Enterprise Architecture and it will end up on this page.

## Does this apply to me?

If you have built anything with AI-assisted development, yes. The policy covers vibe-coded apps across the company, from a spreadsheet replacement you scripted in an afternoon to a Tier 3 service. It applies to how apps get classified, where they are hosted, and what review happens before sharing.

## How do I know my app's tier?

Two questions. What data does it touch, and who sees it. The data sets your starting tier and sharing can promote it; your tier is the higher of the two numbers. The [decision tree](#) does this in under a minute.

## My app was Tier 1 and now my team wants it. What changes?

Sharing promotes the tier. A personal tool shared with your team moves to Tier 2 at least: register it with BT and get a peer review before you share the link. This is the single most common trip point, so the quick reference card leads with it.

## Where am I allowed to build?

Approved platforms only: your local machine, Otto, the Workato platform (Genies, MCP servers, Skills), Lovable, and Workato AWS. Which platform fits which tier is being finalized as platform configuration completes; the decision tree shows what is settled and what is pending.

## Can I use my own AWS account? It is faster.

No. Personal cloud accounts and unlisted providers are off-limits at every tier, even for a tiny app. The approved platforms exist so that security review, monitoring, and support are possible when something goes wrong. Fast but ungoverned is not faster; it is an incident waiting for a calendar slot.

## Do I need to register my app?

Tier 2 and above register before sharing. Registration is lightweight: app name, description, owner, risk tier, data sources, platform, sharing scope, URL. The registry itself is being built right now; until the form is live, send those details to BT and we will track them.

## Who reviews Tier 3 and Tier 4 apps?

Tier 3: BT classifies the app, Security reviews it, BT approves the deployment. Tier 4 adds legal review and leadership approval, because by definition you are touching restricted data or exposing something outside Workato. Start those conversations early; a Tier 4 timeline is measured in weeks, not hours.

## What happens if I skip all this and someone finds out?

Tier violations get handled the same way any security process handles them: the app gets classified properly, and the conversation is about remediation, not blame. The bad outcome is not "I got in trouble for a dashboard". The bad outcome is an app with customer data on an unmonitored host that nobody knows exists when it breaks. Come forward first; it is a five-minute registration versus a full autopsy.

## Can I put my app on the public internet?

Only through the external-facing gate, and anything external is Tier 4 by definition. That means security, legal, and leadership approval before launch. If you think you need this, talk to BT before you build, not after.

## I already built something before this policy existed. Am I in trouble?

No. Classify it with the decision tree, and if it lands at Tier 2 or above, register it. That is the whole dance. The policy is forward-looking; nobody is auditing last year's prototypes, but an unregistered Tier 2 sitting in production is exactly what the registry exists to catch.

## What is happening with Replit, Vercel, and other third-party builders?

Under evaluation. The shortlist is Replit, Lovable, and Vercel, and the decision hangs on SSO integration, data residency, cost, and security posture. Lovable is listed as an approved platform today; the others join or do not based on how that evaluation lands. Watch this page.

## Where do the full rules live?

The [Vibe-Coded App Governance Policy](https://workato.atlassian.net/wiki/spaces/extbt/pages/2553184311/Vibe-Coded+App+Governance+Policy) is the source of truth. These pages are the shortened, builder-facing version; when the two disagree, the policy wins and you should tell us so we can fix the mismatch.
