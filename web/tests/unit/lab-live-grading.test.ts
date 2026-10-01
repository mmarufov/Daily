/**
 * The moment the runner exists to show: a fault-injected case catching a
 * candidate, named, with the reason it is a fault.
 *
 * Graded from committed record bundles with the real evaluator, so these are
 * the same answers a visitor would get running the same parser live.
 */

import { describe, expect, it } from 'vitest'

import { caughtByFault, wrongOnRecorded } from '@/lib/lab/live'

import { committedCases, gradeCommitted } from '../fixtures/live-outcome'

describe('summariseGrading', () => {
  it('names the fault that catches the count guard, and says why it is a fault', () => {
    const grading = gradeCommitted('count-guard-v1')
    expect(grading.verdict).toBe('rejected')
    expect(grading.cases).toHaveLength(64)

    const caught = caughtByFault(grading)
    expect(caught.map((c) => c.case_id)).toEqual(['syn-positional-reordered'])
    const fault = caught[0]
    expect(fault?.status).toBe('should-have-refused')
    // The case suite's own words, carried through rather than paraphrased.
    expect(fault?.why).toBe('equal length, internally reordered — a length check cannot detect this')
    expect(fault?.origin).toBe('fault-injection')
  })

  it('keeps recorded failures apart from fault-injected ones', () => {
    const grading = gradeCommitted('count-guard-v1')
    expect(wrongOnRecorded(grading).map((c) => c.case_id)).toEqual([
      'observed-2026-09-02-005',
      'observed-2026-09-02-035',
      'observed-2026-09-02-041',
    ])
    expect(grading.out_of_protocol_case_ids).toHaveLength(7)
  })

  it('reports no fault catch for the proposed keyed contract', () => {
    const grading = gradeCommitted('keyed-v2')
    expect(grading.verdict).toBe('accepted-for-review')
    expect(caughtByFault(grading)).toEqual([])
    // One fault is an association rule of the positional protocol, so it is
    // not scored against a keyed parser. Not scored is not passed, and the
    // page has to say which it was.
    const faults = grading.cases.filter((c) => c.origin === 'fault-injection')
    expect(faults).toHaveLength(22)
    expect(faults.filter((c) => c.applicability === 'not-applicable').map((c) => c.case_id)).toEqual([
      'syn-positional-reordered',
    ])
  })

  it('carries every case of the suite, 42 recorded and 22 fault-injected', () => {
    const cases = committedCases()
    expect(cases.filter((c) => c.origin === 'recorded-replay')).toHaveLength(42)
    expect(cases.filter((c) => c.origin === 'fault-injection')).toHaveLength(22)
    const grading = gradeCommitted('positional-v0')
    expect(new Set(grading.cases.map((c) => c.case_id))).toEqual(new Set(cases.map((c) => c.case_id)))
  })
})
