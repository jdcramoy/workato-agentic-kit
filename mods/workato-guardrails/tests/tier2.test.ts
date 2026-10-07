import { expect, test } from 'claude-code/testing'

test('Jira-story prompts get jira-story-standards injected as context', async ($, on) => {
  // Answer the prompt in Claude Code's place; capture what was passed on.
  let seenContext: unknown
  on('prompt.submit', (_$, e) => {
    seenContext = (e as { context?: unknown }).context
    return { drop: 'test capture' }
  })

  await $.prompt.submit({ text: 'create a Jira story for the payment-elections fix' })
  const ctx = JSON.stringify(seenContext ?? '')
  expect(ctx).toContain('jira-story-standards')
  expect(ctx).toContain('customfield_10057')
})

test('unrelated prompts get no standards injection', async ($, on) => {
  on('prompt.submit', () => ({ drop: 'captured' }))

  const answer = await $.prompt.submit({ text: 'list the files in this directory' })
  expect(answer.drop).toBe('captured')
  // No exception and no injection side effects to observe — drop came through.
})

test('secrets in tool results are redacted (key prefix, bearer, assignment)', async ($, on) => {
  on('tool.call', () => ({
    result:
      'response: {"api_key": "sk-ant-api1234567890abcdefSECRET", "auth": "Bearer eyJhbGciOiJIUzI1NiIsSecretToken123", "note": "no secrets here"}',
  }))

  const answer = await $.tool.call({ tool: 'Read', file_path: 'config.json' })
  const text = String(answer.result)
  expect(text).not.toContain('sk-ant-api1234567890abcdefSECRET')
  expect(text).not.toContain('eyJhbGciOiJIUzI1NiIsSecretToken123')
  expect(text).toContain('[REDACTED]')
  expect(text).toContain('no secrets here')
})

test('prose containing the word "token" is not mangled', async ($, on) => {
  on('tool.call', () => ({
    result: 'The token bucket rate limiter allows 100 requests. Password policies apply.',
  }))

  const answer = await $.tool.call({ tool: 'Read', file_path: 'docs.md' })
  expect(answer.result).toContain('token bucket rate limiter')
  expect(answer.result).not.toContain('[REDACTED]')
})

test('/guardrails command returns the status card', async ($) => {
  const answer = await $.command.run({ command: 'guardrails', args: '' })
  expect(answer.text).toContain('workato-guardrails v')
  expect(answer.text).toContain('active hooks')
  expect(answer.text).toContain('prod-write audit')
  expect(answer.text).toContain('customfield_10057')
})
