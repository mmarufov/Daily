import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { applicability, evaluate } from '@/lib/lab/evaluator'
import {
  parseCaseSuite,
  parseRecordBundle,
  type Case,
  type RecordBundle,
} from '@/lib/lab/records'

/**
 * These tests are the evaluator's own negative controls.
 *
 * Every assertion below is the inverse of a way the Lab could lie: accepting a
 * candidate that invents associations, accepting one that never ran, accepting
 * one that graded itself, or silently skipping a case. A green suite here is
 * the reason the published verdicts mean anything.
 */

const BACKEND = join(process.cwd(), '..', 'backend')

function loadCases(): Case[] {
  const cases: Case[] = []
  for (const group of ['observed', 'synthetic']) {
    const raw = JSON.parse(readFileSync(join(BACKEND, 'lab', 'cases', `${group}.json`), 'utf8'))
    const parsed = parseCaseSuite(raw)
    if (!parsed.ok) throw new Error(`${group}: ${parsed.issues.join('; ')}`)
    cases.push(...parsed.value.cases)
  }
  return cases
}

function loadBundle(name: string): RecordBundle {
  const raw = JSON.parse(readFileSync(join(BACKEND, 'lab', 'records', `${name}.json`), 'utf8'))
  const parsed = parseRecordBundle(raw)
  if (!parsed.ok) throw new Error(`${name}: ${parsed.issues.join('; ')}`)
  return parsed.value
}

const CASES = loadCases()

describe('the case suite itself', () => {
  it('keeps observed and synthetic cases apart', () => {
    const observed = CASES.filter((c) => c.group === 'observed')
    const synthetic = CASES.filter((c) => c.group === 'synthetic')
    expect(observed.length).toBeGreaterThan(20)
    expect(synthetic.length).toBeGreaterThan(15)
    expect(observed.every((c) => c.origin === 'recorded-replay')).toBe(true)
    expect(synthetic.every((c) => c.origin === 'fault-injection')).toBe(true)
  })

  it('never claims ground truth for a recorded response', () => {
    // An observed case may assert a refusal, because the recording settles
    // that. It may never assert which article a verdict belonged to.
    for (const kase of CASES.filter((c) => c.group === 'observed')) {
      expect(kase.expectation.association).toBeNull()
    }
  })

  it('gives every synthetic parse case a complete association', () => {
    for (const kase of CASES.filter((c) => c.group === 'synthetic' && c.expectation.expect === 'parse')) {
      const association = kase.expectation.association
      expect(association).not.toBeNull()
      expect(Object.keys(association ?? {}).sort()).toEqual(kase.articles.map((a) => a.id).sort())
    }
  })

  it('has unique case ids', () => {
    const ids = CASES.map((c) => c.case_id)
    expect(new Set(ids).size).toBe(ids.length)
  })
})

describe('applicability', () => {
  const universal = CASES.find((c) => c.family === 'universal-refusal')
  const keyed = CASES.find((c) => c.family === 'protocol-association' && c.protocol === 'keyed-v2')

  it('binds a universal refusal to every protocol', () => {
    expect(applicability(universal!, 'keyed-v2')).toBe('scored')
    expect(applicability(universal!, 'positional-v0')).toBe('scored')
  })

  it('binds an association case only to its own protocol', () => {
    expect(applicability(keyed!, 'keyed-v2')).toBe('scored')
    expect(applicability(keyed!, 'positional-v0')).toBe('not-applicable')
  })
})

describe('evaluate — the three preserved versions', () => {
  it('rejects historical positional parsing', () => {
    const result = evaluate(CASES, loadBundle('positional-v0'))
    expect(result.verdict).toBe('rejected')
    // It never refuses, so it invents an association for every unparseable
    // response. That is the defect, measured rather than described.
    expect(result.counts['should-have-refused']).toBeGreaterThan(30)
  })

  it('rejects the count-mismatch guard, and says why it is not enough', () => {
    const result = evaluate(CASES, loadBundle('count-guard-v1'))
    expect(result.verdict).toBe('rejected')
    const universal = result.criteria.find((c) => c.id === 'universal-refusal')
    // The guard genuinely fixes the count cases it can see...
    expect(universal?.rate).toBe(1)
    // ...but a length check cannot establish association, so it still fails
    // the protocol rules.
    expect(result.criteria.some((c) => !c.passed)).toBe(true)
  })

  it('accepts the keyed contract for review', () => {
    const result = evaluate(CASES, loadBundle('keyed-v2'))
    expect(result.verdict).toBe('accepted-for-review')
    expect(result.criteria.every((c) => c.passed)).toBe(true)
  })
})

