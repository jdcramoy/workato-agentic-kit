import { expect, test } from 'claude-code/testing'

test('recipe_builder_pull results get the datapill trap warning', async ($, on) => {
  on('tool.call', () => ({ result: 'Recipe pulled successfully. code: for start_workflow_1 in ...' }))

  const answer = await $.tool.call({
    tool: 'mcp__workato-airo-mcp-server__recipe_builder_pull',
    recipe_id: 74912047,
  })
  expect(String(answer.result)).toContain('DO NOT TRUST this DSL export')
  expect(String(answer.result)).toContain('SAMPLE VALUE')
})

test('other AIRO tools do not get the datapill warning', async ($, on) => {
  on('tool.call', () => ({ result: 'Recipe saved.' }))

  const answer = await $.tool.call({
    tool: 'mcp__workato-airo-mcp-server__recipe_builder_save',
    recipe_id: 74912047,
  })
  expect(String(answer.result)).not.toContain('DO NOT TRUST')
})

test('Jira writes get the re-read nudge (getJiraIssue variant)', async ($, on) => {
  on('tool.call', () => ({ result: 'BSYS-30001 created.' }))

  const answer = await $.tool.call({
    tool: 'mcp__atlassian__editJiraIssue',
    issueIdOrKey: 'BSYS-30001',
    fields: {},
  })
  expect(String(answer.result)).toContain('getJiraIssue')
  expect(String(answer.result)).toContain('re-read it back')
})

test('Confluence writes get the re-read nudge (getConfluencePage variant)', async ($, on) => {
  on('tool.call', () => ({ result: 'Page 12345 updated.' }))

  const answer = await $.tool.call({
    tool: 'mcp__atlassian__updateConfluencePage',
    pageId: '12345',
    body: 'content',
  })
  expect(String(answer.result)).toContain('getConfluencePage')
})

test('Jira reads do not get the nudge', async ($, on) => {
  on('tool.call', () => ({ result: 'Issue details...' }))

  const answer = await $.tool.call({
    tool: 'mcp__atlassian__getJiraIssue',
    issueIdOrKey: 'BSYS-30001',
  })
  expect(String(answer.result)).not.toContain('re-read it back')
})
