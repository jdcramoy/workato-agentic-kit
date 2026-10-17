# Agentic platform lessons — Otto codebase study (2026-10-09)

Code-grounded study of `~/orca/projects/otto` (Workato's agentic platform,
~34 services + ~70 library packages) mining lessons for Workato
no-code/low-code development. Every lesson cites real code. Three-way
attribution matters: some patterns are native Otto, some are Josh's
inventions flowing INTO otto, some are harness ports of Otto patterns.

**Attribution map:**
- Native Otto: loop architecture, safety judges, delivery guarantees,
  change sandboxes, tracing idioms.
- Josh's inventions: the semantic-gateway modality (reviewed capability
  registry + content-free routing index + typed facts + plan-then-confirm-commit)
  — born Workato-side, `services/gws-semantic-gateway/` is the phase-1
  import into otto; and the harness fleet (canon, evidence, dissenters,
  squad-build) — ports of Otto patterns, not Otto itself.
- Traffic runs both directions; the meta-skill is the translation.

**Operator's manual for working IN the repo:** skill `otto-house-style`.

## The lessons (each → Workato mapping)

1. **Verification throughput caps agent-authored volume.** Otto's
   AGENTIC_VERIFICATION.md: per-change sandbox envs — fork changed services
   + path closure, template-cloned DB (~5s), TTL, additive-only.
   → Workato: **REJECTED (Josh, 2026-10-09).** We are a fixed AHQ
   end-customer workspace — no OEM/managed-users plane, workspace-per-change
   impossible — and the project-level fallback (prefixed tables + namespaced
   fixtures + provisioner/reaper machinery) gives up more than it gains,
   is cumbersome, and leaves a mess. The Otto lesson that DOES carry: keep
   verification cheap and unqueued — which the current practice already
   does with dev workspace + test cases + verify-recipe evidence. Do not
   re-propose workspace or project sandboxes.

2. **"Delivered" = durably recorded, not enqueued.** Otto acks an event when
   its `<<MSGID>>` marker is byte-verbatim in the on-disk transcript
   (`worker/agentic_loop/delivery.py`); a resume sweep re-drives
   acked-but-never-run.
   → Workato: done = cited job trace/test-run, never say-so (verify-recipe).

3. **Failure policy is per-component, not blanket.** Judges differ by design:
   send/share fail-open on rate limits + fail-closed otherwise; approval
   classifier fails closed to "ask" on every error; schedule judge has no
   approval path. Event-router quarantines permanent failures instead of
   retrying (`read_op.py` mark_disabled).
   → Workato: classify every error branch transient/permanent/capacity
   (now in workato-development-playbook + workato-skill-builder check).

4. **Two-signal rule.** On Anthropic 529: user sees soft-success "retry
   scheduled"; operator sees the real API_ERROR verdict. Exactly one
   authoritative outcome per turn (outcome latch).
   → Workato: notification recipes ≠ monitoring; monitoring reads run
   outcome, not the Slack message (in playbook + skill-builder check).

5. **"Two is a coincidence, three is a pattern."** Gateway SDK refuses to
   abstract what two interfaces share (`library/gateway/settings.py`), but
   enforces what all three share (callback route, dedup-as-context-manager,
   "a 429 must stay a 429").
   → Workato: extract shared functions/connections at third use, not second;
   keep per-asset quirks local at the boundary.

6. **Rotation-safe credentials.** Twilio webhook verification resolves
   current + retiring tokens per webhook, tries each — rotation never 403s a
   live webhook; resolver never raises, fail-closed lives at the wiring
   (`webhook_signature.py`).
   → Workato: old+new accepted in rotation windows, per-connection
   resolution, never a global secret (added to slack-bot-connection).

7. **Cache-prefix discipline.** Sorted tool lists (`run.py:267-281`), sha256
   of prompts in logs, byte-identical timezone wording across turns — the
   prompt prefix is cache AND behavior.
   → Workato: genie/skill instructions byte-stable across publishes; no
   volatile state early (in airo-mcp-playbook).

8. **Guardrails are not agent-configurable.** URL-sanitizer Stop hook is
   deliberately not a FeatureProvider (`run.py:250-254`).
   → Workato: decide which knobs the agent may turn vs constitutional
   (permission gates layered above Genie tools, unremovable).

9. **Versioned idempotency keys.** Fold `changed_at` into dedup keys so one
   event's redeliveries collapse but a later distinct change re-notifies
   (`container.py:551`).
   → Workato: reruns dedupe on (entity, event, event-version) — in
   testcase-authoring as a test form.

10. **Lossy in-memory, durable at the edges.** Tick queue drops at capacity
    and counts it; durability lives in the DB cursor + safety net; retries at
    exactly one layer. No retry queue, no DLQ.
    → Workato: put state/retry at one layer (the data table / the ledger),
    keep inner steps disposable.

11. **Observability must not share a failure domain with the observed.**
    Loop metrics emitted by the loop, not derived from spans, so loop death
    is observable when tracing is down. Link+empty-context idiom for async
    hops (`telemetry/__init__.py:608`).
    → Workato: monitoring path (workato-health, dashboards) reads platform
    state directly, never the bot's own announcements.

12. **The agentic platform is delivery + governance with an LLM in the
    middle.** The worker's loop is thin — it delegates reasoning to the CLI
    and spends its code on exactly-once delivery, restart/resume, permission
    layers, and invariants that survive dying mid-turn (open-turn marker,
    resume sweep, dedup-from-disk).
    → Workato: genies/skills/MCP servers are easy; the engineering is what
    happens when everything dies at the wrong moment. Design for that.

## Semantic-gateway status (Josh's build)

`services/gws-semantic-gateway/` phase-1 prototype: OAuth-chain proof via
Workato connector bridge (service must 401 on expired Google token, never
self-refresh); registry tables landed (`20261009_d311a8c2fb0d`,
`20261009_81371052e15f`); execute/plan-commit = phase 3; MCP rewiring =
phase 4; k8s packaging = phase 7. Convergence rules for later phases live in
skill `otto-house-style` §gws-semantic-gateway.

## Shortlist for action (delivered 2026-10-09)

Change sandboxes — **REJECTED for Workato, see lesson 1; do not re-propose** ·
failure classification
(playbook + skill-builder) · two-signal rule (playbook + skill-builder) ·
rotation-safe connections (slack-bot-connection) · semantic-gateway modality
as the general shape for every agent-facing surface (otto-house-style).

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [Workato One Delivers on the Promise of Agentic Enterprise](../../kb-corpus/blog/workato-one.md)
- [Powering ISVs with AI, Agents, &amp; Orchestration: A First Look at Workato’s Agentic Platform for ISVs](../../kb-corpus/blog/powering-isv-agents.md)
- [The Agentic Workato Harness: a self-improving development organism](../../kb-corpus/confluence/extbt/2938830860-the-agentic-workato-harness-a-self-improving-development-organism.md)
- [Workato Enterprise MCP: The Future of Agentic Automation](../../kb-corpus/blog/workato-mcp.md)
<!-- kb-bridges:end -->
