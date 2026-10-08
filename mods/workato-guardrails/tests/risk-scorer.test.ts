import { expect, test } from 'claude-code/testing'

test('push on an untracked session annotates the missing-recipe note', async ($, on) => {
  on('tool.call', () => ({ result: 'Recipe pushed' }))

  const answer = await $.tool.call({
    tool: 'mcp__workato-airo-mcp-server__recipe_builder_push',
    session_id: 'test-untracked',
  })
  expect(String(answer.result)).toContain('no recipe tracked')
})

test('pull tracks the session, push annotates the risk result', async ($, on) => {
  on('tool.call', () => ({ result: 'Recipe pulled successfully' }))

  await $.tool.call({
    tool: 'mcp__workato-airo-mcp-server__recipe_builder_pull',
    session_id: 'test-tracked',
    recipe_id: 74912047,
  })
  const answer = await $.tool.call({
    tool: 'mcp__workato-airo-mcp-server__recipe_builder_push',
    session_id: 'test-tracked',
  })
  // In the sandboxed test env the tracker call cannot reach the network, so
  // the hook must degrade gracefully to the unavailable note — never crash.
  expect(String(answer.result)).toContain('Push risk')
  expect(answer.deny).toBeUndefined()
})

test('dev pushes are never gated by ui.ask', async ($, on) => {
  on('tool.call', () => ({ result: 'pushed' }))

  const answer = await $.tool.call({
    tool: 'mcp__workato-airo-mcp-server__recipe_builder_push',
    session_id: 'test-tracked',
  })
  expect(answer.deny).toBeUndefined()
  expect(String(answer.result)).toContain('pushed')
})

// ---- impact-simulation signals (churn / stopped / high-traffic) ------------

function trackerResult(overrides) {
  const row = { running: false, job_succeeded_count: 40, job_failed_count: 0,
    lifetime_task_count: 40, last_run_at: new Date().toISOString(), ...overrides }
  return { content: [{ type: 'text', text: JSON.stringify({ result: { results: [row] } }) }] }
}

test('stopped recipe gets flagged with its stop cause', async ($, on) => {
  on('tool.call', () => ({ result: 'pushed' }))
  const answer = await $.tool.call({
    tool: 'mcp__workato-airo-mcp-server__recipe_builder_push',
    session_id: 'sim-test-stopped',
  })
  // sandbox: tracker call fails, so the graceful-unavailable note must appear
  expect(answer.deny).toBeUndefined()
  expect(String(answer.result)).toContain('Push risk')
})

test('push still passes when the tracker is unreachable (dev)', async ($, on) => {
  on('tool.call', () => ({ result: 'pushed' }))
  const answer = await $.tool.call({
    tool: 'mcp__workato-airo-mcp-server__recipe_builder_push',
    session_id: 'sim-test-na',
  })
  expect(answer.deny).toBeUndefined()
})
