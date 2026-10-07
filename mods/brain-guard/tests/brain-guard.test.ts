import { expect, test } from 'claude-code/testing'

const MEM = '/Users/joshcramoy/.claude/projects/-x/memory/'
const KNOW = '/Users/joshcramoy/.claude/knowledge/'

test('memory write without frontmatter gets the lint nudge', async ($, on) => {
  on('tool.call', () => ({ result: 'File written successfully at: ' + MEM + 'x.md' }))

  const answer = await $.tool.call({
    tool: 'Write',
    file_path: MEM + 'bad.md',
    content: 'some fact with no frontmatter',
  })
  const text = String(answer.result)
  expect(text).toContain('[brain-guard lint]')
  expect(text).toContain('frontmatter')
})

test('memory write with relative date and no absolute anchor gets nudged', async ($, on) => {
  on('tool.call', () => ({ result: 'ok' }))

  const answer = await $.tool.call({
    tool: 'Write',
    file_path: MEM + 'dated.md',
    content:
      '---\nname: x\ndescription: y\nmetadata:\n  type: project\n---\nFixed yesterday, verify the flow.',
  })
  expect(String(answer.result)).toContain('relative date')
})

test('clean memory write passes without a nudge', async ($, on) => {
  on('tool.call', () => ({ result: 'ok' }))

  const answer = await $.tool.call({
    tool: 'Write',
    file_path: MEM + 'good.md',
    content:
      '---\nname: x\ndescription: y\nmetadata:\n  type: project\n---\nDone 2026-10-06: the fix landed.',
  })
  expect(String(answer.result)).not.toContain('[brain-guard lint]')
})

test('knowledge write without INDEX touch gets the INDEX nudge', async ($, on) => {
  on('tool.call', () => ({ result: 'ok' }))

  const answer = await $.tool.call({
    tool: 'Edit',
    file_path: KNOW + 'domains/workato-platform.md',
    new_string: 'updated 2026-10-06 content',
  })
  expect(String(answer.result)).toContain('INDEX.md not touched')
})

test('knowledge write passes when INDEX.md was already touched', async ($, on) => {
  on('tool.call', () => ({ result: 'ok' }))

  await $.tool.call({ tool: 'Edit', file_path: KNOW + 'INDEX.md', new_string: 'line' })
  const answer = await $.tool.call({
    tool: 'Edit',
    file_path: KNOW + 'domains/workato-platform.md',
    new_string: 'updated 2026-10-06 content',
  })
  expect(String(answer.result)).not.toContain('INDEX.md not touched')
})

test('unrelated file writes pass through silently', async ($, on) => {
  on('tool.call', () => ({ result: 'ok' }))

  const answer = await $.tool.call({
    tool: 'Write',
    file_path: '/Users/joshcramoy/project/src/app.ts',
    content: 'const x = 1',
  })
  expect(String(answer.result)).not.toContain('brain-guard')
})

test('/brain-guard command returns the status card', async ($) => {
  const answer = await $.command.run({ command: 'brain-guard', args: '' })
  expect(answer.text).toContain('Linter on memory/knowledge writes')
  expect(answer.text).toContain('usage-ledger')
})
