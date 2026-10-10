# Tier and SDLC Quick Reference

One card. Print it, pin it, done. Full detail lives in the governance policy; this is the version you check mid-build.

## The four tiers

Your tier comes from the data your app touches and who uses it.

| Tier | Data | Example | What is required |
|------|------|---------|------------------|
| 1 | No sensitive data, personal use | Personal productivity tool, local calculator | Self-classify, no review |
| 2 | Internal data, team-level sharing | Team dashboard with internal metrics | Register with BT, peer review |
| 3 | Confidential data or broad sharing | App pulling Salesforce data, shared department-wide | Security review, BT approval |
| 4 | Restricted data or external-facing | App processing PII, financial data, or published outside Workato | Full security, legal, and leadership approval |

## The rule that catches people

Sharing promotes your tier. A Tier 1 app shared company-wide becomes at least Tier 2. A Tier 2 app that starts pulling confidential data becomes Tier 3. Classify for what the app is now, not what it was when you built it.

| Sharing scope | Effect |
|---------------|--------|
| Just you | No promotion |
| Your team | May promote to Tier 2 |
| Your department | Promotes to Tier 2 or 3 |
| Company-wide | Promotes to Tier 3 or higher |
| External (customers, partners, public) | Promotes to Tier 4 |

## The 8-stage lifecycle

Rigor scales with tier. Tier 1 is mostly self-service; Tier 4 gets a full escort.

| Stage | Tier 1 | Tier 2 | Tier 3 | Tier 4 |
|-------|--------|--------|--------|--------|
| Ideation | Self-service | Self-service | Self-service | Self-service |
| Risk classification | Self-classify | Self-classify, BT validates | BT classifies | BT and Security classify |
| Design | No review | Peer review | BT review | BT and Security review |
| Build | Any approved platform | Approved platform | Approved platform | Approved platform |
| Test | Developer testing | Developer and peer testing | BT-defined test plan | Security testing plus BT test plan |
| Security review | Not required | Not required | Required | Full security assessment |
| Deploy | Self-deploy | BT registers | BT approves | BT, Security, and Leadership approve |
| Operate | Self-maintained | Registered, you maintain | Monitored, BT oversight | Monitored, SLA, incident response |

## Two things that are always true, at every tier

- Approved platforms only. Personal cloud accounts and unlisted providers are off-limits no matter how small the app.
- Tier 2 and above register before sharing. Registration is lightweight: name, description, owner, tier, data sources, platform, sharing scope, URL.

Not sure of your tier? Two questions settle it: what data does it touch, and who sees it. The [platform decision tree](#) walks you through it.
