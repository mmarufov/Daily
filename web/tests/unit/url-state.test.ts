import { describe, expect, it } from 'vitest'

import { buildQuery, explorerHrefString, readState } from '@/lib/url-state'

describe('readState', () => {
  it('defaults to the summary view and no filter', () => {
    const state = readState({})
    expect(state.view).toBe('summary')
    expect(state.outcome).toBe('all')
    expect(state.run).toBeUndefined()
  })

  it('rejects an unknown view rather than passing it through', () => {
    expect(readState({ view: 'javascript:alert(1)' }).view).toBe('summary')
    expect(readState({ outcome: 'made-up' }).outcome).toBe('all')
  })

  it('accepts every declared view and outcome', () => {
    expect(readState({ view: 'funnel' }).view).toBe('funnel')
    expect(readState({ view: 'stories' }).view).toBe('stories')
    expect(readState({ outcome: 'lost-before-scorer' }).outcome).toBe('lost-before-scorer')
  })

  it('takes the first value when a parameter repeats', () => {
    expect(readState({ persona: ['ray', 'lena'] }).persona).toBe('ray')
  })
})

describe('buildQuery', () => {
  it('merges a patch into existing state rather than replacing it', () => {
    const current = readState({ run: 'r1', persona: 'ray', view: 'stories', story: 'a00429' })
    const query = buildQuery(current, { outcome: 'lost-before-scorer' })
    expect(query).toEqual({
      run: 'r1',
      persona: 'ray',
      view: 'stories',
      outcome: 'lost-before-scorer',
      story: 'a00429',
    })
  })

  it('omits defaults so a shared link stays readable', () => {
    const query = buildQuery(readState({ run: 'r1' }), {})
    expect(query).toEqual({ run: 'r1' })
    expect('view' in query).toBe(false)
    expect('outcome' in query).toBe(false)
  })

  it('clears a value when the patch sets it to undefined', () => {
    const current = readState({ run: 'r1', story: 'a00429' })
    expect(buildQuery(current, { story: undefined })).toEqual({ run: 'r1' })
  })

  it('round-trips through a URL string', () => {
    const state = readState({ run: 'prod-llm__2026-09-02__47edb50', persona: 'ray', view: 'funnel' })
    const href = explorerHrefString(state, {})
    const params = Object.fromEntries(new URL(href, 'https://example.test').searchParams)
    expect(readState(params)).toEqual(state)
  })

  it('percent-encodes values that need it', () => {
    const href = explorerHrefString(readState({ run: 'a b&c=d' }), {})
    expect(href).toContain('run=a+b%26c%3Dd')
    const params = Object.fromEntries(new URL(href, 'https://example.test').searchParams)
    expect(params.run).toBe('a b&c=d')
  })
})
