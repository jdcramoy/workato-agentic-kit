// Replayable live-evidence driver for hook 15 (push identity guard).
// The claude plugin test sandbox serves no $.mcp noun, so the lookup-backed
// warn path can't be exercised there. This driver loads the REAL register.js,
// fires the REAL tool.call hook chain, and feeds REAL captured MCP payloads
// (fixtures: recipe_get_A.json, recipe_list_folder.json — captured 2026-10-20
// from a live duplicate-name pair, recipes 83197137/83197138 in folder
// 35835951). Run: node tests/push-identity-driver.mjs
// Expect: CASE 1 WARNED (names both ids, no deny), CASE 2 cached (one
// recipe_list), CASE 3 unique name no warning, CASE 4 mcp down push passes.
import { register } from './register.mjs'
import { readFileSync } from 'node:fs'

const getA = JSON.parse(readFileSync('/tmp/pi-guard/recipe_get_A.json', 'utf8'))
const listing = JSON.parse(readFileSync('/tmp/pi-guard/recipe_list_folder.json', 'utf8'))

// ---- mock engine: same hook contract the real engine serves ---------------
const hooks = []
const on = (event, matcherOrHook, maybeHook) => {
  const matcher = typeof matcherOrHook === 'function' ? null : matcherOrHook
  const fn = maybeHook ?? matcherOrHook
  hooks.push({ event, matcher, fn })
}
const mcpCalls = []
const $ = {
  mcp: { call: async (server, tool, args) => {
    mcpCalls.push(server + '/' + tool + (args.recipe_id ? ':' + args.recipe_id : '') + (args.folder_id ? ':f' + args.folder_id : ''))
    if (tool === 'recipe_get' && args.recipe_id === 83197137) return { content: getA }
    if (tool === 'recipe_list') return { content: listing }
    if (tool === 'search_recipe_dependencies') return { content: [{ type: 'text', text: JSON.stringify({ result: { results: [] } }) }] }
    return { content: [] }
  }},
  fs: { read: async (p) => { if (String(p).includes('prod-bypass.json')) return { text: '{"until":0}' }; throw new Error('no file ' + p) } },
  process: { run: async () => ({ stdout: '' }) },
  store: { get: async () => 0, set: async () => {} },
  ui: { ask: async () => 'Cancel', log: () => {}, invalidate: () => {} },
  command: { register: async () => {} },
}

register(on)

// run every tool.call hook whose matcher matches, chained like the engine does
async function fire(tool, e) {
  const chain = hooks.filter((h) => h.event === 'tool.call' &&
    (!h.matcher?.tool || (h.matcher.tool instanceof RegExp ? h.matcher.tool.test(tool) : h.matcher.tool === tool)))
  const run = (i) => async (e2) => i >= chain.length ? { result: 'Recipe pushed' } : chain[i].fn($, e2, run(i + 1))
  return run(0)(e)
}

// ---- CASE 1 (positive, real data): push stopped twin A while B runs -------
const case1 = await fire('mcp__workato-airo-mcp-server__recipe_builder_push', { tool: 'mcp__workato-airo-mcp-server__recipe_builder_push', session_id: 'driver-1', recipe_id: 83197137 })
const t1 = typeof case1.result === 'string' ? case1.result : JSON.stringify(case1.result)
console.log('CASE 1 (same-name live twin) ->', t1.includes('PUSH IDENTITY WARNING') ? 'WARNED' : 'NO WARNING')
console.log('  names both ids:', t1.includes('recipes/83197137') && t1.includes('recipes/83197138') ? 'YES' : 'NO')
console.log('  never blocks:', !case1.deny ? 'YES (no deny)' : 'NO — DENIED: ' + case1.deny)
console.log('  excerpt:', t1.split('PUSH IDENTITY WARNING')[1]?.slice(0, 400))

// ---- CASE 2 (cache): same push again -> no second recipe_list -------------
const listCallsBefore = mcpCalls.filter((c) => c.includes('recipe_list')).length
await fire('mcp__workato-airo-mcp-server__recipe_builder_push', { tool: 'mcp__workato-airo-mcp-server__recipe_builder_push', session_id: 'driver-1', recipe_id: 83197137 })
const listCallsAfter = mcpCalls.filter((c) => c.includes('recipe_list')).length
console.log('CASE 2 (5-min cache) -> recipe_list calls: before=' + listCallsBefore, 'after-second-push=' + listCallsAfter,
  listCallsAfter === listCallsBefore ? '(CACHED — one call)' : '(RE-FETCHED — cache broken)')

// ---- CASE 3 (negative, real data): unique-name push -> no warn ------------
mcpCalls.length = 0
const getUnique = [{ type: 'text', text: 'Recipe retrieved successfully\n\n### Recipe: Copy of Test create form [TEST] (ID: 83113573)\n\n**Recipe URL**: https://app.workato.com/recipes/83113573\n\n**Folder ID**: 35835951\n\n**Project ID**: 18276750\n\n**Running**: False\n' }]
$.mcp.call = async (server, tool, args) => {
  mcpCalls.push(server + '/' + tool)
  if (tool === 'recipe_get' && args.recipe_id === 83113573) return { content: getUnique }
  if (tool === 'recipe_list') return { content: listing }
  if (tool === 'search_recipe_dependencies') return { content: [{ type: 'text', text: JSON.stringify({ result: { results: [] } }) }] }
  return { content: [] }
}
hooks.length = 0
register(on)
const case3b = await (async () => {
  const chain = hooks.filter((h) => h.event === 'tool.call' &&
    (!h.matcher?.tool || (h.matcher.tool instanceof RegExp ? h.matcher.tool.test('mcp__workato-airo-mcp-server__recipe_builder_push') : false)))
  const run = (i) => async (e2) => i >= chain.length ? { result: 'Recipe pushed' } : chain[i].fn($, e2, run(i + 1))
  return run(0)({ tool: 'mcp__workato-airo-mcp-server__recipe_builder_push', session_id: 'driver-3', recipe_id: 83113573 })
})()
const t3 = typeof case3b.result === 'string' ? case3b.result : JSON.stringify(case3b.result)
console.log('CASE 3 (unique name) ->', t3.includes('PUSH IDENTITY WARNING') ? 'WARNED (BAD!)' : 'NO WARNING (correct)')

// ---- CASE 4 (degrade): mcp unavailable -> push passes through -------------
hooks.length = 0
const failing$ = { ...$, mcp: { call: async () => { throw new Error('mcp down') } }, fs: $.fs, process: $.process, store: $.store, ui: $.ui, command: $.command }
register(on)
const chain = hooks.filter((h) => h.event === 'tool.call' &&
  (!h.matcher?.tool || (h.matcher.tool instanceof RegExp ? h.matcher.tool.test('mcp__workato-airo-mcp-server__recipe_builder_push') : false)))
const run = (i) => async (e2) => i >= chain.length ? { result: 'Recipe pushed' } : chain[i].fn(failing$, e2, run(i + 1))
const case4 = await run(0)({ tool: 'mcp__workato-airo-mcp-server__recipe_builder_push', session_id: 'driver-4', recipe_id: 83197137 })
const t4 = typeof case4.result === 'string' ? case4.result : JSON.stringify(case4.result)
console.log('CASE 4 (mcp down) -> push passes:', !case4.deny && t4.includes('Recipe pushed') ? 'YES' : 'FAIL', '| no warning:', !t4.includes('PUSH IDENTITY WARNING') ? 'YES' : 'NO')
