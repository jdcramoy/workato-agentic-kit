# Queue definitions — the per-lane queries (canonical)

## Hard filter (Josh ruling 2026-10-09, BSYS-29438 rejection)

EVERY queue query below MUST carry the assignee filter:

```
assignee = 712020:112eb7d5-8a97-41a3-ae23-05513ca0ad72
```

The loop only pulls in work ASSIGNED TO JOSH. Tickets where he is merely
creator, watcher, mentioned, or reporter are NOT actionable work items — they
may be read for context but are never queued, planned, or replied to. This
replaces the earlier "created by Josh, or watched" scope. The explicit
account id is used instead of `currentUser()` so the filter is deterministic
regardless of which connection runs the query.

The matrix's three lanes have three different queue queries. A loop run
executes ALL THREE in order, then the everything-else rule catches stragglers.
Verified live 2026-10-07 (the original single-label query returned 0 and was
wrong — see gotchas).

## Lane 1 — BSYS Stories (plan lane)

```
project = BSYS AND issuetype = Story AND resolution = unresolved
  AND statusCategory != done
  AND assignee = 712020:112eb7d5-8a97-41a3-ae23-05513ca0ad72
ORDER BY updated DESC
```

The loop produces TECHNICAL PLANS posted for Josh's review; it never starts
builds. Scope decision for the fleet job: plan only `status = Backlog`
stories (In Progress/UAT stories belong to their assignees — several are
other people: Sam Cox, Jorge, Kevin Deng); the assignee filter above makes
other people's tickets unreachable by construction.

## Lane 2 — Bugs (remediation lane)

```
assignee = 712020:112eb7d5-8a97-41a3-ae23-05513ca0ad72
  AND issuetype = Bug AND resolution = unresolved
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
  AND assignee = 712020:112eb7d5-8a97-41a3-ae23-05513ca0ad72
ORDER BY updated DESC
```

Verified live 2026-10-07: 8+ open requests WITHOUT the ownership filter —
and nearly all were other people's in-flight work (terminations,
provisioning, software concerns owned by Anthony Wong / Ivan Yuri Uy /
Marc Parilla). Originally the loop touched unassigned OR Josh-assigned
requests; tightened 2026-10-09 (Josh ruling, BSYS-29438): the loop touches
ONLY Josh-assigned requests. Unassigned requests are humans' future intake,
not the loop's — they wait for a human assignee like anything else.
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
3. **Other people's tickets**: BSYS has many collaborators. The assignee
   filter makes other-assignee tickets unreachable by construction. Being
   creator, watcher, mentioned, or reporter is NOT enough — the ruling of
   2026-10-09 (BSYS-29438: an AE-change ticket Josh was only watching got
   queued and planned) makes assignee = Josh a hard gate on every query.
4. A single lane query is NOT "the queue". Run all three lanes every pass;
   a pass that only checks the label lane is a pass that missed the
   backlog.
