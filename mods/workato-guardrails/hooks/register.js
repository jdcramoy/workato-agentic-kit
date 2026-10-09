// workato-guardrails — mechanizes Josh's standing Workato/Jira rules.
// v0.1: prod-write audit, Jira story-points enforcement, Workato URL linker.
// v0.2: secret redaction on tool results, jira-story-standards prompt
//       injection, AbovePrompt status band, /guardrails status command.

const AUDIT_DIR = '$HOME/.claude/workato-audit'
const AUDIT_FILE = AUDIT_DIR + '/prod-writes.log'
const STANDARDS_PATH =
  '/Users/joshcramoy/.claude/skills/jira-story-standards/SKILL.md'

// Write-surface tools on the prod AIRO server. Read tools pass through untouched.
const PROD_WRITE = /^mcp__workato-airo-mcp-prod__(recipe_builder_(save|push|init|init_skill|add_step|update_step|remove_step|remove_input_field|move_step|move_steps|set_input_field|set_input_field_v4_mode|set_condition|set_foreach_source|set_error_handling_config|set_block_comments|update_asset_metadata|select_connections|convert_to_skill)|blueprint_(apply|init|push|link_asset|reset)|genie_(create|update)|data_table_(create|delete|update|truncate)|knowledge_base_(create|delete|delete_documents|update|upload_file)|mcp_server_create|connector_builder_(apply_connector_code_patch|init_connector|release_connector|save_latest_connector_code))/

// Jira projects where the Story Points field is NOT on the issue-type screens.
const POINTS_BLOCKED_PROJECTS = ['BTSUP', 'HROPS', 'PSM', 'MCP']

const WORKATO_TOOLS = /^mcp__(workato-airo-mcp-server|workato-airo-mcp-prod|workato-dependency-tracker)__/

// Build ledger: every Workato mutation across AIRO MCP, the Workato CLI, and
// Orca browser automation lands here — one line per event, shared across
// sessions (this is what lets any session answer "what did we change").
const BUILD_LEDGER_DIR = '$HOME/.claude/knowledge'
const BUILD_LEDGER = BUILD_LEDGER_DIR + '/build-ledger.jsonl'
// Atomic append helper (flock + temp file + os.replace) — shared with knowledge/scripts.
const ATOMIC_APPEND_PY = '$HOME/.claude/knowledge/scripts/atomic_io.py'
const SYSPY = '/usr/bin/python3'
const RECIPE_HISTORY = '$HOME/.claude/recipe-history'

// AIRO mutation tools (dev + prod). Reads never ledger.
const AIRO_MUTATION = /^mcp__workato-airo-mcp-(server|prod)__(recipe_builder_(save|push|init|init_skill|add_step|update_step|remove_step|remove_input_field|move_step|move_steps|set_input_field|set_input_field_v4_mode|set_condition|set_foreach_source|set_error_handling_config|set_block_comments|update_asset_metadata|select_connections|convert_to_skill)|blueprint_(apply|init|push|link_asset|reset)|genie_(create|update)|data_table_(create|delete|update|truncate)|knowledge_base_(create|delete|delete_documents|update|upload_file)|mcp_server_create|connector_builder_(apply_connector_code_patch|init_connector|release_connector|save_latest_connector_code))$/

const TICKET_KEY = /\b([A-Z]{2,6}-\d{3,5})\b/

// Append one event to the build ledger (top-level decl: static-analysis rule).
function ledgerAppend($, event) {
  const line = JSON.stringify({ ts: new Date().toISOString(), ...event }) + '\n'
  // Atomic: temp file + rename via atomic_io.py (was plain 'cat >>', which
  // truncated line 4837 once when a write died mid-record).
  return $.process
    .run(['sh', '-c', 'mkdir -p ' + BUILD_LEDGER_DIR + ' && ' + SYSPY + ' ' + ATOMIC_APPEND_PY + ' ' + BUILD_LEDGER], { stdin: line })
    .catch(() => {})
}

// Opportunistic claim verification: real work doubles as evidence. Appends
// observations to claims/verifications.jsonl; the gardener rolls them up
// into claims.jsonl last_verified. Never rewrites claims directly.
function verifyClaim($, subject, observation, evidence) {
  const line = JSON.stringify({
    ts: new Date().toISOString(),
    subject: subject,
    observation: observation,
    evidence: evidence,
  }) + '\n'
  const dir = '$HOME/.claude/knowledge/claims'
  return $.process
    .run(['sh', '-c', 'mkdir -p ' + dir + ' && ' + SYSPY + ' ' + ATOMIC_APPEND_PY + ' ' + dir + '/verifications.jsonl'], { stdin: line })
    .catch(() => {})
}

const POINT_SCALE =
  'Story Points scale (1pt = 1 dev day): 1 trivial <2h, 2 half day, ' +
  '3 one day, 5 2-3 days w/ UAT, 8 one week, 13 epic, 21 program.'

// Distilled jira-story-standards, used when the SKILL.md cannot be read.
const STANDARDS_FALLBACK = [
  '[workato-guardrails] jira-story-standards (fallback digest) apply:',
  '- Story sections: ## Business Requirements, ## Technical Requirements,',
  '  ## Acceptance Criteria (checkboxes), ## UAT Evidence (even if pending).',
  '- Epic format: ## Background, ## Objective, ## Scope, ## Out of Scope,',
  '  ## Success Measures, ## Acceptance Criteria.',
  '- ALWAYS set Story Points at creation (customfield_10057, number).',
  '  ' + POINT_SCALE,
  '- Blocked-points projects: BTSUP, HROPS, PSM, MCP (note once, move on).',
  '- Deployments are filed as Story/Bug under the governing Epic, NEVER the',
  '  "Deployment Request" issue type.',
  '- Link each Story to its Epic via parent; batch creation; return a',
  '  summary table (key, points, one-line).',
].join('\n')

