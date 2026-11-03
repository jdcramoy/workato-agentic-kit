# Workato testing methodologies — the full suite

> Josh's harness, 2026-10-30. This is the inventory of HOW we test every asset
> class, what the agentic surfaces are, and where the agentic limitations sit.
> Companion docs: `workato-development-playbook` (build doctrine),
> `verify-recipe` / `tdd-fix-loop` / `testcase-authoring` / `uat-evidence`
> skills, `red-team-review` skill, `wt-cookbook` (test surfaces).

## 0. Philosophy: evidence-first, trace-or-it-didn't-happen

- A recipe is never "done" because a push returned 200. It's done when a live
  run proves the specific behavior. Every claim cites a job ID, trace line, or
  API response. "The job succeeded" is not evidence for a field mapping.
- Verification defines what "correct" means BEFORE running (the acceptance
  checklist), then runs, then quotes the trace. A guessed business rule written
  into a checklist launders the guess as fact — stop and ask instead.
- Never assert fixed/working/broken without live evidence; every "done" claim
  lists what was NOT verified ("Nothing unverified" when clean).

## 1. Test surfaces inventory (the toolbox)

| Surface | What it is | Best for |
|---|---|---|
| Test Automation API (`wt testcases run/status/cases`) | Headless run of recipe test cases with mocks + assertions | Unit tests for recipes; the nightly regression fleet |
| In-page web_api case create | `POST /web_api/recipes/<id>/test_cases.json` then FLAT `PUT .../test_cases/<caseId>.json` `{name, description, mocks, assertions}`; every assertion needs a client-generated uuid `id` or silently dropped (BSYS-29585) | Browser-free case authoring (AIRO cannot create cases) |
| Test Recipe dialog (UI, Orca) | The canvas Test button | Function recipes; interactive debugging; NOT a headless surface (Test panel ≠ VUA; its caret/JSON views are broken) |
| Force-run / webhook fixture | Invoke the recipe directly (`wt fixture run`, webhook_url from trigger) | Scheduled recipes (no natural trigger to wait for); NEVER wait for the next tick |
| MCP gateway `tools/call` | Real call through the served gateway | MCP servers + skills; the PRIMARY test surface for served tools |
| Attached-client test | Attach the dev MCP server to local config and call real tools | MCP end-to-end (schema caches, served descriptions) |
| Job trace + job_get | Step-by-step execution record | The evidence layer under everything |
| Orca browser | Signed-in Workato UI | Test dialog flows, job traces with masked data, VUA surfaces, Genie testing |

## 2. Testing by asset class

### 2.1 Scheduled recipes

Scheduled recipes have no natural trigger to wait for — and waiting for the next tick is a violation of our own efficiency rules. (2026-10-02/03 lesson). We never wait for a scheduler tick when we need a job NOW: stop → Test → observe trace → restart, or force-run.

**The unit surface: Test Automation API + test cases.** Cases live on the
recipe (Test Automation API): name, description, mocks, assertions. We author
them browser-free via the in-page web_api (flat envelope, uuid-per-assertion —
AIRO cannot create cases; wt is RUN-only). Assertions prove behavior, not
execution: assert on the guard message, the empty-state handling, the correct
count — never on "it ran."

**Agentic limitations (current, real):**

1. **AIRO recipe_builder cannot create test cases.** Case CREATE is web_api or
   UI only; wt is run-only. An agent in an AIRO-only session can run cases but
   not author them.
2. **"could not start run" error class.** The nightly regression fleet sees
   ~20 recipes fail to START under headless runs (2026-10-24 regression report:
   0 passed, 20 errors). Root causes: VUA-bound connectors (identity absent at
   the platform layer headless), deliberately stopped diagnostic recipes, and
   recipes whose tested path requires a resolvable end-user identity. These are
   structural, not flaky — we tag-and-skip them (MASKED entries in
   regression-latest.md, Josh-approved 2026-10-20) with re-entry criteria
   written at tagging time (identity-carrying run, or re-authored headless-safe
   and passing stably).
3. **Rerun-safety needs versioned idempotency keys.** The Workato runtime
   folds a version/timestamp into idempotency keys; a stable key alone
   eventually swallows legitimate new events. The counter-proof pair is
   mandatory in tests: a rerun after partial failure does NOT double-post, AND
   a second distinct occurrence of the same event shape (new version) DOES
   process.
4. **Stopped recipe = MCP tool disappears.** Stopping a recipe for any Test
   flow silently removes its tool from the served MCP tools/list. Always
   restart everything you stopped in the same turn; check `running` on the
   backing recipe FIRST when a tool goes missing.
5. **Test-doc ownership.** Docs created by a recipe live under THAT recipe's
   Google Docs connection account; a 404 is a connection-visibility issue, not
   existence. For MCP-served calls, create test docs THROUGH the gateway.

