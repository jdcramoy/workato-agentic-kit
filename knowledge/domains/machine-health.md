# Machine health — memory pressure postmortem (Josh's Mac, 2026-10-16)

Verdict: the "mystery Python processes" crashing the machine were OURS, with one
corporate co-conspirator. Three stacked causes, all confirmed live:

## 1. Per-session KB index duplication (design flaw, PRIMARY)
Every Claude Code session spawns its own `kb.mcp_server` (stdio). On first KB
query it loads the FULL ~200k-chunk vector index: **~3.4GB per loaded session**.
13 loaded copies coexisted ≈ 45GB → swap thrash (load avg 34, Force Quit hanging).
Same pattern for `brain-mcp` (one per session) but those stay ~1MB — harmless.

## 2. Lingering sessions (the multiplier)
52 claude processes, ages 3 min – 3d7h, all interactive terminal tabs, ~all idle.
Sessions never exit → their MCP children never exit.

## 3. kb.sync runaway (the crash-er)
`python -m kb.sync` (KB ingestion), launched ~21:37 detached (parent=launchd),
grew to **35GB footprint in 4.5h** with 36 threads at ~0% CPU. Alone took swap
from 12GB → 30GB used and load to 110. `kill -TERM` — exited cleanly, no respawn.

## Cleanup applied (2026-10-16 ~02:14)
- Killed 42 claude sessions idle >12h (kept 9 recent + active + current); MCP
  children reaped automatically via stdio close — zero orphans left behind.
- TERM'd kb.sync 35GB runaway.
- Result: swap 30GB→10GB, load 110→47 falling.

## Open fixes (proposals, not built)
1. ~~**Make kb.mcp_server attach to the shared `kb.daemon`**~~ **BUILT 2026-10-16
   (02:3x):** `kb/mcp_server.py` is now daemon-first — tool calls proxy to
   127.0.0.1:8765 (/search /read /zoom); in-process (3.4GB load) only as cold
   fallback when the daemon is down, same contract as the `kb` CLI. Verified
   live: RSS after a search **26MB vs ~3400MB pre-fix**; cold fallback answers
   with daemon down; KB_DAEMON_URL env override for tests. Existing sessions
   keep old code until they restart; the one loaded 3.4GB copy dies with its
   session. Uncommitted in ~/Documents/workato-kb at time of build.
2. Session reaper: alert/kill claude sessions idle >12h (cron or watchdog row).
3. Corporate leakers for IT: `zdpd` (Zscaler ZDX agent, 4.5GB/144 threads, 3.8d),
   `DisplayLinkPrivilegedHelper` (3.3GB). Root-owned; reboot clears temporarily.
4. `sync.harness_sync` daemon (3.2GB, 32 threads) — by design but heavy; audit
   whether it needs the full dataset resident.

## Traps
- Activity Monitor "Memory" = phys_footprint (includes compressed+swapped); ps
  RSS shows ~1MB for these while AM shows 3.4GB. Trust AM for footprint, ps for
  identity. Check `top -l 1 -o mem` for the real-time sorted view.
- Force Quit (SIGTERM) hangs during swap thrash; terminal `kill -9` on the PID
  works. Root processes can't be Force Quit at all.
- Screenshot PIDs are ephemeral — the +1 offset vs session PIDs was a red
  herring; match on thread count (19 = loaded kb server) and command line.
