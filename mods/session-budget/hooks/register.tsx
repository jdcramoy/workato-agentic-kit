// session-budget — Josh's cold-start guardrail (2026-10-11; cost source fixed 2026-10-12).
//
// The 2026-10-11 cost analysis found 26 of 333 sessions carried 80% of the
// week's $3,371 gateway spend, every one a long RESUMED session re-hydrating
// a giant context. Cheapest lever: cap sessions and hand off.
//
// COST SOURCE (the $85-vs-$3.39 bug): the engine's `$.session.usage().cost.usd`
// prices every call against ANTHROPIC's list — a number the Fireworks gateway
// never bills — and for a resumed session it sums the whole lineage since
// first launch. The band showed $85.03 where Josh's status line showed $3.39.
// Fix: compute cost the way the status line does — spawn the Fireconnect
// statusline's own exported helper (claudeStatusLineUsage) over the session
// transcript: Fireworks list rates per actual model, cache-adjusted, parent +
// subagents. One source of truth; the mod keeps no pricing table.
//
// Three surfaces:
//   1. AbovePrompt band  — live $ spent / budget + context %, amber at warn,
//                          red at hard.
//   2. Warn toast        — once, when either warn line is first crossed.
//   3. Hard stop         — classic.Stop blocks the turn end (max 3 times per
//                          session, native stop_hook_active respected) and
//                          orders the model to write the durable handoff +
//                          append the closeout row. Josh starts the next
//                          task cold; the row is the gate that reopens Stop.
//
// Fleet headless jobs (CLAUDE_JOB=yes) and non-interactive surfaces are
// exempt — the fleet needs its full budget and `claude -p` cannot act on a
// band or a blocked stop.
//
// Env knobs (literal names — the engine lists the variables a module reads):
//   SESSION_BUDGET_WARN_USD (25) / SESSION_BUDGET_HARD_USD (50, matches the
//   statusline's alert line) / SESSION_BUDGET_WARN_CTX_PCT (60) /
//   SESSION_BUDGET_HARD_CTX_PCT (85) / SESSION_BUDGET_CLOSEOUT_LEDGER /
//   SESSION_BUDGET_FORCE=warn|hard|off (simulation + kill switch) /
//   SESSION_BUDGET_COST_OVERRIDE (test seam: pins the $ figure).

import { atom, read, update } from 'claude-code'
import type { Register } from 'claude-code'

const DEFAULT_CLOSEOUT =
  '/Users/joshcramoy/.claude/knowledge/handoffs/session-closeouts.jsonl'
const COST_HELPER =
  '/Users/joshcramoy/.fireconnect/cli/packages/setup-cli/lib/harnesses/claude/statusline.mjs'

// Runs OUTSIDE the hooks sandbox (node spawn), so import() and node:fs are
// fine here. argv[1] = transcript path if known ('' if not — mid-load session),
// argv[2] = the cwd's project-slug dir to derive it from (newest .jsonl by
// mtime = the live session's transcript; the file is appended every turn).
// Always prints one JSON line.
const COST_SCRIPT =
  '(async () => {' +
  '  const fs = require("fs");' +
  '  let p = process.argv[1] || "";' +
  '  try { if (!p || !fs.existsSync(p)) {' +
  '    const dir = process.argv[2];' +
  '    const files = fs.readdirSync(dir).filter(f => f.endsWith(".jsonl"))' +
  '      .map(f => ({ f, m: fs.statSync(dir + "/" + f).mtimeMs }))' +
  '      .sort((a, b) => b.m - a.m);' +
  '    if (files.length) p = dir + "/" + files[0].f;' +
  '  } } catch (e) {}' +
  '  if (!p) { console.log(JSON.stringify({ cost: null, cachePct: null })); return; }' +
  '  try {' +
  '    const m = await import(' + JSON.stringify(COST_HELPER) + ');' +
  '    const r = await m.claudeStatusLineUsage(p);' +
  '    console.log(JSON.stringify({ cost: r && r.cost != null ? r.cost : null, cachePct: r && r.cachePct ? r.cachePct : null }));' +
  '  } catch (e) { console.log(JSON.stringify({ cost: null, cachePct: null })); }' +
  '})()'

const warnedAtom = atom({ plugin: 'session-budget', key: 'warned' } as const, false)
const blocksAtom = atom({ plugin: 'session-budget', key: 'blocks' } as const, 0)

type Figures = {
  usd: number | null
  ctxPct: number | null
  warn: boolean
  hard: boolean
}

function envNum(raw: unknown, fallback: number): number {
  const v = raw == null || raw === '' ? NaN : Number(raw)
  return Number.isFinite(v) ? v : fallback
}

