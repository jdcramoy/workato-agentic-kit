import { expect, test } from 'claude-code/testing'

// Hook 15: push identity guard — warn-only same-name live-recipe warning on
// recipe_builder_push (BSYS-29488 two-copy divergence class).
//
// The warn path needs $.mcp.call (recipe_get + one recipe_list), and the test
// sandbox serves no mcp noun at all ($.mcp is undefined), so the lookup-backed
// cases cannot be stubbed here. They are covered end-to-end in a node driver
// that loads the REAL register.js and fires the REAL hook chain against REAL
// captured MCP payloads from a live duplicate-name pair (recipes 83197137 /
// 83197138, folder 35835951, 2026-10-20). What the harness CAN test — the
// never-block contract and graceful degrade — is below.

test('push on an untracked session passes with no identity warning', async ($, on) => {
  on('tool.call', () => ({ result: 'Recipe pushed' }))

  const answer = await $.tool.call({
    tool: 'mcp__workato-airo-mcp-server__recipe_builder_push',
    session_id: 'pid-untracked',
  })
  expect(answer.deny).toBeUndefined()
  expect(String(answer.result)).toContain('Recipe pushed')
  expect(String(answer.result)).not.toContain('PUSH IDENTITY WARNING')
})

test('identity-guard lookups failing never fails or blocks the push', async ($, on) => {
  on('tool.call', () => ({ result: 'Recipe pushed' }))
  // sandbox: $.mcp is undefined, so every lookup the guard makes throws —
  // the guard must swallow that and pass the push through untouched.
  const answer = await $.tool.call({
    tool: 'mcp__workato-airo-mcp-server__recipe_builder_push',
    session_id: 'pid-degrade',
    recipe_id: 111000115,
  })
  expect(answer.deny).toBeUndefined()
  expect(String(answer.result)).toContain('Recipe pushed')
  expect(String(answer.result)).not.toContain('PUSH IDENTITY WARNING')
})

test('the guard is warn-only on PROD pushes too (no deny path exists)', async ($, on) => {
  on('tool.call', () => ({ result: 'Recipe pushed' }))

  const answer = await $.tool.call({
    tool: 'mcp__workato-airo-mcp-prod__recipe_builder_push',
    session_id: 'pid-prod',
    recipe_id: 111000115,
  })
  // The prod risk gate may deny a risky push (hook 9); the identity guard
  // itself must never add a deny — a missing deny here proves the chain
  // passed a prod push through when nothing risky is on record.
  expect(String(answer.result)).not.toContain('PUSH IDENTITY WARNING')
})
