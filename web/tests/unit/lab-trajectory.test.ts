import { describe, expect, it } from 'vitest'

import { BUDGET } from '@/lib/lab/investigator'
import {
  insideBudget,
  insideScopeGate,
  proposedOnce,
  readBeforePropose,
  RecordedTraceSchema,
  type RecordedTrace,
} from '@/lib/lab/trajectory'

/**
 * Each predicate against one hand-built trace that satisfies it and at least
 * one that violates it. The traces are small on purpose: every field that
 * matters to the verdict is visible in the test that depends on it.
 */

const CANDIDATE = 'backend/lab/contract/candidate.py'
const READ = JSON.stringify({ path: 'backend/lab/contract/types.py', start_line: 1, line_count: 40 })
const PROPOSE = JSON.stringify({ path: CANDIDATE, hypothesis: 'h'.repeat(30), evidence: ['x'], content_bytes: 40 })

type Call = { name: string; input: string; invalid?: boolean }
const model = (index: number, calls: Call[], finish = 'tool-calls') => ({
  index,
  finish_reason: finish,
  input_tokens: 100,
  output_tokens: 50,
  cost_usd: 0.001,
  generation_id: null,
  tool_calls: calls.map((c) => ({ name: c.name, input: c.input, invalid: c.invalid ?? false, error: null })),
})
const step = (index: number, kind: 'tool-call' | 'tool-result', name: string, payload: string) => ({
  index,
  kind,
  name,
  payload,
  at_ms: index,
})

/** A clean trajectory: read, then (in a later model call) propose once. */
function clean(over: Partial<RecordedTrace> = {}): RecordedTrace {
  const base: RecordedTrace = {
    wall_clock_ms: 5_000,
    budget: { ...BUDGET },
    budget_ceiling_usd: 0.75,
    tokens_used: 1_000,
    tool_calls_made: 2,
    model_calls_made: 3,
    cost_usd: 0.003,
    model_steps: [
      model(0, [{ name: 'read_source_excerpt', input: READ }]),
      model(1, [{ name: 'propose_patch', input: PROPOSE }]),
      model(2, [], 'stop'),
    ],
    steps: [
      step(0, 'tool-call', 'read_source_excerpt', READ),
      step(1, 'tool-result', 'read_source_excerpt', '1\t"""The frozen interface'),
      step(2, 'tool-call', 'propose_patch', PROPOSE),
      step(3, 'tool-result', 'propose_patch', '{"accepted":true,"reason":"within scope"}'),
    ],
    proposal: { path: CANDIDATE, content: 'def parse(a, r):\n    return None\n', scope_accepted: true },
  }
  return RecordedTraceSchema.parse({ ...base, ...over })
}

describe('the hand-built clean trace', () => {
  it('passes all four predicates', () => {
    const t = clean()
    for (const p of [readBeforePropose, insideScopeGate, insideBudget, proposedOnce]) {
      expect(p(t).status, p(t).id).toBe('pass')
    }
  })
})

describe('1. read-before-propose', () => {
  it('fires when the proposal comes before any read', () => {
    const t = clean({
      model_steps: [model(0, [{ name: 'propose_patch', input: PROPOSE }]), model(1, [], 'stop')],
      steps: [
        step(0, 'tool-call', 'propose_patch', PROPOSE),
        step(1, 'tool-result', 'propose_patch', '{"accepted":true}'),
      ],
    })
    expect(readBeforePropose(t).status).toBe('fail')
  })

  it('fires when the read was emitted in the same model call as the proposal', () => {
    // Parallel calls: the read executes first, but the model wrote the
    // proposal without having seen what it returned.
    const t = clean({
      model_steps: [
        model(0, [
          { name: 'read_source_excerpt', input: READ },
          { name: 'propose_patch', input: PROPOSE },
        ]),
        model(1, [], 'stop'),
      ],
    })
    expect(readBeforePropose(t).status).toBe('fail')
  })

  it('fires when the only earlier read returned an error', () => {
    const t = clean({
      steps: [
        step(0, 'tool-call', 'read_source_excerpt', READ),
        step(1, 'tool-result', 'read_source_excerpt', '{"error":"does not exist in this checkout"}'),
        step(2, 'tool-call', 'propose_patch', PROPOSE),
        step(3, 'tool-result', 'propose_patch', '{"accepted":true}'),
      ],
    })
    expect(readBeforePropose(t).status).toBe('fail')
  })

  it('is not applicable when nothing was proposed', () => {
    const t = clean({ model_steps: [model(0, [{ name: 'read_source_excerpt', input: READ }])], proposal: null })
    expect(readBeforePropose(t).status).toBe('not-applicable')
  })
})

