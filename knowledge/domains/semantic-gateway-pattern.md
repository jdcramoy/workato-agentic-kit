# Semantic gateway pattern — house standard for API-surface MCPs

What the pattern is, why the house keeps choosing it, and where the
authoritative contract lives. Read this before starting ANY new gateway
surface build (a platform API that deserves a small set of MCP tools
instead of hundreds).

Status: doc written 2026-11-01 (librarian pass). The pattern itself is
older: first instantiated 2026-10 for Google Workspace, matured through
2026-10-22 (devapi) and 2026-10-31 (Atlassian).

## What is the semantic gateway pattern?

Instead of exposing an API's hundreds of raw endpoints as MCP tools,
build exactly 3 tools: a heavy lifter, a routing index, and a policy
lookup. Every capability the API offers becomes a REGISTRY ROW the
index routes to, not a new tool. Tool count never grows with capability
count. A learning loop (probe, mine, jury, benchmark) keeps registry
rows truthful. Rule of thumb from the contract: the pattern is the
interface; each surface owns its own data.

## Where is the authoritative contract?

`~/orca/projects/dev-api-mcp/PATTERN.md` (v1, cross-surface, updated
2026-10-30) plus `VOCABULARY.md` in the same repo (envelope decision
classes, error codes, intel field names). The next surface adopts that
spec, not a copy of another gateway's code. THIS doc is the routing hub;
the repo file is the spec of record. If this doc and PATTERN.md ever
disagree, PATTERN.md wins and this doc gets fixed.

**Terraformer:** the full build blueprint for standing up a new surface —
asset topology, apply order, platform laws, done-criteria — lives at
`~/orca/projects/dev-api-mcp/TERRAFORMER-HANDOFF.md` (written 2026-11-02,
after the third instance proved the pattern replicates).

## Which surfaces exist as of 2026-11-01?

| Surface | Story | State (dated) | Project doc |
|---|---|---|---|
| Google Workspace Semantic MCP (gw_semantic) | BSYS-29262 + 29957/30072/30079/30085 | live in dev; compound auto-authoring live 2026-10-29 (BSYS-30074); full-spine promotion manifest assembled 2026-10-26, pending Josh push | projects/google-semantic-mcp.md |
| Developer API Semantic MCP (devapi) | BSYS-29894 | dev-only; Phase 6 benchmark campaign live; 3-tool surface, 332-endpoint registry | projects/dev-api-mcp.md |
| Atlassian Semantic MCP | BSYS-30123 | dev-only; resolver 83514453 v26 UAT 16/16 as of 2026-11-01; connector 1371993 v9 OAuth 3LO; 9-recipe flywheel fleet | projects/atlassian-semantic-mcp.md |
| otto port | otto repo | port target for gw_semantic; 7 flywheel loops live | projects/otto.md |

## What must every surface implement? (the 8 invariants, condensed)

1. Tool economy: exactly 3 MCP tools; new capability = new registry row.
2. Routing index: content-free catalog, per-family checksums derived
   from executable rows only, deterministic ordering.
3. Fail-closed envelopes: rejections never guess; every rejection
   carries a machine-readable code plus everything needed to retry
   without reasoning.
4. Recovery machinery: valid_values, expected_formats, retry_with,
   retry_checksum, next_call, produced_by.
5. Mutation safety: irreversible or outward-facing mutations run
   plan then confirm, PERMANENTLY (no surface ships no-dry-run on
   outward mutations).
6. Packed intel: per-capability intelligence rides in the registry
   row's JSON envelope column, read as data by the hot path.
7. Attribution: caller identity and enforcement identity logged
   separately; audit table is ground truth.
8. Identity floor: per-caller scoped execution, principals verified
   live and re-checked on a schedule.

The full table (with the T1-T5 loop tiers and clocks) is PATTERN.md
section 1 and 3. The parity matrix there is two-directional: surfaces
adopt from each other on a named schedule, and vocabulary drift is
treated as a bug.

## Why does the house standardize on it? (the case, in brief)

- **MCP tool-count tax.** Every served tool costs schema tokens on
  every session that attaches the server. The fleet measured the
  catalog cost of 39 tools at roughly 9,989 tokens (2026-10,
  workato-platform.md benchmark discipline section). A 500-endpoint
  API served raw is unusable; 3 tools plus routing is the only shape
  that scales.
- **Governed mutation surface.** Plan-then-confirm on outward
  mutations is a safety invariant the fleet can enforce in ONE place
  (the resolver), instead of auditing every consumer.
- **Learning compounds per row, not per tool.** The T1-T5 loop
  improves capabilities continuously without re-shipping the tool
  surface; contract_health and probe_checked_at make staleness
  detectable per row.
- **Portability.** The same contract now spans three unrelated APIs
  (Google Workspace, Workato management API, Atlassian). Each new
  surface reuses the invariants and the wall list, which is why the
  third build (Atlassian) reached UAT-passing in days, not weeks.

## Known shared walls (read before planning a fourth surface)

Recorded in the Atlassian walls doc (W1-W5) and devapi experience:
workspace Anthropic connectors 400 on string content vs array-of-blocks
(W2, blocks the T3 promoter); the gateway mangles some PUT bodies (G1);
silent PUT no-op on RUNNING recipes (G5); the data-tables plane is the
fragile substrate (schema PUT wipes tables, field-id rotation, integer
columns unwritable from recipes, W3/G6/G7); empty commit responses
weaken receipts evidence (G9). PATTERN.md section 4.2 records one open
shared instrument gap: neither surface periodically re-verifies SCOPE
appropriateness of a row, only API-shape correctness.

## Traps a new surface must not rediscover

- Adopt the spec, not the code. Copying another gateway's resolver
  copies its drift; read PATTERN.md and the walls doc first (port
  discipline, PATTERN.md section 5).
- Checksums MUST be derived from executable rows only and ordered
  deterministically, and the index and resolver must derive them from
  the same payload, or callers fail closed on ghost mismatches.
- Recovery machinery is a sequenced phase, not a patch: the devapi to
  gw_semantic port was priced at ~18 rejection sites (PATTERN.md
  section 4).
- Build-session updates to the parity matrix land in the same commit
  as the code.

## Related

- Contract of record: `~/orca/projects/dev-api-mcp/PATTERN.md` + `VOCABULARY.md`
- Per-surface state: projects/google-semantic-mcp.md, projects/dev-api-mcp.md,
  projects/atlassian-semantic-mcp.md, projects/otto.md
- The three-tool shape in practice: workato-airo-mcp-server tool list
  (docs_get id guides:overview) mirrors the lifter/router/policy trio
