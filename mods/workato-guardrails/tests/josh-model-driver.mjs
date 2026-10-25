// Positive-path driver for hook 16 (josh-model session briefing).
// The plugin test sandbox has no $.process noun, so the injection path can't
// be exercised there. This driver loads the REAL register.js (copied to a
// temp .mjs for ESM import), fires the REAL prompt.submit hook chain, and
// mocks $.process.run to return a canned briefing.
// Run: node tests/josh-model-driver.mjs
// Expect: CASE 1 context injected on first prompt; CASE 2 no re-injection on
// second prompt; CASE 3 empty briefing output = no context; CASE 4 subprocess
// throw = prompt passes through (fail open).
import { copyFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const staged = path.join(here, 'register.tmp.mjs')
copyFileSync(path.join(here, '..', 'hooks', 'register.js'), staged)
const { register } = await import(staged)

const hooks = []
const on = (event, matcherOrHook, maybeHook) => {
  const matcher = typeof matcherOrHook === 'function' ? null : matcherOrHook
  hooks.push({ event, matcher, fn: maybeHook ?? matcherOrHook })
}

const BRIEFING = '--- [josh-model] session briefing (task: build | project: workbench) ---\n- pref-001 (global): test rule\n---'

const processCalls = []
const $ = {
  mcp: { call: async () => ({ content: [] }) },
  fs: { read: async () => { throw new Error('no file') } },
  process: { run: async (argv) => {
    processCalls.push(argv.slice(1).join(' '))
    return { stdout: BRIEFING }
  } },
  store: { get: async () => 0, set: async () => {} },
  ui: { ask: async () => 'Cancel', log: () => {}, invalidate: () => {} },
  command: { register: async () => {} },
}

async function firePrompt(text) {
  const chain = hooks.filter((h) => h.event === 'prompt.submit')
  const run = (i) => async (e2) =>
    i >= chain.length ? { answered: e2.text, context: e2.context ?? [] } : chain[i].fn($, e2, run(i + 1))
  return run(0)({ text, cwd: '/Users/YOUR-USER/Documents/workbench', session_id: 'driver-jm' })
}

register(on)

const c1 = await firePrompt('build a recipe')
console.log('CASE 1 (first prompt) -> briefing injected:',
  (c1.context ?? []).some((c) => String(c).includes('[josh-model] session briefing')) ? 'YES' : 'NO')
console.log('  subprocess argv sane:', processCalls[0]?.includes('brief') && processCalls[0]?.includes('build a recipe') ? 'YES' : 'NO')

const before = processCalls.length
const c2 = await firePrompt('a totally different second prompt')
console.log('CASE 2 (second prompt) -> no re-fire:', processCalls.length === before ? 'YES' : 'NO',
  '| no injected context:', !(c2.context ?? []).some((c) => String(c).includes('[josh-model]')) ? 'YES' : 'NO')

// Fresh registration (new "session") with empty briefing output.
hooks.length = 0
processCalls.length = 0
$.process.run = async () => ({ stdout: '' })
register(on)
const c3 = await firePrompt('what time is it')
console.log('CASE 3 (empty briefing) -> no context added:',
  !(c3.context ?? []).length ? 'YES' : 'NO')

// Fresh registration with a throwing subprocess: fail open.
hooks.length = 0
$.process.run = async () => { throw new Error('python exploded') }
register(on)
const c4 = await firePrompt('build another recipe')
console.log('CASE 4 (subprocess throws) -> prompt passes through:',
  c4.answered === 'build another recipe' && !(c4.context ?? []).length ? 'YES (fail open)' : 'NO')
