# Platform Decision Tree

Two questions decide everything: what data does your app touch, and who do you share it with. Answer both and the tree lands you on a tier with the requirements and the platform to match. You should never need to read the policy for a classification.

## How to use it

Start at the top. The first question sets your starting tier from the data. The second question asks about sharing, because sharing can promote you. Your final tier is the higher of the two numbers. The colored boxes at the bottom are what that tier asks of you.

```mermaid
flowchart TB
  s([You want to build or share a vibe-coded app]) --> d{What data does it touch?}

  d -->|No sensitive data, personal use| b1[Data tier: 1]
  d -->|Internal company data| b2[Data tier: 2]
  d -->|Confidential data| b3[Data tier: 3]
  d -->|Restricted data like PII or financials| b4[Data tier: 4]

  b1 --> sh{Who do you share it with?}
  b2 --> sh
  b3 --> sh
  b4 --> sh

  sh -->|Just me| p0[No promotion]
  sh -->|My team| p1[May promote one tier]
  sh -->|My department| p2[Promotes to tier 2 or 3]
  sh -->|Company-wide| p3[Promotes to tier 3 or higher]
  sh -->|Anyone outside Workato| p4[Promotes to tier 4]

  p0 --> fin{Your tier is the higher of the two numbers}
  p1 --> fin
  p2 --> fin
  p3 --> fin
  p4 --> fin

  fin -->|Tier 1| t1[Tier 1: personal tool]
  fin -->|Tier 2| t2[Tier 2: team app]
  fin -->|Tier 3| t3[Tier 3: department app]
  fin -->|Tier 4| t4[Tier 4: restricted or external]

  t1 --> r1["Self-classify, no review.<br/>Build local on your laptop, or on an<br/>approved agent platform (Otto, Workato)."]
  t2 --> r2["Register with BT, peer review.<br/>Build on an approved team-level platform;<br/>final list lands with platform configuration."]
  t3 --> r3["BT classifies, security review, BT approval.<br/>Build on the approved managed platform;<br/>final list lands with platform configuration."]
  t4 --> r4["Full security, legal, and leadership approval.<br/>Managed infrastructure only;<br/>placement confirmed with platform configuration."]

  classDef tier1 fill:#e6f4ea,stroke:#1e7b34,color:#111
  classDef tier2 fill:#e8f0fe,stroke:#1a56b0,color:#111
  classDef tier3 fill:#fef3d8,stroke:#a06a00,color:#111
  classDef tier4 fill:#fde8e8,stroke:#b3261e,color:#111
  class t1,r1 tier1
  class t2,r2 tier2
  class t3,r3 tier3
  class t4,r4 tier4
```

## Worked examples

A few scenarios, walked end to end.

**You built a personal expense tracker.** It touches no sensitive data and only you use it. Tier 1, no review, build it locally and move on with your day.

**Your team dashboard with internal metrics.** Internal data, shared with your team. Tier 2. Register with BT, grab a peer review, build on an approved team-level platform.

**That same dashboard, now pulling Salesforce numbers.** Confidential data. The app just became Tier 3 regardless of who it is shared with. BT classifies it, Security reviews it, BT approves the deployment.

**A customer-facing tool of any kind.** Anything outside Workato sees Tier 4. That means security, legal, and leadership before it ships. Do not start this one without talking to us first.

## Platform names, and why some boxes are vague

The governance policy lists the approved platforms: your local machine, Otto, the Workato platform (Genies, MCP servers, Skills), Lovable, and Workato AWS (Amplify, EC2, S3, SQS, Lambda). Everything else, including personal cloud accounts, is off-limits.

The tree deliberately says "approved platform" rather than naming one per tier in most boxes, because platform configuration is being finalized right now. Which platform serves which tier gets locked when that lands, and the onboarding guides follow. If you need a platform today, the Tier 1 answer (local, Otto, Workato) is safe, and everything else starts with a conversation with BT.

If the classification process or the platform list changes, this tree changes in the same session. Check the date on the [governance policy](https://workato.atlassian.net/wiki/spaces/extbt/pages/2553184311/Vibe-Coded+App+Governance+Policy) if you want to confirm you are looking at the current rules.