### 2.2 Function recipes

Function recipes are tested through the Orca editor Test panel (the signed-in
browser), because function execution needs the interactive surface. Never
Transform the test: run it, pull the job trace, quote the lines. The Test
panel is the last-resort surface for MCP-served recipes (its caret menu + JSON
view are broken). Post-test: restart anything stopped in the same turn. For
served skills, a function recipe's real call path is the MCP gateway
tools/call — the function's proof is a real call returning the mapped output
with the served description intact.

### 2.3 Connections

- **Inventory + health:** `list_connections` (dependency-tracker MCP) answers
  "how many, which broken, which never restored after losing auth" — filter
  `authorization_status: "exception"` for broken, `application_name` per system.
- **Live probe:** the connection's recipe-level proof is a real job trace
  through it; connection-auth claims REQUIRE a live recipe-config read-back of
  the binding before asserting ("Missing connection" in a trace is NOT proof of
  an unbound connection — VUA/personalized connections run headless produce the
  same error with the binding intact; proven BSYS-29582).
- **Governance:** personal-identity connections doing bot/service work is a
  red-team Tier 1 finding, not a style issue.
- **The right way (2026-10-08 correction):** before any fix on a shared
  connection, ask what dedicated path exists (dedicated app, custom OAuth
  profile, scoped connection). Governance rules beat the fast path.

### 2.4 Custom SDK connectors

- **Schema first:** `workato-custom-action-schema` — resolve a custom action's
  schema BEFORE mapping datapills; the fix for DatapillSourceBlockNotFound /
  "input.schema not available".
- **Connector Builder sessions:** `connector_builder_get_unreleased_code_diff`
  before every release intent; save/Release are separate confirmations; the
  semantic gateway (devapi) is the governed mutation surface.
- **Validation is connector-side:** sdk_apply_connector_code_patch validates on
  apply; the session source must be read before any patch (never patch from
  memory).

### 2.5 MCP servers and skills

- **Primary test surface = MCP gateway tools/call.** A real call through the
  served gateway is the proof; the served `description` is a UI-copy snapshot
  that does NOT track edits (pushes don't propagate — edit the served
  description explicitly when it matters).
- **End-to-end: attached-client test.** Attach the dev MCP to local config and
  call real tools; switch servers to Workato Identity (OAuth); never curl/
  token-probe or force-run skills.
- **The stopped-recipe gotcha** (section 2.1, item 4) is the #1 MCP test trap.
- **Schema-cache freshness:** verify MCP schema caches are fresh before
  trusting tool descriptions.

### 2.6 Genies

Two surfaces:

1. **Workato test surface (AIRO/AHQ):** genie_get/genie_list for config truth;
   skill-call stats (`FUNC_AI_Directory_Genie_Skills_Stats`) for usage evidence;
   the Workato test/conversation surface for behavior. Genie verdicts post RAW
   OUTPUT DUMPS when the consolidation header is missing — the loop
   consolidates, it never re-triages. Attribution: genies execute as the
   workspace identity "(via AIRO)" — executor guard + zero jobs + empty action
   log exonerated genies of a delete once (BSYS-29262-adjacent 157379 audit).
2. **Browser automation (Slack Workato BT AI workspace):** for the BT AI
   workspace Genies (bt-genie pilots), testing is via the Orca browser in the
   Slack Workato BT AI workspace — conversation-level testing in the real
   destination surface where users meet the Genie. Raw output dumps read as
   broken; the consolidation header fixes the reading, not the Genie.

## 3. The four test types

### 3.1 Unit testing — testcase-authoring

- Failure-signature-first: the fixture must reproduce the BUG, not a happy
  path (empty payload, missing field, oversize payload, expired-token shape,
  boundary value).
- Assertion proves the fix's behavior; counter-proof case proves the guard
  doesn't over-fire.
- A case that has never failed on the unfixed code is unproven — say so.
- Never weaken a fixture to make a case pass.
- Name cases after the failure class: `guard-empty-records-json-payload`.

### 3.2 Regression testing — canon + nightly fleet

- Every failure ends in the regression canon
  (`~/.claude/knowledge/regression-canon/canon.jsonl`) via
  `canonize-failure.py` — recipe, job, slug, fixture scaffold. An autopsy that
  ends without canonization is a report, not a closed loop.
- Nightly regression runs the canon fixtures (`regression-latest.md`); FAIL
  rows carry recipe + job IDs and are the day's first work candidates.
- Fix loop: reproduce from the failure (autopsy to the ORIGIN step, not the
  error step) → failing test first → smallest change → gate (new test passes +
  full canon green + live probe) → 5-strike stop rule → evidence comment.
