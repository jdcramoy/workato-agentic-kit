import { expect, test } from 'claude-code/testing'

// Hook 13 — prod-write confirm gate for every non-AIRO surface.
// In the sandboxed test env $.ui.ask cannot be answered, so the gate must
// fail closed: a prod WRITE denies, a prod READ passes through untouched.

const PROD_MARK = 'd42cc899-694d-474e-80ef-c4eb3d43cf9f'

// ---- prod writes are blocked ------------------------------------------------

test('wt-prod mutation is blocked', async ($, on) => {
  on('tool.call', () => ({ result: 'recipe started' }))
  const answer = await $.tool.call({ tool: 'Bash', command: 'wt-prod recipes start 74912047' })
  expect(answer.deny).toBeDefined()
  expect(String(answer.deny)).toContain('prod-write gate')
})

test('workato-prod push is blocked', async ($, on) => {
  on('tool.call', () => ({ result: 'pushed' }))
  const answer = await $.tool.call({ tool: 'Bash', command: 'workato-prod push' })
  expect(answer.deny).toBeDefined()
})

test('wt with WORKATO_PROFILE=josh-prod api POST is blocked', async ($, on) => {
  on('tool.call', () => ({ result: 'ok' }))
  const answer = await $.tool.call({
    tool: 'Bash',
    command: 'WORKATO_PROFILE=josh-prod wt api POST /api/recipes/1/start',
  })
  expect(answer.deny).toBeDefined()
})

test('raw http carrying the prod credential is blocked on write', async ($, on) => {
  on('tool.call', () => ({ result: 'ok' }))
  const answer = await $.tool.call({
    tool: 'Bash',
    command: `curl -X DELETE https://www.workato.com/api/recipes/1 -H "Authorization: Bearer ${PROD_MARK}"`,
  })
  expect(answer.deny).toBeDefined()
})

test('orca interaction against a prod url is blocked', async ($, on) => {
  on('tool.call', () => ({ result: 'clicked' }))
  const answer = await $.tool.call({
    tool: 'Bash',
    command: 'orca find --action click --url "https://app.workato.com/recipes?env=Production"',
  })
  expect(answer.deny).toBeDefined()
})

// ---- prod reads pass through ------------------------------------------------

test('wt-prod read passes through', async ($, on) => {
  on('tool.call', () => ({ result: 'recipe details' }))
  const answer = await $.tool.call({ tool: 'Bash', command: 'wt-prod recipes get 74912047' })
  expect(answer.deny).toBeUndefined()
  expect(String(answer.result)).toContain('recipe details')
})

test('workato-prod workspace read passes through', async ($, on) => {
  on('tool.call', () => ({ result: 'workspace info' }))
  const answer = await $.tool.call({ tool: 'Bash', command: 'workato-prod workspace' })
  expect(answer.deny).toBeUndefined()
})

test('wt-prod api GET passes through', async ($, on) => {
  on('tool.call', () => ({ result: '{"id":3535598}' }))
  const answer = await $.tool.call({ tool: 'Bash', command: 'wt-prod api GET /api/users/me' })
  expect(answer.deny).toBeUndefined()
})

// ---- dev is never gated -----------------------------------------------------

test('dev wt mutation is not gated', async ($, on) => {
  on('tool.call', () => ({ result: 'recipe started' }))
  const answer = await $.tool.call({ tool: 'Bash', command: 'wt recipes start 74912047' })
  expect(answer.deny).toBeUndefined()
  expect(String(answer.result)).toContain('recipe started')
})

test('dev workato push is not gated', async ($, on) => {
  on('tool.call', () => ({ result: 'pushed' }))
  const answer = await $.tool.call({ tool: 'Bash', command: 'workato push' })
  expect(answer.deny).toBeUndefined()
})

test('unrelated bash is untouched', async ($, on) => {
  on('tool.call', () => ({ result: 'files' }))
  const answer = await $.tool.call({ tool: 'Bash', command: 'ls -la /tmp' })
  expect(answer.deny).toBeUndefined()
  expect(String(answer.result)).toContain('files')
})
