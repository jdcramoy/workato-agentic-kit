import { expect, test } from 'claude-code/testing'

// Hook 16 (josh-model session briefing). The test sandbox has no $.process
// noun (verified constraint), so the briefing subprocess always throws here —
// which is exactly the fail-open path these tests prove. The positive path
// (briefing injected as context) is covered by tests/josh-model-driver.mjs
// with a mocked $.process, matching the push-identity-driver pattern.

test('first prompt fails open when the briefing subprocess is unavailable', async ($, on) => {
  on('prompt.submit', () => ({ drop: 'captured' }))

  const answer = await $.prompt.submit({ text: 'build a recipe for the thing' })
  // No deny, no mutation, no injected context: the prompt passes as-is.
  expect(answer.deny).toBeUndefined()
  expect(answer.drop).toBe('captured')
})

test('briefing fires at most once per session even across repeated failures', async ($, on) => {
  on('prompt.submit', () => ({ drop: 'captured' }))

  const first = await $.prompt.submit({ text: 'first prompt of the session' })
  const second = await $.prompt.submit({ text: 'second prompt, different topic' })
  expect(first.drop).toBe('captured')
  expect(second.drop).toBe('captured')
  // Neither carries injected context in the sandbox (fail-open path).
  expect(first.context).toBeUndefined()
  expect(second.context).toBeUndefined()
})

test('jira-story prompt still gets standards injection after the briefing hook runs', async ($, on) => {
  // Ordering check: hook 16 (fail-open here) must not eat hook 5's context.
  // A stubbed prompt.answer may not carry context, so capture via closure.
  let captured: string[] = []
  on('prompt.submit', (_$, e) => {
    captured = (e.context ?? []).map(String)
    return { drop: 'captured' }
  })

  await $.prompt.submit({ text: 'create a Jira story for the briefing work' })
  expect(captured.join('\n')).toContain('jira-story-standards')
})
