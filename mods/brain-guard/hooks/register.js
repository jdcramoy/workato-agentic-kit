// brain-guard — the gardener's write-time nervous system.
//   1. LINTER: memory/knowledge writes get checked at the moment of writing —
//      relative dates without absolute anchors, memory files missing
//      frontmatter/type, knowledge writes with no INDEX.md touch this session.
//      Violations nudge (annotated result + transcript line); they never block.
//   2. TELEMETRY: Skill invocations, knowledge/memory reads and writes, and
//      scheduled-task/gardener events append one JSON line to
//      ~/.claude/knowledge/garden-reports/usage-ledger.jsonl — the evidence
//      base the gardener uses to judge what knowledge is load-bearing.

const KNOWLEDGE = '/Users/YOUR-USER/.claude/knowledge/'
const LEDGER_DIR = '$HOME/.claude/knowledge/garden-reports'
const LEDGER = LEDGER_DIR + '/usage-ledger.jsonl'

const INDEX_MD = KNOWLEDGE + 'INDEX.md'
const GARDEN_DIR = KNOWLEDGE + 'garden-reports/'

const RELATIVE_DATE =
  /\b(yesterday|tomorrow|tonight|just now|earlier today|last (week|month|night)|this (week|month|morning|afternoon|evening)|next (week|month)|the other day|recently)\b/i
const ABS_DATE = /\b20\d\d-\d\d-\d\d\b|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2}, 20\d\d\b/

const FRONTMATTER = /^---[\s\S]*?name:[\s\S]*?description:[\s\S]*?---/
const TYPE_TAG = /type:\s*(user|feedback|project|reference)\b/

function isMemoryPath(p) {
  return p.indexOf('/memory/') !== -1 && p.endsWith('.md') && p.indexOf(GARDEN_DIR) === -1
}

function isKnowledgePath(p) {
  return p.indexOf(KNOWLEDGE) === 0 && p.endsWith('.md') && p.indexOf(GARDEN_DIR) === -1
}

// Append the lint nudge to whatever result shape the tool produced.
function nudge(result, block) {
  if (typeof result === 'string') return result + block
  if (result && typeof result === 'object') {
    if (typeof result.result === 'string') {
      return { ...result, result: result.result + block }
    }
    if (Array.isArray(result.content)) {
      return { ...result, content: [...result.content, { type: 'text', text: block }] }
    }
  }
  return result
}

// Top-level declaration: static analysis only allows passing `$` to
// functions declared at the top level of the module.
function logEvent($, kind, target) {
  const line =
    JSON.stringify({ ts: new Date().toISOString(), kind: kind, target: target }) + '\n'
  // $.fs.write overwrites; append via shell like workato-guardrails' audit log.
  return $.process
    .run(['sh', '-c', 'mkdir -p ' + LEDGER_DIR + ' && cat >> ' + LEDGER], { stdin: line })
    .catch(() => {})
}

// ---- registration ---------------------------------------------------------