- Containment is never a fix: an error monitor/try-block envelope that masks
  the failure signal corrupts the regression's exact purpose (BSYS-29582:
  masked-green corruption). Containment must state how the signal survives
  (alarm, quarantine tag, explicit skip — never a silent green).
- MASKED tag-and-skip entries carry Josh approval + re-entry criteria.

### 3.3 Red-team testing — the promotion gate

- Every prod promotion carries a red-team verdict BEFORE the push, no
  exceptions; hotfixes get tier-appropriate review ("urgent" changes the tier,
  never the requirement). The build session dispatches the independent
  `red-team` agent — the builder never reviews its own work.
- Tiers: Tier 1 full (PII/financial/external triggers/outward output), Tier 2
  standard (internal, shared deps), Tier 3 light self-certification (config
  flips — the micro-target sweep IS the checklist).
- Five attack surfaces: secrets & credentials, data exposure (masking gate is
  a GATE, not a note — an unmasked PII line fails the evidence full stop),
  injection surfaces, identity & auth (VUA vs bot correctness), logic abuse
  (idempotency, replayable triggers).
- Verdict: PASS / PASS-WITH-NOTES / FAIL with fatal/material/cosmetic
  severity, evidence-cited. FAIL blocks promotion unless Josh overrides by
  name. Verdict file `~/.claude/knowledge/redteam/<BSYS-id>-<slug>.md` + Jira
  comment.

### 3.4 UAT testing — uat-evidence

- The promotion bottleneck is evidence assembly, not testing. `uat-evidence`
  runs `wt testcases run` per asset, polls to completion, pulls real job URLs
  + key trace lines, applies the masking gate, and assembles the block in
  Josh's standards format (test run IDs, pass/fail rows, job URLs, masking
  confirmation, proven vs structural-only vs not-yet-tested).
- Empty/pending UAT is written as "UAT pending: evidence will record X" —
  never implied. Evidence citing a job that doesn't resolve = invalid block.
- Masking is a gate, not a note — failing it blocks the story's promotion.

## 4. Known agentic limitations (the honest list, 2026-10-30)

1. **Headless = no VUA identity.** VUA-bound connector paths cannot run
   headless (identity absent at the platform layer): Seismic VUA connector
   tests 404 RESOURCE_NOT_FOUND or "Missing connection" with binding intact.
   Tag-and-skip with re-entry criteria, or re-author headless-safe.
2. **"could not start run" error class.** ~20 recipes in the nightly fleet
   fail to START headless (structural: VUA identity, deliberately stopped
   diagnostics, identity-carrying paths).
3. **AIRO cannot author test cases.** Case CREATE is web_api/UI; wt is
   run-only. AIRO sessions can run, not create.
4. **Test panel ≠ VUA.** The UI Test dialog does not carry end-user identity —
   a Test-panel green does not prove the VUA path.
5. **Stopped recipe kills its MCP tool** — silently; restart in the same turn.
6. **MCP served descriptions are UI snapshots** that don't track pushes; schema
   caches go stale.
7. **Fixture/webhook prerequisites.** Some fixtures need the trigger's
   webhook_url (`wt: webhook kind needs fixture webhook_url`); timeouts on
   force-runnable recipes are a distinct class from start-failures.
8. **genie raw-output dumps.** Genie verdict posts without the consolidation
   header read as broken output; the loop consolidates, never re-triages.

## 5. The closure weld

Every failure class terminates in the canon with a covering test
(`failure-close-gate`: a run may mark a finding resolved ONLY if, in the same
run, it updates the durable record — canon row, triage card, or build-ledger
entry). An N-day escalation sweep re-flags unclosed findings. Testing is the
harness's immune system: unit tests bite, the canon remembers, the nightly
runs it, red-team gates promotion, UAT proves it for the business, and the
close-gate prevents a verdict from claiming "fixed" without updating the
durable record.

## 6. Quick-reference: which surface for which job

| Job | Surface | Evidence |
|---|---|---|
| Unit-test a recipe's logic | Test Automation API case (web_api authoring) | run ID + per-case result |
| Prove a build end-to-end | force-run / webhook fixture / real call | job ID + trace lines (verify-recipe table) |
| Prove a served MCP tool | gateway tools/call or attached client | response envelope + schema check |
| Prove a Genie behaves | AIRO test surface + Orca in BT AI workspace | conversation transcript + skill-call stats |
| Prove a custom SDK action | custom-action-schema resolve + Builder validation | resolved schema + unreleased-diff review |
| Gate a promotion | red-team agent (tiered) + uat-evidence | verdict file + UAT evidence block |
| Guard a fix | failing test first (tdd-fix-loop) | canon fixture + nightly pass row |
| Root-cause a failure | workato-autopsy | origin step + classification + proposed diff |
