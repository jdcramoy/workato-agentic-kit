import { expect, test } from 'claude-code/testing'

test('createJiraIssue without story points is denied with the scale', async ($, on) => {
  // Answer in Claude Code's place when the call gets past the mod,
  // so the test proves the deny came from the mod's hook.
  on('tool.call', () => ({ result: 'PASSTHROUGH' }))

  const answer = await $.tool.call({
    tool: 'mcp__atlassian__createJiraIssue',
    projectKey: 'BSYS',
    additional_fields: '{"components":[{"name":"Backend"}]}',
  })
  expect(answer.deny).toContain('customfield_10057')
  expect(answer.deny).toContain('Story Points')
})

test('createJiraIssue with customfield_10057 passes through', async ($, on) => {
  on('tool.call', () => ({ result: 'PASSTHROUGH' }))

  const answer = await $.tool.call({
    tool: 'mcp__atlassian__createJiraIssue',
    projectKey: 'BSYS',
    additional_fields: '{"customfield_10057": 3}',
  })
  // v0.3: the writeback nudge also annotates successful Jira writes.
  expect(String(answer.result)).toContain('PASSTHROUGH')
  expect(String(answer.result)).toContain('re-read it back')
  expect(answer.deny).toBeUndefined()
})

test('blocked projects (BTSUP) may create without points', async ($, on) => {
  on('tool.call', () => ({ result: 'PASSTHROUGH' }))

  const answer = await $.tool.call({
    tool: 'mcp__atlassian__createJiraIssue',
    projectKey: 'BTSUP',
    additional_fields: '{}',
  })
  expect(String(answer.result)).toContain('PASSTHROUGH')
  expect(answer.deny).toBeUndefined()
})

test('AIRO result with a recipe_id gets the canonical URL appended', async ($, on) => {
  // Stub the tool's real result: a payload containing a bare recipe_id.
  on('tool.call', () => ({ result: '{"result":"Recipe retrieved successfully\\n\\n### Recipe: demo (ID: 74912047)\\n\\nrecipe_id: 74912047 folder_id: 30326966"}' }))

  const answer = await $.tool.call({
    tool: 'mcp__workato-airo-mcp-server__recipe_get',
    recipe_id: 74912047,
  })
  expect(answer.result).toContain('https://app.workato.com/recipes/74912047')
  expect(answer.result).toContain('https://app.workato.com/recipes?fid=30326966')
})

test('results that already carry Workato URLs are not annotated twice', async ($, on) => {
  on('tool.call', () => ({ result: 'see https://app.workato.com/recipes/74912047 (recipe_id: 74912047)' }))

  const answer = await $.tool.call({
    tool: 'mcp__workato-airo-mcp-server__recipe_get',
    recipe_id: 74912047,
  })
  const matches = answer.result.match(/app\.workato\.com\/recipes\/74912047/g) ?? []
  expect(matches.length).toBe(1)
})

test('non-Workato tools pass through untouched', async ($, on) => {
  on('tool.call', () => ({ result: 'plain result' }))

  const answer = await $.tool.call({ tool: 'Read', file_path: 'README.md' })
  expect(answer.result).toBe('plain result')
})