// Secret shapes to redact from tool results before Claude reads them.
const SECRET_PATTERNS = [
  // Well-known key prefixes
  {
    re: /\b(sk-ant-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,})/g,
    to: '[REDACTED]',
  },
  // Bearer / Authorization headers
  { re: /\bBearer [A-Za-z0-9._~+/=-]{20,}/g, to: 'Bearer [REDACTED]' },
  // key/value secret assignments (value must look secret-shaped: 16+ chars)
  {
    re: /((?:api[_-]?key|x-api-key|access[_-]?token|auth[_-]?token|refresh[_-]?token|client[_-]?secret|password|secret)["']?\s*[:=]\s*["']?)[A-Za-z0-9._~+/=-]{16,}/gi,
    to: '$1[REDACTED]',
  },
]

// ---- helpers --------------------------------------------------------------

function redactString(text) {
  let out = text
  let hits = 0
  for (const p of SECRET_PATTERNS) {
    out = out.replace(p.re, (...args) => {
      hits += 1
      // Support $1-style backreferences in the replacement
      const groups = args.slice(0, -2)
      return p.to.replace(/\$(\d)/g, (m, i) => groups[Number(i)] ?? m)
    })
  }
  return { text: out, hits }
}

// Walk the result shapes tools produce; redact every string inside.
function redactResult(result) {
  if (typeof result === 'string') return redactString(result)
  if (result && typeof result === 'object') {
    if (typeof result.result === 'string') {
      const r = redactString(result.result)
      return { changed: r.hits, result: { ...result, result: r.text } }
    }
    if (Array.isArray(result.content)) {
      let hits = 0
      const content = result.content.map((block) => {
        if (block && block.type === 'text' && typeof block.text === 'string') {
          const r = redactString(block.text)
          hits += r.hits
          return { ...block, text: r.text }
        }
        return block
      })
      return { changed: hits, result: { ...result, content } }
    }
  }
  return { changed: 0, result }
}

// True when the tool result text already contains a canonical Workato URL,
// so we never annotate the same result twice.
function hasWorkatoUrl(text) {
  return text.indexOf('app.workato.com/recipes/') !== -1
}

// Pull asset IDs out of a blob of text and return canonical URLs.
function extractLinks(text) {
  const links = []
  const seen = {}
  const recipeIds = text.matchAll(/(?<![_\w])recipe_id["':\s]+(\d{6,})/g)
  for (const m of recipeIds) {
    if (!seen[m[1]]) {
      seen[m[1]] = true
      links.push('https://app.workato.com/recipes/' + m[1])
    }
  }
  const tables = text.matchAll(/(?<![_\w])data_table_id["':\s]+("?[\w-]{8,}"?)/g)
  for (const m of tables) {
    const id = m[1].replace(/"/g, '')
    if (!seen[id]) {
      seen[id] = true
      links.push('https://app.workato.com/data_tables/' + id)
    }
  }
  const folders = text.matchAll(/(?<![_\w])folder_id["':\s]+(\d{6,})/g)
  for (const m of folders) {
    if (!seen['f' + m[1]]) {
      seen['f' + m[1]] = true
      links.push('https://app.workato.com/recipes?fid=' + m[1])
    }
  }
  return links
}

// Append the URL block to whatever result shape the tool produced.
function annotate(result, block) {
  if (typeof result === 'string') return result + block
  if (result && typeof result === 'object') {
    if (typeof result.result === 'string') {
      return { ...result, result: result.result + block }
    }
    if (Array.isArray(result.result)) {
      return { ...result, result: [...result.result, { type: 'text', text: block }] }
    }
    if (Array.isArray(result.content)) {
      return { ...result, content: [...result.content, { type: 'text', text: block }] }
    }
  }
  return result
}

// Does this prompt ask for Jira work that jira-story-standards governs?
function isJiraWritePrompt(text) {
  return /\b(create|write|draft|file|open|point|estimate|update)\b[^.?!]{0,80}\b(jira|epic|stories?|tickets?)\b/i.test(text) ||
    /\b(jira|epic|stories?|tickets?)\b[^.?!]{0,80}\b(create|write|draft|file)\b/i.test(text)
}

// Score a push from the dependency tracker's per-step rows: dedupe to the
// row carrying real job stats (running and/or non-zero counts), then weigh.
function scoreRisk(mcpResult, churn) {
  let rows = []
  try {
    const blocks = mcpResult?.content ?? []
    const text = blocks.map((b) => b?.text ?? '').join('')
    const parsed = JSON.parse(text)
    rows = parsed?.result?.results ?? []
  } catch {
    return { error: 'unparseable tracker result' }
  }
  if (!Array.isArray(rows) || rows.length === 0) {
    return { error: 'recipe not found in tracker' }
  }
  // The tracker returns one row per step; prefer the row with live state.
  const live = rows.find((r) => r.running) ||
    rows.find((r) => (r.lifetime_task_count ?? 0) > 0) || rows[0]

  let score = 0
  const reasons = []
  const running = !!live.running
  if (running) {
    score += 2
    reasons.push('recipe is RUNNING (push on a running recipe fails or needs stop-first)')
  }
  const ok = live.job_succeeded_count ?? 0
  const bad = live.job_failed_count ?? 0
  const lifetime = live.lifetime_task_count ?? 0
  if (lifetime === 0) {
    score += 2
    reasons.push('never run — no job evidence at all')
  } else {
    const failRate = bad / Math.max(1, ok + bad)
    if (failRate > 0.2) {
      score += 3
      reasons.push('fail rate ' + Math.round(failRate * 100) + '% (' + bad + ' failed of ' + (ok + bad) + ')')
    } else if (bad > 0) {
      score += 1
      reasons.push(bad + ' failed job(s) on record')
    }
    if (live.last_run_at) {
      const days = (Date.now() - Date.parse(live.last_run_at)) / 86400000
      if (days > 14) {
        score += 1
        reasons.push('last run ' + Math.round(days) + ' days ago — cold')
      }
    }
  }
  if (live.stopped_at) {
    score += 1
    reasons.push('recipe is STOPPED (' + (live.stop_cause || 'unknown cause') + ') — push ok, remember to start it back')
  }
  if (lifetime >= 500) {
    reasons.push('high-traffic recipe (' + lifetime + ' lifetime tasks) — many downstream consumers')
  }
  // Ledger churn: real edit frequency from the build ledger (passed in).
  if (churn && churn.count > 0) {
    if (churn.count >= 4) {
      score += 2
      reasons.push('churn: edited ' + churn.count + 'x this week across ' +
        churn.sessions + ' session(s) — destabilized asset')
    } else if (churn.count >= 2) {
      score += 1
      reasons.push('edited ' + churn.count + 'x this week')
    }
    if (churn.lastTs && live.updated_at && Date.parse(live.updated_at) > Date.parse(churn.lastTs) + 120000) {
      score += 1
      reasons.push('external drift: updated_at is newer than the last ledgered edit — someone else touched it')
    }
  }
  const label = score >= 5 ? 'high' : score >= 3 ? 'medium' : 'low'
  return { score: score, label: label, reasons: reasons.length ? reasons : ['healthy: running history looks clean'], running: running }
}

// Count this week's ledgered mutations of a recipe + distinct sessions.
async function ledgerChurn($, recipeId) {
  try {
    const file = await $.fs.read(BUILD_LEDGER.replace('$HOME', process.env.HOME))
    const text = file.text ?? file
    const cutoff = Date.now() - 7 * 86400000
    let count = 0
    const sessions = new Set()
    let lastTs = null
    for (const line of String(text).split('\n')) {
      if (!line.trim()) continue
      let ev
      try { ev = JSON.parse(line) } catch { continue }
      if (ev.recipe_id !== recipeId) continue
      if (Date.parse(ev.ts) < cutoff) continue
      count += 1
      if (ev.session) sessions.add(ev.session)
      lastTs = ev.ts
    }
    return { count, sessions: sessions.size, lastTs }
  } catch {
    return null
  }
}

// ---- registration ---------------------------------------------------------

export function register(on) {
  // Session state: standards text, prod-write counters, /guardrails command.
  let standards = null
  let prodWrites = 0

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'guardrails',
      description: 'Show workato-guardrails status: hooks, prod-write audit, counters',
    })
    await $.command.register({
      name: 'builds',
      description: 'What this workspace touched: ledger summary (today | week | all)',
    })
    await $.command.register({
      name: 'promotion-ready',
      description: 'Dev builds edited but not yet marked promoted',
    })
    await $.command.register({
      name: 'promoted',
      description: 'Mark a recipe promoted: /promoted <recipe_id> [recipe_id...]',
    })
    await $.command.register({
      name: 'snapdiff',
      description: 'Recipe snapshot history: /snapdiff <recipe_id> shows recent changes',
    })
    await $.command.register({
      name: 'cockpit',
      description: 'Cockpit: terminal pane (bare) or full-page dashboard (/cockpit full)',
    })
    // Recipe-history repo: init once, snapshot pushes forever.
    await $.process.run(['sh', '-c',
      'mkdir -p ' + RECIPE_HISTORY + ' && cd ' + RECIPE_HISTORY +
      ' && git init -q 2>/dev/null; true'])
    try {
      const file = await $.fs.read(STANDARDS_PATH)
      standards = file.text ?? file
      // Keep the injection bounded; the full skill loads via the Skill tool.
      if (standards.length > 4000) standards = standards.slice(0, 4000)
    } catch {
      standards = null
    }
    const saved = await $.store.get('prodWrites')
    if (typeof saved === 'number') prodWrites = saved
    return next(e)
  })

  // /guardrails — status card in the transcript
  on('command.run', { command: 'guardrails' }, async () => {
    return {
      text:
        'workato-guardrails v0.7.0 active hooks:\n' +
        '1. secret redaction on tool results (outermost)\n' +
        '2. prod-write audit → ' + AUDIT_FILE + ' (this session: ' + prodWrites + ')\n' +
        '3. Jira story-points gate (customfield_10057; BTSUP/HROPS/PSM/MCP exempt)\n' +
        '4. Workato asset URL linker (AIRO + dependency-tracker results)\n' +
        '5. jira-story-standards prompt injection (' +
        (standards ? 'SKILL.md loaded' : 'fallback digest') + ')\n' +
        '6. status band above the prompt + /guardrails /cockpit /builds /promotion-ready /promoted /snapdiff\n' +
        '7. datapill trap warning on recipe_builder_pull\n' +
        '8. writeback re-read nudge on Jira/Confluence writes\n' +
        '9. push risk scorer (tracker lookup; risky PROD pushes held for confirm)\n' +
        '10. build ledger — AIRO mutations (dev+prod) with ticket tracking\n' +
        '11. build ledger — CLI/Orca via Bash sniffing + CLI-start claim verification\n' +
        '12. recipe snapshot history → ~/.claude/recipe-history (git) on every push\n' +
        '14. remote-identity guard (git push to non-org remote held for confirm)\n' +
        '13. prod-write confirm gate — EVERY surface (workato-prod, wt-prod, ' +
        'WORKATO_PROFILE=josh-prod, raw http w/ prod credential, Orca on prod urls)',
    }
  })

  // 4. SECRET REDACTION — registered FIRST so it is outermost in the
  // tool.call chain: whatever inner hooks (URL linker, prod audit) return
  // still passes through redaction on the way out.
  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    if (!result || result.deny) return result
    const r = redactResult(result)
    if (r.changed > 0) {
      $.ui.log('workato-guardrails redacted ' + r.changed + ' secret pattern(s) from ' + e.tool)
    }
    return r.changed > 0 ? r.result : result
  })

  // 1. PROD-WRITE AUDIT + VISIBILITY
  on('tool.call', { tool: /^mcp__workato-airo-mcp-prod__/ }, async ($, e, next) => {
    if (PROD_WRITE.test(e.tool)) {
      prodWrites += 1
      await $.store.set('prodWrites', prodWrites)
      const stamp = new Date().toISOString()
      const line = stamp + ' PROD-WRITE ' + e.tool + '\n'
      // Append via shell: $.fs.write overwrites, and the audit log must grow.
      await $.process.run(['sh', '-c', 'mkdir -p ' + AUDIT_DIR + ' && cat >> ' + AUDIT_FILE], { stdin: line })
      // Visible to Josh in the transcript; Claude does not read ui.log lines.
      $.ui.log('PROD WRITE · ' + e.tool)
    }
    return next(e)
  })

  // 9. PUSH RISK SCORER — before any recipe_builder_push, look up the
  //    recipe's live health via the dependency tracker and score the push.
  //    Dev pushes: score annotated onto the result. Prod pushes with a
  //    medium+ score (or a RUNNING recipe): the call holds for an explicit
  //    proceed/cancel with the score in the prompt.
  //    session_id -> recipe_id is learned from recipe_builder_pull/save calls.
  const sessionRecipes = new Map()

  function trackSession(e, result) {
    const sid = String(e.session_id ?? '')
    if (!sid) return
    if (e.recipe_id != null) {
      sessionRecipes.set(sid, e.recipe_id)
      return
    }
    if (!sessionRecipes.has(sid) && result) {
      const blob = JSON.stringify(result?.result ?? result?.content ?? '')
      const m = blob.match(/recipe_id["':\s]+(\d{6,})/) || blob.match(/recipes\/(\d{6,})/)
      if (m) sessionRecipes.set(sid, Number(m[1]))
    }
  }

  on('tool.call', { tool: /^mcp__workato-airo-mcp-(server|prod)__recipe_builder_(pull|save|push)$/ }, async ($, e, next) => {
    const isPush = e.tool.endsWith('recipe_builder_push')
    const isProd = e.tool.indexOf('mcp-prod') !== -1

    let risk = null
    if (isPush) {
      trackSession(e, null)
      const rid = sessionRecipes.get(String(e.session_id ?? ''))
      if (rid != null) {
        try {
          const res = await $.mcp.call('workato-dependency-tracker', 'search_recipe_dependencies', { recipe_id: String(rid) })
          const churn = await ledgerChurn($, rid)
          risk = scoreRisk(res, churn)
        } catch {
          risk = { error: 'risk lookup unavailable' }
        }
      } else {
        risk = { error: 'no recipe tracked for this session (pull or save first)' }
      }
      // Gate prod pushes that look risky; ui.ask time does not count against
      // the hook's time limit, and a dismissed dialog fails closed.
      let bypassOnPush = false
      try {
        const bf2 = await $.fs.read(BYPASS_PATH)
        const bj2 = JSON.parse(String(bf2.text ?? bf2))
        bypassOnPush = typeof bj2.until === 'number' && bj2.until * 1000 > Date.now()
      } catch { bypassOnPush = false }
      if (isProd && risk && !risk.error && (risk.score >= 3 || risk.running) && !bypassOnPush) {
        let answer = 'Cancel push'
        try {
          answer = await $.ui.ask(
            'PUSH RISK ' + risk.label.toUpperCase() + ' (' + risk.score + '/10): ' +
              risk.reasons.join('; ') + '. Push to PROD?',
            ['Push anyway', 'Cancel push'],
          )
        } catch {
          answer = 'Cancel push'
        }
        if (answer !== 'Push anyway') {
          return {
            deny:
              'Push cancelled by workato-guardrails risk gate (' + risk.label + '): ' +
              risk.reasons.join('; ') +
              '. Resolve and retry, or ask Josh to override by telling you to push explicitly.',
          }
        }
      }
    }

    const result = await next(e)
    if (!isPush) trackSession(e, result)

    // Opportunistic verification: a push that succeeded while the recipe was
    // RUNNING is live evidence about the push-on-running claim.
    if (isPush && result && !result.deny && !result.isError && risk && !risk.error && risk.running) {
      await verifyClaim($, 'push-on-running-recipe',
        'push succeeded while recipe was running — claim may be stale',
        ['push ' + e.tool + ' recipe ' + (sessionRecipes.get(String(e.session_id ?? '')) ?? '?')])
    }

    // 12. RECIPE SNAPSHOT HISTORY — after every successful push, pull the
    //     fresh DSL from the matching server and commit it to a local git
    //     history repo. "What changed in recipe X" becomes `git log/diff`,
    //     closing the ledger's biggest blind spot (it knows THAT, not WHAT).
    if (isPush && result && !result.deny && !result.isError) {
      trackSession(e, result)
      const rid = sessionRecipes.get(String(e.session_id ?? ''))
      if (rid != null) {
        try {
          const serverName = isProd ? 'workato-airo-mcp-prod' : 'workato-airo-mcp-server'
          const fresh = await $.mcp.call(serverName, 'recipe_get', { recipe_id: rid })
          const blob = JSON.stringify(fresh?.content ?? fresh ?? '')
          if (blob.length > 100) {
            const stamp = new Date().toISOString().replace(/[:.]/g, '-')
            const dir = RECIPE_HISTORY + '/' + (isProd ? 'prod' : 'dev') + '/' + rid
            const path = dir + '/' + stamp + '.json'
            await $.process.run(['sh', '-c',
              'mkdir -p ' + dir + ' && cat > ' + path + " && cd " + RECIPE_HISTORY +
              ' && git add -A && git commit -q -m "snapshot ' + (isProd ? 'prod' : 'dev') +
              '/' + rid + ' ' + stamp + '" --allow-empty'], { input: blob })
          }
        } catch {
          // Snapshotting must never fail the push — best effort only.
        }
      }
    }

    if (isPush && result && !result.deny && !result.isError && risk) {
      return annotate(
        result,
        risk.error
          ? '\n\n[workato-guardrails] Push risk: ' + risk.error
          : '\n\n[workato-guardrails] Push risk: ' + risk.label + ' (' + risk.score + '/10) — ' + risk.reasons.join('; '),
      )
    }
    return result
  })

  // 2. JIRA STORY-POINTS ENFORCER
  on('tool.call', { tool: 'mcp__atlassian__createJiraIssue' }, async ($, e, next) => {
    const project = String(e.projectKey ?? '').toUpperCase()
    if (POINTS_BLOCKED_PROJECTS.indexOf(project) !== -1) {
      // Field is not on these projects' screens — creation without points is correct.
      return next(e)
    }
    let fields = e.additional_fields
    if (fields == null) fields = ''
    if (typeof fields !== 'string') {
      try {
        fields = JSON.stringify(fields)
      } catch {
        fields = String(fields)
      }
    }
    if (fields.indexOf('customfield_10057') === -1) {
      return {
        deny:
          'BLOCKED by workato-guardrails: every Jira ticket MUST get a Story Points ' +
          'estimate at creation time (customfield_10057, number). ' + POINT_SCALE +
          ' Re-issue createJiraIssue with additional_fields including ' +
          '{"customfield_10057": <points>}.',
      }
    }
    return next(e)
  })

  // 3. WORKATO URL LINKER (post-tool annotation)
  on('tool.call', { tool: WORKATO_TOOLS }, async ($, e, next) => {
    const result = await next(e)
    if (!result || result.deny || result.isError) return result
    const text =
      (typeof result === 'string' ? result : '') ||
      (typeof result?.result === 'string' ? result.result : '') ||
      JSON.stringify(result?.result ?? result?.content ?? '')
    if (!text || hasWorkatoUrl(text)) return result
    // JSON-encoded results carry literal "\n" sequences; normalize so
    // "…\\nrecipe_id: 749…" is scannable the same as a plain newline.
    const flat = text.replace(/\\n/g, ' ')
    const links = extractLinks(flat)
    if (links.length === 0) return result
    return annotate(result, '\n\n[workato-guardrails] Asset URLs:\n' + links.map((u) => '- ' + u).join('\n'))
  })

  // 7. DATAPILL TRAP WARNING — recipe_builder_pull's DSL export can render a
  //    mapped datapill as its resolved sample value (a mapped employee.name
  //    pill shows as the literal "Logan McNeil"), so a correct mapping looks
  //    hardcoded. Warn at the exact moment of exposure.
  on('tool.call', { tool: /^mcp__workato-airo-mcp-(server|prod)__recipe_builder_pull$/ }, async ($, e, next) => {
    const result = await next(e)
    if (!result || result.deny || result.isError) return result
    return annotate(
      result,
      '\n\n⚠️ [workato-guardrails] DO NOT TRUST this DSL export for field mappings: ' +
        'recipe_builder_pull can render a mapped datapill as its resolved SAMPLE VALUE ' +
        '(a mapped employee.name pill shows as a literal name), so a correctly-mapped ' +
        'field can look hardcoded. Verify mappings against the recipe UI or a real ' +
        'job_get trace before concluding a field is unmapped or hardcoded.',
    )
  })

  // 8. WRITEBACK VERIFICATION NUDGE — after any Jira/Confluence write, remind
  //    Claude to re-read the artifact: Atlassian MCP writes can return success
  //    while markdown renders wrong (# as H1, double-escaped description).
  on('tool.call', { tool: /^mcp__atlassian__(createJiraIssue|editJiraIssue|addCommentToJiraIssue|transitionJiraIssue|createIssueLink|createConfluencePage|updateConfluencePage|createConfluenceFooterComment|createConfluenceInlineComment)$/ }, async ($, e, next) => {
    const result = await next(e)
    if (!result || result.deny || result.isError) return result
    const isConfluence = e.tool.indexOf('Confluence') !== -1
    return annotate(
      result,
      '\n\n[workato-guardrails] Write completed. Before reporting it done, re-read it back ' +
        '(' +
        (isConfluence ? 'getConfluencePage' : 'getJiraIssue') +
        ') to confirm the formatting rendered as intended — Atlassian MCP writes can ' +
        'succeed while the markup renders wrong.',
    )
  })

  // 5. JIRA-STANDARDS PROMPT INJECTION + ticket tracking.
  //    The last ticket key mentioned in a prompt becomes the session's current
  //    ticket; build-ledger entries carry it for traceability.
  let currentTicket = null
  on('prompt.submit', async ($, e, next) => {
    const tk = e.text.match(TICKET_KEY)
    if (tk) currentTicket = tk[1]
    if (!isJiraWritePrompt(e.text)) return next(e)
    const body = '--- [workato-guardrails] jira-story-standards govern this request ---\n' +
      (standards ?? STANDARDS_FALLBACK)
    return next({ ...e, context: [...(e.context ?? []), body] })
  })

  // 10. BUILD LEDGER — every successful AIRO mutation, recorded with session,
  //     asset, ticket context, and server (dev/prod). This is the multi-agent
  //     answer to "what was edited": the ledger is shared state.
  on('tool.call', { tool: AIRO_MUTATION }, async ($, e, next) => {
    const result = await next(e)
    if (!result || result.deny || result.isError) return result
    const sid = String(e.session_id ?? '')
    const entry = {
      kind: 'airo-mutation',
      tool: e.tool.replace(/^mcp__workato-airo-mcp-(server|prod)__/, ''),
      server: e.tool.indexOf('mcp-prod') !== -1 ? 'prod' : 'dev',
      session: sid || null,
      recipe_id: e.recipe_id ?? (sid ? sessionRecipes.get(sid) : null) ?? null,
      asset_name: e.name ?? null,
      folder_id: e.folder_id ?? null,
      ticket: currentTicket,
    }
    mutationCount += 1
    await ledgerAppend($, entry)
    $.ui.invalidate('ui.render')
    return result
  })

  // BYPASS flag path: explicit, time-boxed prod-gate bypass (bin/prod-bypass).
  // Inline at each site ($ may not be passed to helpers — mod validator).
  const BYPASS_PATH = '/Users/joshcramoy/.claude/workato-audit/prod-bypass.json'

  // 13. PROD-WRITE CONFIRM GATE — EVERY surface, not just AIRO MCP.
  //     The prod AIRO server is already gated (permissions.ask + hook 1).
  //     This closes the other doors into production: the Workato CLI
  //     (workato-prod), wt (wt-prod / WORKATO_PROFILE=josh-prod), raw HTTP
  //     carrying the prod credential, and Orca browser actions aimed at prod.
  //     Reads pass through untouched; only mutations hold for confirmation,
  //     and a dismissed dialog fails closed (deny).
  const PROD_WORKSPACE = '3535598'
  // Stable identifier embedded in the prod JWT (not the secret itself) — lets
  // the gate recognise the prod credential when it appears in a raw command.
  const PROD_TOKEN_MARK = 'd42cc899-694d-474e-80ef-c4eb3d43cf9f'
  const PROD_URL_RE = new RegExp(
    '(environments?|workspaces?)/' + PROD_WORKSPACE + '\\b|env=Production|environment_name=Production')
  const HTTP_WRITE_RE = /(-X\s*|--request[= ])(POST|PUT|PATCH|DELETE)\b|(^|\s)(-d|--data|--data-raw|--data-binary)\b/i
  const ORCA_WRITE_RE = /\b(click|fill|type|press|submit|eval|run)\b/i
  const WT_READ_OPS = /^(list|get|show|health|health-scan|versions|job-counts|export)$/i
  const WT_WRITE_OPS =
    /^(start|stop|delete|copy|force-run|poll-now|reset-trigger|connect|repeat|cancel|create|update|add-row|upsert|import|enable|POST|PUT|PATCH|DELETE)$/i
  const WORKATO_READ_SUBS = /^(pull|workspace|assets|guide|profiles|init)$/
  const WORKATO_WRITE_OPS = /^(create|update|delete|upsert|set|enable|disable|add|remove|start|stop|push)$/i

  // Which prod surface does this command target? null = not prod.
  function prodSurface(cmd) {
    if (/\bwt-prod\b/.test(cmd)) return 'wt-prod'
    if (/\bworkato-prod\b/.test(cmd)) return 'workato-prod'
    if (/WORKATO_PROFILE=["']?josh-prod/.test(cmd)) return 'wt (WORKATO_PROFILE)'
    if (/\b(wt|workato)\b[^\n]*--profile[= ]+["']?josh-prod/.test(cmd)) return 'cli (--profile josh-prod)'
    if (cmd.includes(PROD_TOKEN_MARK)) return 'raw http (prod credential)'
    if (/\borca\b/i.test(cmd) && PROD_URL_RE.test(cmd)) return 'orca browser (prod url)'
    return null
  }

  function splitArgs(rest) {
    return rest
      .replace(/--profile[= ]+\S+/g, '')
      .replace(/--(raw|restart-recipes|force)\b/g, '')
      .trim()
      .split(/\s+/)
      .filter(Boolean)
  }

  function wtIsWrite(cmd) {
    if (HTTP_WRITE_RE.test(cmd)) return true
    // Longest wrapper name first, or `\bwt\b` would match inside `wt-prod`
    // and leave "-prod" as the parsed group.
    const m = cmd.match(/\b(?:wt-prod|wt)\b([^\n]*)/)
    if (!m) return false
    const parts = splitArgs(m[1])
    const group = parts[0]
    const op = parts[1]
    if (!group) return false
    if (group === 'api') return /^(POST|PUT|PATCH|DELETE)$/i.test(op || '')
    if (group === 'discover' || group === 'folders' || group === 'projects') return false
    if (op && WT_READ_OPS.test(op)) return false
    return WT_WRITE_OPS.test(op || '')
  }

  function workatoIsWrite(cmd) {
    const m = cmd.match(/\b(?:workato-prod|workato)\b([^\n]*)/)
    if (!m) return false
    const parts = splitArgs(m[1])
    const sub = parts[0]
    const op = parts[1]
    if (!sub) return false
    if (WORKATO_READ_SUBS.test(sub)) return false
    if (sub === 'push') return true
    if (sub === 'recipes') return /^(start|stop)$/i.test(op || '')
    return WORKATO_WRITE_OPS.test(op || '')
  }

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const cmd = String(e.command ?? '')
    const surface = prodSurface(cmd)
    if (surface) {
      let bypassOn = false
      try {
        const bf = await $.fs.read(BYPASS_PATH)
        const bj = JSON.parse(String(bf.text ?? bf))
        bypassOn = typeof bj.until === 'number' && bj.until * 1000 > Date.now()
      } catch { bypassOn = false }
      if (bypassOn) {
        await $.process.run(['sh', '-c', 'cat >> ' + AUDIT_FILE], {
          stdin: new Date().toISOString() + ' PROD-WRITE-BYPASSED(' + surface + ') ' + cmd.slice(0, 200) + '\n',
        })
        $.ui.log('PROD WRITE (bypassed) · ' + surface + ' · ' + cmd.slice(0, 80))
        return next(e)
      }
      const isWrite =
        surface === 'workato-prod'
          ? workatoIsWrite(cmd)
          : surface.startsWith('wt')
            ? wtIsWrite(cmd)
            : surface.startsWith('orca')
              ? ORCA_WRITE_RE.test(cmd)
              : HTTP_WRITE_RE.test(cmd)
      if (isWrite) {
        let answer = 'Cancel'
        try {
          answer = await $.ui.ask(
            '⚠️  PROD WRITE via ' + surface + ' — workspace ' + PROD_WORKSPACE +
              ' (Environment Production).\n\n' + cmd.slice(0, 400) +
              '\n\nThis modifies LIVE PRODUCTION Workato. Proceed?',
            ['Proceed', 'Cancel'],
          )
        } catch {
          answer = 'Cancel' // fail closed
        }
        if (answer !== 'Proceed') {
          return {
            deny:
              'workato-guardrails prod-write gate: BLOCKED ' + surface +
              ' write to PRODUCTION (workspace ' + PROD_WORKSPACE + '). ' +
              'Josh must confirm explicitly. Command: ' + cmd.slice(0, 200),
          }
        }
        prodWrites += 1
        await $.store.set('prodWrites', prodWrites)
        await $.process.run(['sh', '-c', 'mkdir -p ' + AUDIT_DIR + ' && cat >> ' + AUDIT_FILE], {
          stdin: new Date().toISOString() + ' PROD-WRITE(' + surface + ') ' + cmd.slice(0, 200) + '\n',
        })
        $.ui.log('PROD WRITE · ' + surface + ' · ' + cmd.slice(0, 80))
      }
    }
    return next(e)
  })

  // 14. REMOTE-IDENTITY GUARD — the 2026-10-07 incident: org work pushed to
  //     a personal remote because the origin was misconfigured. On any Bash
  //     `git push`, resolve where it actually points and hold non-org
  //     destinations for an explicit confirm. Unresolvable = allow (never
  //     block unrelated commands); URL-in-command mismatch = ask, fail-closed.
  const ORG_REMOTE = /github\.com[/:]Workato-All\//i

  function pushTargets(cmd) {
    const urls = []
    const urlRe = /https?:\/\/[^\s'"<>]*github\.com[/:][\w.-]+\/[\w.-]+|git@github\.com:[\w.-]+\/[\w.-]+/gi
    let m
    while ((m = urlRe.exec(cmd)) !== null) urls.push(m[0])
    return urls
  }

  async function originIn(cmd, e) {
    // best-effort cwd: the event may carry it, else fall back to process cwd
    const cwdRaw = e.cwd || e.workingDir
    if (!cwdRaw) return null   // no cwd in the event: skip the origin check, never throw
    const cwd = String(cwdRaw)
    try {
      const res = await $.process.run(
        ['sh', '-c', 'git -C "' + cwd + '" remote get-url origin 2>/dev/null'])
      return String((res && (res.stdout ?? res.result ?? res)) || '').trim() || null
    } catch {
      return null
    }
  }

  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const cmd = String(e.command ?? '')
    if (/\bgit\b[^\n]*\bpush\b/.test(cmd) && !/\b(--dry-run|--delete)\b/.test(cmd)) {
      // path 1: a literal non-org URL inside the command
      const urls = pushTargets(cmd)
      const badUrl = urls.find((u) => !ORG_REMOTE.test(u))
      if (badUrl) {
        let answer = 'Cancel'
        try {
          answer = await $.ui.ask(
            '⚠️  git push targets a NON-ORG remote:\n  ' + badUrl +
            '\nOrg work in a personal repo is how work gets lost. Push anyway?',
            ['Push anyway', 'Cancel'])
        } catch { answer = 'Cancel' }
        if (answer !== 'Push anyway') {
          return { deny: 'workato-guardrails remote-identity guard: push to non-org remote "' +
            badUrl + '" not confirmed. Fix the remote (git remote set-url origin …) or confirm explicitly.' }
        }
        return next(e)
      }
      // path 2: bare push — check the origin remote of the resolved cwd
      const origin = await originIn(cmd, e)
      if (origin && !ORG_REMOTE.test(origin)) {
        let answer = 'Cancel'
        try {
          answer = await $.ui.ask(
            '⚠️  this repo\'s origin is NON-ORG:\n  ' + origin +
            '\nPushing org work here? Confirm:',
            ['Push anyway', 'Cancel'])
        } catch { answer = 'Cancel' }
        if (answer !== 'Push anyway') {
          return { deny: 'workato-guardrails remote-identity guard: origin "' +
            origin + '" is not an org remote; push not confirmed.' }
        }
      }
    }
    return next(e)
  })

  // 11. CLI / ORCA LEDGER — Workato CLI and Orca browser automation bypass
  //     AIRO, so they ledger via Bash command sniffing. A successful CLI
  //     START doubles as opportunistic verification of the silent-noop
  //     claim: read the recipe back and see if it's actually running.
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    const result = await next(e)
    if (!result || result.deny || result.isError) return result
    const cmd = String(e.command ?? '')
    const kind = /\borca\b/.test(cmd)
      ? 'orca-browser'
      : /\bwt(-prod)?\s|workato(-prod)? (push|pull|start|stop)/.test(cmd)
        ? 'workato-cli'
        : null
    if (kind) {
      const ids = cmd.match(/\b\d{7,9}\b/g) ?? []
      await ledgerAppend($, {
        kind: kind,
        command: cmd.slice(0, 200),
        recipe_id: ids.length ? Number(ids[0]) : null,
        ticket: currentTicket,
      })
      // Opportunistic verification: did that start actually take?
      if (/\b(wt|workato)\s+start\b/.test(cmd) && ids.length) {
        try {
          const fresh = await $.mcp.call('workato-airo-mcp-server', 'recipe_get', { recipe_id: Number(ids[0]) })
          const blob = JSON.stringify(fresh?.content ?? fresh ?? '')
          const actuallyRunning = /"running":\s*true|"Running":\s*True|Running\*\*: True/.test(blob)
          await verifyClaim($, 'cli-start-silent-noop',
            actuallyRunning
              ? 'CLI start took effect (recipe_get shows running) — claim refuted this time'
              : 'CLI start did NOT take effect (recipe_get shows not running) — claim confirmed',
            ['Bash: ' + cmd.slice(0, 120)])
        } catch {
          // Read-back unavailable — skip verification, never fail the command.
        }
      }
    }
    return result
  })

  // /builds — ledger summary for today / week / all
  on('command.run', { command: 'builds' }, async ($, e) => {
    let text = ''
    try {
      const file = await $.fs.read(BUILD_LEDGER.replace('$HOME', process.env.HOME))
      text = file.text ?? file
    } catch {
      return { text: 'Build ledger is empty — nothing recorded yet.' }
    }
    const args = String(e.args ?? 'today').trim()
    const now = Date.now()
    const cutoff =
      args === 'all' ? 0 : args === 'week' ? now - 7 * 86400000 : new Date().setHours(0, 0, 0, 0)
    const byRecipe = new Map()
    let n = 0
    for (const line of text.split('\n')) {
      if (!line.trim()) continue
      let ev
      try { ev = JSON.parse(line) } catch { continue }
      if (Date.parse(ev.ts) < cutoff) continue
      n += 1
      const key = ev.recipe_id ? 'recipe ' + ev.recipe_id : (ev.tool ?? ev.kind)
      const cur = byRecipe.get(key) ?? { count: 0, server: ev.server ?? '-', ticket: ev.ticket ?? '-', kinds: new Set() }
      cur.count += 1
      cur.kinds.add(ev.tool ?? ev.kind)
      if (ev.ticket) cur.ticket = ev.ticket
      byRecipe.set(key, cur)
    }
    if (n === 0) return { text: 'No build events in window "' + args + '".' }
    const lines = ['Build ledger — ' + args + ' (' + n + ' events):']
    for (const [key, v] of byRecipe) {
      lines.push('- ' + key + ' [' + v.server + '] ×' + v.count + ' (' + [...v.kinds].join(', ') + ')' +
        (v.ticket !== '-' ? ' — ' + v.ticket : ''))
    }
    return { text: lines.join('\n') }
  })

  // /cockpit — command-center pane: Session tab (live counters) + Ledger tab
  // (tail of the build ledger). Redraws via $.ui.invalidate on mutation.
  let cockpitTab = 'session'
  let mutationCount = 0

  on('command.run', { command: 'cockpit' }, async ($, e) => {
    // /cockpit full (or /cockpit dash): regenerate the full-page dashboard and
    // open it in the browser. Bare /cockpit keeps the terminal pane.
    const wantsFull = /\b(full|dash|page)\b/i.test(String(e?.args ?? ''))
    if (wantsFull) {
      const out = await $.process.run(
        ['python3', process.env.HOME + '/.claude/knowledge/scripts/brain-dashboard.py'])
      const page = String((out && (out.stdout ?? out.result ?? out)) || '').trim()
      await $.process.run(['open', page || process.env.HOME + '/.claude/knowledge/dashboard.html'])
      return { text: 'Dashboard: ' + page }
    }
    try {
      await $.ui.open({ id: 'wg-cockpit', title: 'Workato cockpit', focus: true, closeOnEscape: true })
      return {} // pane opened; the ui.render hook draws it
    } catch {
      // No drawing surface here (headless run, VS Code panel): fall back to
      // the same summary as the Session tab, as a transcript reply.
      return {
        text:
          'Workato cockpit (text fallback — no pane surface here):\n' +
          'prod writes: ' + prodWrites + ' · mutations: ' + mutationCount +
          ' · ticket: ' + (currentTicket ?? 'none yet') +
          ' · /builds for the ledger view',
      }
    }
  })

  on('ui.render', { component: 'Pane' }, async ($, e, next) => {
    if (e.requestId !== 'wg-cockpit') return next(e)
    const { Box, Text, Button } = $.ui.resolve(e)
    const redraw = () => $.ui.invalidate('ui.render')
    const tabButton = (name, label, hotkey) =>
      Button({
        key: 'tab-' + name,
        label: label,
        hotkey: hotkey,
        plain: true,
        dimColor: cockpitTab !== name,
        onPress: () => {
          cockpitTab = name
          redraw()
        },
      })

    let body
    if (cockpitTab === 'session') {
      body = Text({
        children: [
          'prod writes: ' + prodWrites + '   mutations: ' + mutationCount +
            '   ticket: ' + (currentTicket ?? 'none yet') +
            '\nhooks active: 12   audit: ~/.claude/workato-audit/prod-writes.log',
        ],
      })
    } else {
      let tail = '(ledger empty)'
      try {
        const file = await $.fs.read(BUILD_LEDGER.replace('$HOME', process.env.HOME))
        const lines = String(file.text ?? file).split('\n').filter((l) => l.trim())
        tail = lines.slice(-8).map((l) => {
          try {
            const ev = JSON.parse(l)
            return ev.ts.slice(5, 16) + ' ' + (ev.tool ?? ev.kind) +
              (ev.recipe_id ? ' #' + ev.recipe_id : '') +
              (ev.ticket ? ' [' + ev.ticket + ']' : '')
          } catch {
            return l.slice(0, 60)
          }
        }).join('\n')
      } catch {
        tail = '(ledger empty)'
      }
      body = Box({
        flexDirection: 'column',
        children: [Text({ children: ['build ledger (last 8):'] }), Text({ children: [tail] })],
      })
    }

    return Box({
      flexDirection: 'column',
      children: [
        Box({
          flexDirection: 'row',
          columnGap: 3,
          children: [tabButton('session', 'Session', '1'), tabButton('ledger', 'Ledger', '2')],
        }),
        Text({ children: [' '] }),
        body,
      ],
    })
  })

  // /snapdiff — recipe snapshot history: recent snapshots + last real diff.
  // Named snapdiff (not diff): /diff belongs to the engine's built-in
  // cc-plugin-diff panel; a second registration of a taken name is refused.
  on('command.run', { command: 'snapdiff' }, async ($, e) => {
    const rid = (String(e.args ?? '').match(/\d{6,9}/g) ?? [])[0]
    if (!rid) return { text: 'Usage: /snapdiff <recipe_id>' }
    const find = async (env) => {
      try {
        const r = await $.process.run(['sh', '-c',
          'ls ' + RECIPE_HISTORY + '/' + env + '/' + rid + ' 2>/dev/null | tail -3'])
        return r.stdout?.trim()
      } catch {
        return ''
      }
    }
    const devSnaps = await find('dev')
    const prodSnaps = await find('prod')
    if (!devSnaps && !prodSnaps) {
      return { text: 'No snapshots for recipe ' + rid + ' yet — snapshots start on the next push.' }
    }
    let diffOut = ''
    try {
      const r = await $.process.run(['sh', '-c',
        'cd ' + RECIPE_HISTORY + ' && git log --oneline -5 -- "*' + rid + '"'])
      diffOut = r.stdout?.trim() ?? ''
    } catch {
      diffOut = '(git log unavailable)'
    }
    return {
      text:
        'Snapshot history for recipe ' + rid + ':\n' +
        (devSnaps ? 'dev: ' + devSnaps.split('\n').join(', ') + '\n' : '') +
        (prodSnaps ? 'prod: ' + prodSnaps.split('\n').join(', ') + '\n' : '') +
        'commits:\n' + diffOut,
    }
  })

  // /promoted — mark recipes promoted (comma/space separated IDs)
  on('command.run', { command: 'promoted' }, async ($, e) => {
    const ids = (String(e.args ?? '').match(/\d{6,9}/g) ?? []).map(Number)
    if (ids.length === 0) return { text: 'Usage: /promoted <recipe_id> [recipe_id...]' }
    for (const id of ids) {
      await ledgerAppend($, { kind: 'promotion', recipe_id: id, ticket: currentTicket })
    }
    return { text: 'Marked promoted: ' + ids.join(', ') + ' (ledger updated)' }
  })

  // /promotion-ready — dev mutations on recipes with no promotion marker since
  on('command.run', { command: 'promotion-ready' }, async ($) => {
    let text = ''
    try {
      const file = await $.fs.read(BUILD_LEDGER.replace('$HOME', process.env.HOME))
      text = file.text ?? file
    } catch {
      return { text: 'Build ledger is empty — nothing recorded yet.' }
    }
    const lastEdit = new Map()   // recipe_id -> {ts, tool}
    const promoted = new Map()   // recipe_id -> ts
    for (const line of text.split('\n')) {
      if (!line.trim()) continue
      let ev
      try { ev = JSON.parse(line) } catch { continue }
      if (ev.kind === 'promotion' && ev.recipe_id) promoted.set(ev.recipe_id, ev.ts)
      if ((ev.kind === 'airo-mutation' || ev.kind === 'workato-cli' || ev.kind === 'orca-browser') &&
          ev.server !== 'prod' && ev.recipe_id) {
        lastEdit.set(ev.recipe_id, { ts: ev.ts, tool: ev.tool ?? ev.kind, ticket: ev.ticket ?? null })
      }
    }
    const ready = []
    for (const [id, v] of lastEdit) {
      const p = promoted.get(id)
      if (!p || Date.parse(p) < Date.parse(v.ts)) ready.push({ id, ...v })
    }
    if (ready.length === 0) return { text: 'Promotion-ready list is empty.' }
    ready.sort((a, b) => Date.parse(b.ts) - Date.parse(a.ts))
    const lines = ['Promotion-ready (dev edits newer than last promotion):']
    for (const r of ready) {
      lines.push('- https://app.workato.com/recipes/' + r.id + ' — last edit ' + r.ts.slice(0, 10) +
        ' via ' + r.tool + (r.ticket ? ' — ' + r.ticket : ''))
    }
    return { text: lines.join('\n') }
  })

  // 6. STATUS BAND above the prompt (keeps other mods' band content)
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const prior = await next(e)
    const { Box, Text } = $.ui.resolve(e)
    let bypass = false
    try {
      const bf3 = await $.fs.read(BYPASS_PATH)
      const bj3 = JSON.parse(String(bf3.text ?? bf3))
      bypass = typeof bj3.until === 'number' && bj3.until * 1000 > Date.now()
    } catch { bypass = false }
    const label =
      (bypass ? '⚠️ PROD BYPASS ACTIVE · ' : '') +
      '🛡 guardrails · prod writes this session: ' + prodWrites +
      ' · /guardrails for status'
    return Box({
      flexDirection: 'row',
      columnGap: 2,
      children: [Text({ children: [label] }), ...(prior ? [prior] : [])],
    })
  })
}