export function register(on) {
  // Which knowledge paths this session has touched (for the INDEX co-write check).
  const touched = new Set()

  // TELEMETRY: skill loads
  on('tool.call', { tool: 'Skill' }, async ($, e, next) => {
    const result = await next(e)
    await logEvent($, 'skill', String(e.skill ?? 'unknown'))
    return result
  })

  // TELEMETRY: knowledge/memory reads + the INDEX router itself
  on('tool.call', { tool: 'Read' }, async ($, e, next) => {
    const result = await next(e)
    const path = String(e.file_path ?? '')
    if (path === INDEX_MD) await logEvent($, 'index-read', path)
    else if (isKnowledgePath(path)) await logEvent($, 'knowledge-read', path)
    else if (isMemoryPath(path)) await logEvent($, 'memory-read', path)
    return result
  })

  // TELEMETRY: MCP call economics + failure classes — tool, result byte
  // size, and error classification per mcp__ call. Feeds the gardener's
  // "what costs us the most context" and "which tools fail most" reports.
  on('tool.call', { tool: /^mcp__/ }, async ($, e, next) => {
    const result = await next(e)
    let bytes = 0
    try {
      bytes = JSON.stringify(result?.result ?? result?.content ?? result ?? '').length
    } catch {
      bytes = -1
    }
    let err = null
    if (result && (result.isError || result.deny)) err = 'error'
    else if (result) {
      const blob = typeof result?.result === 'string' ? result.result : ''
      if (/^\s*error[:\s]|"error"|exception|failed/i.test(blob.slice(0, 400))) err = 'error'
    }
    await logEvent($, err ? 'mcp-error' : 'mcp-call', e.tool + ' bytes=' + bytes)
    return result
  })

  // TELEMETRY: turn-level token usage — the cost-per-project rollup feed.
  on('turn.complete', async ($, e, next) => {
    const u = e.usage
    if (u) {
      const parts = []
      if (u.input_tokens != null) parts.push('in=' + u.input_tokens)
      if (u.output_tokens != null) parts.push('out=' + u.output_tokens)
      if (u.cache_read_input_tokens != null) parts.push('cache_read=' + u.cache_read_input_tokens)
      if (u.cache_creation_input_tokens != null) parts.push('cache_write=' + u.cache_creation_input_tokens)
      if (parts.length) await logEvent($, 'turn-usage', parts.join(' ') + (e.isAborted ? ' aborted' : ''))
    }
    return next(e)
  })

  // LINTER + TELEMETRY: writes and edits to memory/knowledge paths
  on('tool.call', { tool: ['Write', 'Edit'] }, async ($, e, next) => {    const path = String(e.file_path ?? '')
    const mem = isMemoryPath(path)
    const know = isKnowledgePath(path)
    if (!mem && !know) return next(e)

    const content = String(e.content ?? e.new_string ?? '')
    const issues = []

    if (mem && e.content != null) {
      // Whole-file memory writes must carry the memory contract.
      if (!FRONTMATTER.test(content)) {
        issues.push('missing memory frontmatter (--- name/description --- block)')
      }
      if (!TYPE_TAG.test(content)) {
        issues.push('missing/invalid metadata type (user | feedback | project | reference)')
      }
    }
    if (RELATIVE_DATE.test(content) && !ABS_DATE.test(content)) {
      issues.push('relative date(s) ("' + (content.match(RELATIVE_DATE)?.[0] ?? '') +
        '") with no absolute date anywhere — convert to YYYY-MM-DD')
    }

    const result = await next(e)
    if (!result || result.deny || result.isError) return result

    // Telemetry first (fire-and-forget semantics; failures never surface)
    await logEvent($, mem ? 'memory-write' : 'knowledge-write', path)

    if (path === INDEX_MD) touched.add(INDEX_MD)
    if (know && path !== INDEX_MD) {
      if (!touched.has(INDEX_MD)) {
        issues.push('INDEX.md not touched this session — does it need a line update?')
      }
    }

    if (issues.length === 0) return result
    $.ui.log('brain-guard lint: ' + issues.length + ' issue(s) in ' + path.split('/').pop())
    return nudge(
      result,
      '\n\n[brain-guard lint] ' + path + '\n' + issues.map((i) => '- ' + i).join('\n') +
        '\nFix these before considering the write done.',
    )
  })

  // /brain-guard — status card
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'brain-guard',
      description: 'Show brain-guard status: linter rules and telemetry ledger',
    })
    return next(e)
  })

  on('command.run', { command: 'brain-guard' }, async () => {
    return {
      text:
        'brain-guard active:\n' +
        '1. Linter on memory/knowledge writes (relative dates, memory frontmatter,' +
        ' INDEX co-write nudge) — annotates, never blocks\n' +
        '2. Usage telemetry → ' + LEDGER + '\n' +
        '   (skill loads, index/knowledge/memory reads, memory/knowledge writes)\n' +
        'The brain-gardener reads the ledger to judge what knowledge is load-bearing.',
    }
  })
}
