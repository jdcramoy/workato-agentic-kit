import { describe, expect, mock, test } from 'claude-code/testing'

// KNOWN TEST-ENGINE GAP: the test Engine implements no $.fs noun, so the
// closeout-row-present pass-through branch cannot be exercised here — the
// module fail-closes (blocks) when the ledger is unreadable, which is the
// behavior pinned below. The pass branch is covered by logic review and the
// first live session; confirm there before trusting it.
const TMP_LEDGER = '/tmp/session-budget-test/closeouts.jsonl'

const TEST_ENV = {
  SESSION_BUDGET_WARN_USD: '-1',
  SESSION_BUDGET_HARD_USD: '-1',
  SESSION_BUDGET_WARN_CTX_PCT: '-1',
  SESSION_BUDGET_HARD_CTX_PCT: '-1',
  SESSION_BUDGET_CLOSEOUT_LEDGER: TMP_LEDGER,
  SESSION_BUDGET_FORCE: 'hard',
}

describe('session-budget', () => {
  test('blocks over budget with handoff orders', async ($, on) => {
    mock.env(on, TEST_ENV)
    on('classic.Stop', () => ({}))
    const r = (await ($.classic as any).Stop({
      session_id: 's-block-1',
      stop_hook_active: false,
    })) as any
    expect(String(r?.block ?? '')).toContain('SESSION BUDGET EXHAUSTED')
    expect(String(r?.block ?? '')).toContain('s-block-1')
    expect(String(r?.block ?? '')).toContain('handoff skill')
  })

  test('unreadable closeout ledger fail-closes to a block', async ($, on) => {
    mock.env(on, TEST_ENV)
    on('classic.Stop', () => ({}))
    const r = (await ($.classic as any).Stop({
      session_id: 's-done-1',
      stop_hook_active: false,
    })) as any
    expect(String(r?.block ?? '')).toContain('SESSION BUDGET EXHAUSTED')
  })

  test('respects the native stop_hook_active escape', async ($, on) => {
    mock.env(on, TEST_ENV)
    on('classic.Stop', () => ({}))
    const r = (await ($.classic as any).Stop({
      session_id: 's-esc-1',
      stop_hook_active: true,
    })) as any
    expect(r?.block).toBeUndefined()
  })

  test('fleet jobs are exempt', async ($, on) => {
    mock.env(on, { ...TEST_ENV, CLAUDE_JOB: 'yes' })
    on('classic.Stop', () => ({}))
    const r = (await ($.classic as any).Stop({
      session_id: 's-fleet-1',
      stop_hook_active: false,
    })) as any
    expect(r?.block).toBeUndefined()
  })

  test('block budget exhausts after three blocks', async ($, on) => {
    mock.env(on, TEST_ENV)
    on('classic.Stop', () => ({}))
    let r: any = await ($.classic as any).Stop({ session_id: 's-loop-1', stop_hook_active: false })
    expect(String(r?.block ?? '')).toContain('SESSION BUDGET EXHAUSTED')
    await ($.classic as any).Stop({ session_id: 's-loop-1', stop_hook_active: false })
    await ($.classic as any).Stop({ session_id: 's-loop-1', stop_hook_active: false })
    r = await ($.classic as any).Stop({ session_id: 's-loop-1', stop_hook_active: false })
    expect(r?.block).toBeUndefined()
  })

  test('/budget command reports figures', async ($, on) => {
    mock.env(on, TEST_ENV)
    const r = (await ($.command as any).run({ command: 'budget' })) as any
    expect(String(r?.text ?? '')).toContain('session spend')
  })
})
