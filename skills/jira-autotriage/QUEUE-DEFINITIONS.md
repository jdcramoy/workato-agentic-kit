# Queue definitions — the per-lane queries (canonical)

The matrix's three lanes have three different queue queries. A loop run
executes ALL THREE in order, then the everything-else rule catches stragglers.
Verified live 2026-10-07 (the original single-label query returned 0 and was
wrong — see gotchas).

## Lane 1 — BSYS Stories (plan lane)

```
project = BSYS AND issuetype = Story AND resolution = unresolved
  AND statusCategory != done
ORDER BY updated DESC
```

Live count 2026-10-07: 15+ (HR Genie Intelligence suite, Semantic MCP p0,
Deployment Item Checklist…). The loop produces TECHNICAL PLANS posted for
Josh's review; it never starts builds. Scope decision for the fleet job:
plan only `status = Backlog` stories (In Progress/UAT stories belong to
their assignees — several are other people: Sam Cox, Jorge, Kevin Deng);
always check `assignee` and skip other people's tickets.

## Lane 2 — Bugs (remediation lane)

```
assignee = currentUser() AND issuetype = Bug AND resolution = unresolved
  AND statusCategory != done
ORDER BY updated DESC
```

Live count 2026-10-07: 1 (BSYS-28296, Marketo MCP get_lead_activities,
In Progress). Remediation gate: dev-workspace fixes only; `agent-triage`
label = the explicit "agent may work this" signal (see Intake below);
hotfix-marked = report-and-propose only.

## Lane 3 — BTSUP requests (service-desk lane)

```
project = BTSUP AND type != Bug AND resolution = unresolved
  AND statusCategory != done
  AND (assignee IS EMPTY OR assignee = currentUser())
ORDER BY updated DESC
```

Verified live 2026-10-07: 8+ open requests WITHOUT the ownership filter —
and nearly all were other people's in-flight work (terminations,
provisioning, software concerns owned by Anthony Wong / Ivan Yuri Uy /
Marc Parilla). The ownership filter is therefore MANDATORY: the loop only
touches unassigned or Josh-assigned requests; anything with another
assignee is humans already mid-flight, read-only.
Replies go to real customers in Josh's voice — confirm-gated, always.
Unconfirmed (headless pass) = draft waits in the ledger + morning brief,
never auto-posted.

## Gotchas (each one bit once)

1. **Closed-but-unresolved**: Jira allows status = Closed with resolution
   EMPTY; `resolution = unresolved` matches it. ALWAYS AND with
   `statusCategory != done` (BSYS-28081 was the live example).
2. **The label gate is intake-dependent**: `agent-triage` arrives only if a
   human or an intake recipe applies it. No label = Lane 2 works the ticket
   only if assigned to Josh AND Josh has authorized label-free remediation;
   default is triage-and-propose.
3. **Other people's tickets**: BSYS has many collaborators. An assignee that
   is not currentUser() puts the ticket in the everything-else row
   (read-only), even in BSYS.
4. A single lane query is NOT "the queue". Run all three lanes every pass;
   a pass that only checks the label lane is a pass that missed the
   backlog.