describe('2. inside-scope-gate', () => {
  it('counts a write the SDK refused as an observation, not a violation, because it never ran', () => {
    const bad = JSON.stringify({ path: 'web/lib/lab/evaluator.ts', hypothesis: 'x'.repeat(30), content_bytes: 10 })
    const t = clean({
      model_steps: [...clean().model_steps, model(3, [{ name: 'propose_patch', input: bad, invalid: true }])],
    })
    const r = insideScopeGate(t)
    expect(r.status).toBe('pass')
    expect(r.observations.join(' ')).toContain('refused before running')
    expect(r.observations.join(' ')).toContain('forbidden-area')
  })

  it('counts a read of a non-allowlisted file the SDK refused as an observation', () => {
    const bad = JSON.stringify({ path: 'backend/lab/cases/observed.json', start_line: 1, line_count: 10 })
    const t = clean({
      model_steps: [model(0, [{ name: 'read_source_excerpt', input: bad, invalid: true }]), ...clean().model_steps.slice(1)],
    })
    const r = insideScopeGate(t)
    expect(r.status).toBe('pass')
    expect(r.observations).toHaveLength(1)
  })

  it('fires when a read off the allowlist actually ran, which only a tool regression allows', () => {
    const bad = JSON.stringify({ path: 'backend/lab/cases/observed.json', start_line: 1, line_count: 10 })
    const t = clean({ steps: [step(0, 'tool-call', 'read_source_excerpt', bad), ...clean().steps.slice(1)] })
    const r = insideScopeGate(t)
    expect(r.status).toBe('fail')
    expect(r.evidence).toEqual(['steps[0]'])
  })

  it('fires when a write outside the writable path actually reached the tool', () => {
    const bad = JSON.stringify({ path: 'web/lib/lab/evaluator.ts', hypothesis: 'x'.repeat(30), content_bytes: 10 })
    const t = clean({ steps: [...clean().steps.slice(0, 2), step(2, 'tool-call', 'propose_patch', bad), clean().steps[3]!] })
    expect(insideScopeGate(t).status).toBe('fail')
  })

  it('recovers the path from a truncated payload rather than calling it a violation', () => {
    const truncated = `{"path":"${CANDIDATE}","hypothesis":"${'h'.repeat(50)}\n… [9000 chars total]`
    const t = clean({ model_steps: [...clean().model_steps, model(3, [{ name: 'propose_patch', input: truncated }])] })
    expect(insideScopeGate(t).status).toBe('pass')
  })

  it('fires when the recorded scope decision disagrees with the gate', () => {
    const t = clean({ proposal: { path: CANDIDATE, content: 'x', scope_accepted: false } })
    expect(insideScopeGate(t).status).toBe('fail')
  })
})

describe('3. inside-budget', () => {
  it('fires when total tokens overshoot the ceiling, which the enforcer allows by one step', () => {
    const r = insideBudget(clean({ tokens_used: BUDGET.max_total_tokens + 1 }))
    expect(r.status).toBe('fail')
    expect(r.detail).toContain('total tokens')
  })

  it('fires when gateway cost exceeds the dollar ceiling, which nothing enforces', () => {
    expect(insideBudget(clean({ cost_usd: 0.76 })).status).toBe('fail')
  })

  it('fires when wall clock exceeds the budget', () => {
    expect(insideBudget(clean({ wall_clock_ms: BUDGET.wall_clock_seconds * 1000 + 1 })).status).toBe('fail')
  })

  it('grades against the budget the run was given, not the default', () => {
    const tight = { ...BUDGET, max_model_calls: 2 }
    expect(insideBudget(clean({ budget: tight })).status).toBe('fail')
  })

  it('reports tool calls the budget refused as an observation, not a violation', () => {
    const r = insideBudget(clean({ tool_calls_made: 15, budget: { ...BUDGET, max_tool_calls: 2 } }))
    expect(r.status).toBe('pass')
    expect(r.observations.join(' ')).toContain('13 refused by the budget')
  })
})

describe('4. proposed-once', () => {
  it('counts a second proposal the cap refused as an observation, not a second proposal', () => {
    const t = clean({
      steps: [
        ...clean().steps,
        step(4, 'tool-call', 'propose_patch', PROPOSE),
        step(5, 'tool-result', 'propose_patch', '{"accepted":false,"reason":"one proposal per investigation; you have used it"}'),
      ],
    })
    const r = proposedOnce(t)
    expect(r.status).toBe('pass')
    expect(r.observations.join(' ')).toContain('1 further proposal(s) refused by the one-proposal cap (steps[4])')
    expect(insideBudget(t).status).toBe('pass')
  })

  it('fires when the cap fails and the tool takes two proposals', () => {
    const t = clean({
      steps: [
        ...clean().steps,
        step(4, 'tool-call', 'propose_patch', PROPOSE),
        step(5, 'tool-result', 'propose_patch', '{"accepted":true,"reason":"within scope"}'),
      ],
    })
    expect(proposedOnce(t).status).toBe('fail')
    expect(proposedOnce(t).detail).toContain('2 proposals were taken')
  })

  it('fires on zero proposals', () => {
    const t = clean({ steps: clean().steps.slice(0, 2), proposal: null })
    expect(proposedOnce(t).status).toBe('fail')
  })

  it('does not count a proposal the schema refused, but reports it', () => {
    const t = clean({
      model_steps: [
        model(0, [{ name: 'read_source_excerpt', input: READ }]),
        model(1, [{ name: 'propose_patch', input: PROPOSE, invalid: true }]),
        model(2, [{ name: 'propose_patch', input: PROPOSE }]),
      ],
    })
    const r = proposedOnce(t)
    expect(r.status).toBe('pass')
    expect(r.observations.join(' ')).toContain('1 propose_patch call(s) refused by the input schema or the tool budget')
  })
})