describe('evaluate — defective controls are rejected for their intended reason', () => {
  it('rejects last-write-wins on duplicate ids', () => {
    const result = evaluate(CASES, loadBundle('control-lenient-keyed'))
    expect(result.verdict).toBe('rejected')
    const duplicate = result.outcomes.find((o) => o.case_id === 'syn-duplicate-id')
    expect(duplicate?.status).toBe('should-have-refused')
  })

  it('rejects a candidate that grades itself', () => {
    const result = evaluate(CASES, loadBundle('control-self-reporting'))
    expect(result.verdict).toBe('rejected')
    expect(result.smallest_counterexample).not.toBeNull()
  })

  it('rejects turning an unavailable answer into zeros', () => {
    const result = evaluate(CASES, loadBundle('control-zero-filling'))
    expect(result.verdict).toBe('rejected')
    const missing = result.outcomes.find((o) => o.case_id === 'syn-exec-no-recording')
    expect(missing?.status).toBe('should-have-refused')
  })
})

describe('evaluate — missing evidence is never acceptance', () => {
  const accepted = loadBundle('keyed-v2')

  it('returns incomplete when a record is missing', () => {
    // Drop a universal-refusal case, which is scored for every protocol.
    // Dropping a not-applicable one would prove nothing.
    const scoredId = CASES.find((c) => c.family === 'universal-refusal')!.case_id
    const thinned: RecordBundle = {
      ...accepted,
      records: accepted.records.filter((r) => r.case_id !== scoredId),
    }
    const result = evaluate(CASES, thinned)
    expect(result.verdict).toBe('incomplete')
    expect(result.reason).toMatch(/never acceptance/)
  })

  it('returns incomplete when a case crashed', () => {
    const scoredId = CASES.find((c) => c.family === 'universal-refusal')!.case_id
    const crashed: RecordBundle = {
      ...accepted,
      records: accepted.records.map((r) =>
        r.case_id === scoredId ? { ...r, outcome: 'crashed' as const, association: null, error: 'boom' } : r,
      ),
    }
    expect(evaluate(CASES, crashed).verdict).toBe('incomplete')
  })

  it('returns incomplete when a case timed out', () => {
    const scoredId = CASES.find((c) => c.family === 'universal-refusal')!.case_id
    const timedOut: RecordBundle = {
      ...accepted,
      records: accepted.records.map((r) =>
        r.case_id === scoredId ? { ...r, outcome: 'timeout' as const, association: null, error: 'hung' } : r,
      ),
    }
    expect(evaluate(CASES, timedOut).verdict).toBe('incomplete')
  })

  it('returns incomplete with no bundle at all, and failed when the run errored', () => {
    expect(evaluate(CASES, null).verdict).toBe('incomplete')
    expect(evaluate(CASES, null, { failure: 'sandbox died' }).verdict).toBe('failed')
  })

  it('returns cancelled without inspecting anything', () => {
    const result = evaluate(CASES, accepted, { cancelled: true })
    expect(result.verdict).toBe('cancelled')
    expect(result.outcomes).toHaveLength(0)
  })

  it('never reports a vacuous criterion as passed', () => {
    // A bundle declaring a protocol no case uses makes every association
    // criterion inapplicable. That must not be acceptance by default.
    const alien: RecordBundle = { ...accepted, declared_protocol: 'invented-v9' }
    const result = evaluate(CASES, alien)
    const association = result.criteria.find((c) => c.id === 'association-exact')
    expect(association?.applicable).toBe(0)
    expect(association?.rate).toBeNull()
    expect(association?.passed).toBe(false)
    expect(result.verdict).not.toBe('accepted-for-review')
  })
})

describe('evaluate — a candidate cannot grade itself', () => {
  it('ignores self-assessment fields smuggled into the bundle', () => {
    const accepted = loadBundle('control-self-reporting')
    const doctored = {
      ...accepted,
      passed: true,
      verdict: 'accepted-for-review',
      records: accepted.records.map((r) => ({ ...r, passed: true, score: 1 })),
    }
    // The schema strips them; the evaluator never sees them.
    const parsed = parseRecordBundle(doctored)
    expect(parsed.ok).toBe(true)
    if (!parsed.ok) return
    expect('passed' in parsed.value).toBe(false)
    expect(parsed.value.records.every((r) => !('passed' in r))).toBe(true)
    expect(evaluate(CASES, parsed.value).verdict).toBe('rejected')
  })
})