// Every env name is a literal: the engine lists the variables a module reads.
async function thresholds($: any) {
  const [warnUsd, hardUsd, warnCtx, hardCtx, ledger] = await Promise.all([
    $.env.get('SESSION_BUDGET_WARN_USD'),
    $.env.get('SESSION_BUDGET_HARD_USD'),
    $.env.get('SESSION_BUDGET_WARN_CTX_PCT'),
    $.env.get('SESSION_BUDGET_HARD_CTX_PCT'),
    $.env.get('SESSION_BUDGET_CLOSEOUT_LEDGER'),
  ])
  return {
    warnUsd: envNum(warnUsd, 25),
    hardUsd: envNum(hardUsd, 50),
    warnCtx: envNum(warnCtx, 60),
    hardCtx: envNum(hardCtx, 85),
    closeout: ledger ? String(ledger) : DEFAULT_CLOSEOUT,
  }
}

// Fireworks-accurate session cost via the statusline's own helper, cached 30s
// per transcript (the statusline spawns per refresh too; a band redraw must
// not). lastTranscript is captured at SessionStart/Stop; when empty (mod
// loaded mid-session) the helper derives the newest transcript from cwd.
let lastTranscript = ''
let costCache: { path: string; cost: number | null; cachePct: string | null; at: number } | null = null

