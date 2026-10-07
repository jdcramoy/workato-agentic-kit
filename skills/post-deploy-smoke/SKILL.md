---
name: post-deploy-smoke
description: Post-promotion smoke test — prove the deployed assets are actually running correctly in the target environment: first job observed green, connections verified, schedule confirmed, VUA re-checked. Use after any production import/promotion, or when Josh asks "verify the deploy", "smoke test prod".
---

# Post-deploy smoke

A promotion ends at "proven running in production", not "package imported."

## The checklist (in order, all required)

1. **Placement.** Assets landed in the right folder/project in the target
   environment (IDs from the manifest, verified via the prod AIRO read
   tools or wt-prod).
2. **Connections.** Every connection on the imported assets is authorized in
   prod (no "missing connection" — the import-time trap). VUA assets:
   confirm end-user connection mode survived the import.
3. **Properties.** Project/environment properties resolve in prod (not
   pointing at dev values).
4. **First job observed.** Trigger or watch the first real job per asset
   (scheduler: confirm next tick is scheduled and, when allowed, force-run
   a dev-parity check first). Green trace or it isn't done.
5. **Masking in prod.** The first job's trace is masked where it must be.
6. **State restore.** Scheduled recipes end in their intended running state;
   nothing left stopped from the import dance.

## Output

A smoke report: per asset, the six checks with evidence refs (prod job URLs,
connection status, run state). Failures go to Josh immediately with the
blast radius computed.

## Rules

- Prod reads are fine; prod WRITES need Josh's explicit confirmation, always
  (hook 13 + the AIRO gate).
- "Green import" ≠ "smoke passed". The first observed job is the bar.
- If the first job can't be safely induced, the report says so and names
  what would prove it instead.
