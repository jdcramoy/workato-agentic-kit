---
name: claim-verification
description: Systematic verification procedures for claims in the ledger, per claim type — platform-behavior claims get live probes, process claims get trace checks, tooling claims get reproductions. Use when the gardener or cortex flags a stale or low-confidence claim, when Josh asks "is that still true", or before citing a claim older than a week in a decision.
---

# Claim verification

Claims are load-bearing; a wrong one is worse than none. Verify by type,
with live evidence, and write the result back as a verification event.

## Procedures by claim type

1. **Platform behavior** ("push on running fails", "CLI start silently
   no-ops", "WAF redirects urllib"): reproduce it. Minimal live probe in dev
   (the claim usually names the recipe/mechanism). The probe itself is the
   evidence line.
2. **Tooling/API** ("endpoint X rejects Y", "scope Z is granted"): make the
   call fresh. `wt api GET ...` or the MCP tool; record the live response
   class.
3. **Process/convention** ("deployments are Stories", "dev Tests cleared"):
   confirm against the governing doc or Josh's latest ruling in memory —
   conventions expire by new rulings, not by probes.
4. **Estate state** ("recipe X is broken", "conn Y is dead"): tracker or
   AIRO read-back of the current state.

## Write-back

Append to `knowledge/claims/verifications.jsonl` (the gardener rolls these
into `last_verified`):

```json
{"ts","subject","observation":"confirmed|refuted|partial","evidence":[...]}
```

A refuted claim is a gift: it means a decision was about to be made on a
stale fact. Lead the report with refutations.

## Rules

- Verification = live evidence. Reading the claim's original evidence again
  is not verification.
- If the claim can't be probed safely in dev, mark it "needs Josh" with the
  exact probe that would settle it.
- Never silently mark verified. The observation + evidence fields are
  mandatory.