async function projectDir($: any): Promise<string> {
  try {
    const cwd = await $.session.cwd()
    return '/Users/joshcramoy/.claude/projects/' + String(cwd).replace(/\//g, '-')
  } catch {
    return ''
  }
}

async function fireworksCost(
  $: any,
  transcript: string,
  dir: string,
): Promise<{ cost: number | null; cachePct: string | null } | null> {
  const now = await $.clock.now()
  const key = transcript || dir
  if (!key) return null
  if (costCache && costCache.path === key && now - costCache.at < 30000) {
    return costCache
  }
  try {
    const r = await $.process.run(['node', '-e', COST_SCRIPT, transcript, dir])
    if (r.exitCode !== 0) return costCache
    const parsed = JSON.parse(String(r.stdout).trim().split('\n').pop() || '{}')
    costCache = {
      path: key,
      cost: parsed.cost == null ? null : Number(parsed.cost),
      cachePct: parsed.cachePct == null ? null : String(parsed.cachePct),
      at: now,
    }
    return costCache
  } catch {
    return null
  }
}

async function figures($: any, transcript: string): Promise<Figures | null> {
  try {
    const t = await thresholds($)
    // Simulation / kill switch, checked before anything reads the engine:
    // 'warn'/'hard' force the state, 'off' disables without uninstalling.
    const force = await $.env.get('SESSION_BUDGET_FORCE')
    if (force === 'off') return null
    if (force === 'warn' || force === 'hard') {
      return { usd: null, ctxPct: null, warn: true, hard: force === 'hard' }
    }
    const [u, pin, dir, fw] = await Promise.all([
      $.session.usage(),
      $.env.get('SESSION_BUDGET_COST_OVERRIDE'),
      projectDir($),
      fireworksCost($, transcript, ''),
    ])
    // dir resolved after cwd read; retry the derivation when no transcript
    const cost = fw ?? (dir ? await fireworksCost($, '', dir) : null)
    const usd = pin != null && pin !== '' ? Number(pin) : cost ? cost.cost : null
    const ctxPct =
      u?.context?.percent != null ? (u.context.percent as number) : null
    if (usd == null && ctxPct == null) return null
    const warn =
      (usd != null && usd >= t.warnUsd) ||
      (ctxPct != null && ctxPct >= t.warnCtx)
    const hard =
      (usd != null && usd >= t.hardUsd) ||
      (ctxPct != null && ctxPct >= t.hardCtx)
    return { usd, ctxPct, warn, hard }
  } catch {
    return null
  }
}

// Fleet jobs and non-interactive runs never see any of this.
async function isExempt($: any): Promise<boolean> {
  if ((await $.env.get('CLAUDE_JOB')) === 'yes') return true
  try {
    const surface = await $.session.surface()
    return !surface
  } catch {
    return false
  }
}

async function hasCloseout($: any, sessionId: string): Promise<boolean> {
  try {
    const path = (await thresholds($)).closeout
    // No $.fs.exists first: a missing file throws on read, which the catch
    // treats as "no closeout yet" — fail-closed toward blocking.
    const text = await $.fs.read(path)
    for (const line of String(text).split('\n')) {
      if (!line.trim()) continue
      try {
        if (JSON.parse(line).session_id === sessionId) return true
      } catch {
        // skip malformed lines
      }
    }
    return false
  } catch {
    return false
  }
}

export const register: Register = (on) => {
  // Capture the transcript path as early as the engine stamps it.
  on('classic.SessionStart', async ($, e, next) => {
    if (e.transcript_path) lastTranscript = e.transcript_path
    return next(e)
  })

  on('session.start', async ($, e, next) => {
    $.command.register({
      name: 'budget',
      description:
        'Show this session gateway spend, context usage, and budget state',
    })
    return next(e)
  })

  on('command.run', async ($, e, next) => {
    if (e.command !== 'budget') return next(e)
    const f = await figures($, lastTranscript)
    if (!f) return { text: 'session-budget: no usage figures available yet.' }
    const t = await thresholds($)
    const state = f.hard
      ? 'HARD LIMIT — wrap up and hand off'
      : f.warn
        ? 'WARN — consider wrapping up'
        : 'within budget'
    return {
      text: [
        `session spend: ${f.usd == null ? 'n/a' : '$' + f.usd.toFixed(2)} (warn $${t.warnUsd} / hard $${t.hardUsd}) — Fireworks-accurate, same source as the status line`,
        `context: ${f.ctxPct == null ? 'n/a' : f.ctxPct.toFixed(0) + '%'} (warn ${t.warnCtx}% / hard ${t.hardCtx}%)`,
        `state: ${state}`,
        'hard limit blocks turn end until a durable handoff is written and a closeout row lands in ' + t.closeout,
      ].join('\n'),
    }
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (await isExempt($)) return next(e)
    const f = await figures($, lastTranscript)
    if (!f) return next(e)
    if ((f.usd == null || f.usd < 0.5) && (f.ctxPct == null || f.ctxPct < 20)) {
      return next(e)
    }
    const t = await thresholds($)
    const { Box, Text } = $.ui.resolve(e)
    const money = f.usd == null ? '$n/a' : '$' + f.usd.toFixed(2)
    const ctx = f.ctxPct == null ? 'ctx n/a' : `ctx ${f.ctxPct.toFixed(0)}%`
    return (
      <Box>
        <Text color={f.hard ? 'red' : f.warn ? 'yellow' : undefined} dimColor={!f.warn && !f.hard}>
          session {money} / ${t.hardUsd} · {ctx}
        </Text>
      </Box>
    )
  })

  on('turn.complete', async ($, e, next) => {
    if (await isExempt($)) return next(e)
    const f = await figures($, lastTranscript)
    if (!f) return next(e)
    const warnedOnce = await read($, warnedAtom)
    if (f.warn && !warnedOnce) {
      await update($, warnedAtom, () => true)
      $.ui.toast(
        `session-budget: at ${f.usd == null ? '' : '$' + f.usd.toFixed(2) + ' · '}${f.ctxPct == null ? '' : f.ctxPct.toFixed(0) + '% context'} — wrap up soon; prefer a handoff and a cold start over resuming.`,
      )
    }
    return next(e)
  })

  on('classic.Stop', async ($, e, next) => {
    if (await isExempt($)) return next(e)
    if (e.transcript_path) lastTranscript = e.transcript_path
    if (e.stop_hook_active) return next(e)
    const f = await figures($, lastTranscript)
    if (!f || !f.hard) return next(e)

    const sessionId = String(
      e.session_id || (await $.session.id()) || 'unknown',
    )
    if (await hasCloseout($, sessionId)) return next(e)

    const blocks = await read($, blocksAtom)
    if (blocks >= 3) {
      $.ui.toast(
        'session-budget: block budget exhausted — session may end without a closeout row.',
      )
      return next(e)
    }
    await update($, blocksAtom, (n) => n + 1)

    const row = JSON.stringify({
      session_id: sessionId,
      ts: '<current ISO timestamp>',
      handoff_path: '<path of the handoff you just wrote>',
      summary: '<one line: what this session did and its final state>',
    })
    return {
      block:
        `SESSION BUDGET EXHAUSTED (spend ${f.usd == null ? 'n/a' : '$' + f.usd.toFixed(2)} / hard $${(await thresholds($)).hardUsd}, context ${f.ctxPct == null ? 'n/a' : f.ctxPct.toFixed(0) + '%'}). ` +
        `Do NOT start new work. Wrap up now, in this order:\n` +
        `1. Invoke the handoff skill and write the durable session handoff (what was done, current state, verified vs claimed, exact next command). ` +
        `Record the mission-control closeout row per the standing rule if this was a substantial session.\n` +
        `2. Append exactly one line to ${(await thresholds($)).closeout} (create the file if missing):\n${row}\n` +
        `with "ts" the current ISO timestamp and handoff_path the real path from step 1.\n` +
        `3. End your turn. Josh starts the next task in a fresh session.`,
    }
  })
}
