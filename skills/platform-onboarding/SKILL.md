---
name: platform-onboarding
description: Cold-start the harness on a platform it has never seen — read the platform's API reference, self-discover the endpoint surface, map auth, and deliver the first working integration with test cases in one sitting. Use when Josh says "onboard <platform>", "start building against <new system>", or when a build targets an API the harness has no playbook for.
---

# Platform onboarding (cold start)

The harness learned Workato's own API this way; the same pattern cold-starts
ANY new platform. The deliverable is a working, tested first integration —
not a research document.

## Phases

1. **Read the reference, don't guess it.** Find the platform's API reference
   (OpenAPI/Swagger, docs site, developer portal). Prefer machine-readable
   specs. If only HTML docs exist, harvest the endpoint list from the docs
   navigation/markdown the way `wt discover` did — sitemap depth rules and
   canonical-locale markers apply (docs live one level under the locale root;
   don't re-derive this).
2. **Self-discover the surface.** Build the endpoint index: method, path,
   scope, payload shape. Group by resource. Note what has no docs at all.
3. **Auth first, alone.** Get one authenticated read working before anything
   else. Know the grant type (API key, OAuth ISU, OAuth end-user), the token
   lifetime, the refresh story, and what identity the calls run as. If the
   platform has an end-user/VUA model, that decision gates everything after.
4. **Header discipline.** Newer API routes on hardened platforms may
   WAF-redirect default-library clients (the Workato lesson: python-urllib
   headers got 302'd to a sign-in page on newer routes while curl worked).
   Always send an explicit User-Agent + Accept header; when an endpoint
   mysteriously 302s, cross-test headers BOTH directions before concluding
   anything about scopes.
5. **First vertical slice.** Pick the thinnest end-to-end read+write pair the
   platform supports. Build it, test it, verify from the response/trace —
   never from the build tool's success message.
6. **Wire it in.** Register the platform with the harness: a playbook skill
   (its traps), the estate scope (watchdog connections), test cases for the
   integration (they join the regression canon), and the claims ledger for
   behavioral facts you verified.

## Anti-patterns

- No "it should work" from reading docs. Live call or it isn't knowledge.
- No production writes during onboarding. Ever.
- No invented business rules. If the spec doesn't state a limit or behavior,
  that's an open question, not an assumption to build on.
