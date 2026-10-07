import { expect, test } from 'claude-code/testing'

test('successful AIRO mutations pass through (ledger write is side-effect only)', async ($, on) => {
  on('tool.call', () => ({ result: 'Recipe saved' }))

  const answer = await $.tool.call({
    tool: 'mcp__workato-airo-mcp-server__recipe_builder_save',
    session_id: 'ledger-test',
    name: 'demo',
    folder_id: '30326966',
  })
  expect(answer.deny).toBeUndefined()
  expect(String(answer.result)).toContain('Recipe saved')
})

test('failed mutations pass through with the error intact', async ($, on) => {
  on('tool.call', () => ({ deny: 'blocked by test' }))

  const answer = await $.tool.call({
    tool: 'mcp__workato-airo-mcp-server__recipe_builder_save',
    session_id: 'ledger-test',
  })
  expect(answer.deny).toBe('blocked by test')
})

test('AIRO read tools are not treated as mutations', async ($, on) => {
  on('tool.call', () => ({ result: 'details' }))

  const answer = await $.tool.call({
    tool: 'mcp__workato-airo-mcp-server__recipe_get',
    recipe_id: 74912047,
  })
  expect(String(answer.result)).toContain('details')
  expect(answer.deny).toBeUndefined()
})

test('Bash commands without workato/orca pass through untouched', async ($, on) => {
  on('tool.call', () => ({ result: 'files' }))

  const answer = await $.tool.call({ tool: 'Bash', command: 'ls -la' })
  expect(answer.result).toBe('files')
})

test('/promoted without IDs explains usage', async ($) => {
  const answer = await $.command.run({ command: 'promoted', args: '' })
  expect(answer.text).toContain('Usage')
})

test('ticket keys in prompts are tracked without breaking injection', async ($, on) => {
  on('prompt.submit', () => ({ drop: 'captured' }))

  const a = await $.prompt.submit({ text: 'create a Jira story for BSYS-29309' })
  expect(a.drop).toBe('captured')
  const b = await $.prompt.submit({ text: 'plain question with no work' })
  expect(b.drop).toBe('captured')
})

test('/cockpit opens the pane or falls back to text (headless-safe)', async ($) => {
  const answer = await $.command.run({ command: 'cockpit', args: '' })
  // Headless test env has no drawing surface, so the fallback text path runs.
  expect(String(answer.text)).toContain('Workato cockpit')
})
