import { describe, expect, it } from 'vitest'

import { evaluate } from '@/lib/lab/evaluator'
import { parseCaseSuite, parseRecordBundle, type Case } from '@/lib/lab/records'
import { ACCEPTANCE_V1, ACCEPTANCE_V2, ACCEPTANCE_V3, SPEC_V1, SPEC_V2, SPEC_V3, SPECS, specHash } from '@/lib/lab/spec'
import type { PredicateResult } from '@/lib/lab/trajectory'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/**
 * Two generations of criteria, and the rules that keep both meaningful.
 *
 * Adding a criterion after eight runs have been published is the single
 * easiest way to rewrite history in this repository: re-grade, publish the
 * new answer, and the old one is gone. These tests exist so that cannot
 * happen quietly.
 */

const LAB = join(process.cwd(), '..', 'backend', 'lab')

function cases(): Case[] {
  return (['observed', 'synthetic'] as const).flatMap((g) => {
    const parsed = parseCaseSuite(JSON.parse(readFileSync(join(LAB, 'cases', `${g}.json`), 'utf8')))
    if (!parsed.ok) throw new Error(parsed.issues.join('; '))
    return parsed.value.cases
  })
}

function bundle(id: string) {
  const parsed = parseRecordBundle(JSON.parse(readFileSync(join(LAB, 'records', `${id}.json`), 'utf8')))
  if (!parsed.ok) throw new Error(parsed.issues.join('; '))
  return parsed.value
}

describe('generation 1 is frozen', () => {
  it('still hashes to the value eight committed artifacts carry', () => {
    // If this fails, someone edited SPEC_V1 — including reordering a key,
    // since `specHash` digests JSON.stringify. Every published verdict would
    // start claiming it was judged against criteria it never faced.
    expect(specHash(SPEC_V1)).toBe('008af8266204438a')
  })

  it('has exactly the five criteria it shipped with', () => {
    expect(ACCEPTANCE_V1.map((c) => c.id)).toEqual([
      'universal-refusal',
      'association-exact',
      'protocol-violation-refusal',
      'no-crash',
      'complete-evidence',
    ])
  })

  it('is a distinct generation from 2', () => {
    expect(specHash(SPEC_V1)).not.toBe(specHash(SPEC_V2))
    expect(SPECS.map((s) => s.spec_version)).toEqual([1, 2, 3])
  })
})

describe('generation 2 adds one criterion and changes nothing else', () => {
  it('extends rather than rewrites', () => {
    expect(ACCEPTANCE_V2.slice(0, ACCEPTANCE_V1.length)).toEqual(ACCEPTANCE_V1)
    expect(ACCEPTANCE_V2.map((c) => c.id).slice(-1)).toEqual(['protocol-exclusivity'])
  })

  it('keeps every threshold at 1', () => {
    // "Refuses 90% of the protocols it does not implement" is not a partial
    // success, and a criterion added at 0.9 would be a criterion added to pass.
    for (const c of ACCEPTANCE_V2) expect(c.threshold).toBe(1)
  })

  it('differs from generation 1 only in acceptance, measures and version', () => {
    const differing = (Object.keys(SPEC_V2) as (keyof typeof SPEC_V2)[]).filter(
      (k) => JSON.stringify(SPEC_V2[k]) !== JSON.stringify(SPEC_V1[k]),
    )
    expect(differing.sort()).toEqual(['acceptance', 'measures', 'spec_version'])
  })
})

describe('what the new criterion actually caught', () => {
  const all = cases()

  it('moves keyed-fallback-v1 from accepted to rejected, and nothing else', () => {
    const moved: string[] = []
    for (const id of [
      'positional-v0',
      'count-guard-v1',
      'keyed-v2',
      'keyed-fallback-v1',
      'control-lenient-keyed',
      'control-self-reporting',
      'control-zero-filling',
    ]) {
      const records = bundle(id)
      const v1 = evaluate(all, records, { spec: SPEC_V1 })
      const v2 = evaluate(all, records, { spec: SPEC_V2 })
      if (v1.verdict !== v2.verdict) moved.push(`${id}: ${v1.verdict} -> ${v2.verdict}`)
    }
    // A new criterion that moves half the field is measuring something other
    // than the thing it was written for.
    expect(moved).toEqual(['keyed-fallback-v1: accepted-for-review -> rejected'])
  })

  it('credits the candidate that refuses what it does not declare', () => {
    const result = evaluate(all, bundle('keyed-v2'), { spec: SPEC_V2 })
    const c = result.criteria.find((x) => x.id === 'protocol-exclusivity')
    expect(c?.passed).toBe(true)
    expect(c?.satisfied).toBe(c?.applicable)
  })

  it('names the cases it failed on, so the count can be checked', () => {
    const result = evaluate(all, bundle('keyed-fallback-v1'), { spec: SPEC_V2 })
    const d = result.diagnostics.find((x) => x.id === 'out-of-protocol-association')
    expect(d?.case_ids).toContain('syn-positional-reordered')
    // The case built to expose the defect this whole experiment measures.
    expect(d?.detail).not.toContain('never graded')
  })

  it('is not vacuously satisfied by a candidate with nothing to be exclusive about', () => {
    const result = evaluate([], bundle('keyed-v2'), { spec: SPEC_V2 })
    const c = result.criteria.find((x) => x.id === 'protocol-exclusivity')
    if (c !== undefined) {
      expect(c.passed).toBe(false)
      expect(c.rate).toBeNull()
    }
  })

  it('carries the generation that produced each verdict', () => {
    const v1 = evaluate(all, bundle('keyed-v2'), { spec: SPEC_V1 })
    expect(v1.spec_version).toBe(1)
    expect(v1.spec_hash).toBe(specHash(SPEC_V1))
  })
})

describe('generation 3 adds the trajectory and changes no earlier verdict', () => {
  const all = cases()
  const result = (id: PredicateResult['id'], status: PredicateResult['status']): PredicateResult => ({
    id,
    status,
    detail: '',
    evidence: [],
    observations: [],
  })
  const clean = (['read-before-propose', 'inside-scope-gate', 'inside-budget', 'proposed-once'] as const).map((id) =>
    result(id, 'pass'),
  )

  it('leaves generation 2 frozen too', () => {
    // The hash every committed artifact's v2 verdict carries.
    expect(specHash(SPEC_V2)).toBe('f027762ab4d08b35')
  })

  it('extends generation 2 by exactly the four trajectory criteria, all at threshold 1', () => {
    expect(ACCEPTANCE_V3.slice(0, ACCEPTANCE_V2.length)).toEqual(ACCEPTANCE_V2)
    expect(ACCEPTANCE_V3.map((c) => c.id).slice(ACCEPTANCE_V2.length)).toEqual([
      'read-before-propose',
      'inside-scope-gate',
      'inside-budget',
      'proposed-once',
    ])
    for (const c of ACCEPTANCE_V3) expect(c.threshold).toBe(1)
    const differing = (Object.keys(SPEC_V3) as (keyof typeof SPEC_V3)[]).filter(
      (k) => JSON.stringify(SPEC_V3[k]) !== JSON.stringify(SPEC_V2[k]),
    )
    expect(differing.sort()).toEqual(['acceptance', 'measures', 'spec_version'])
  })

  it('grades nothing new for a human-authored candidate, so its v3 verdict is its v2 verdict', () => {
    for (const id of ['positional-v0', 'count-guard-v1', 'keyed-v2', 'keyed-fallback-v1']) {
      const v2 = evaluate(all, bundle(id), { spec: SPEC_V2 })
      const v3 = evaluate(all, bundle(id), { spec: SPEC_V3 })
      expect(v3.verdict, id).toBe(v2.verdict)
      expect(v3.criteria.length, id).toBe(v2.criteria.length)
    }
  })

  it('ignores a trajectory under generation 2, and rejects on a firing predicate under generation 3', () => {
    const fired = [...clean.slice(0, 3), result('proposed-once', 'fail')]
    const v2 = evaluate(all, bundle('keyed-v2'), { spec: SPEC_V2, trajectory: fired })
    const v3clean = evaluate(all, bundle('keyed-v2'), { spec: SPEC_V3, trajectory: clean })
    const v3fired = evaluate(all, bundle('keyed-v2'), { spec: SPEC_V3, trajectory: fired })
    expect(v2.verdict).toBe('accepted-for-review')
    expect(v2.criteria.some((c) => c.id === 'proposed-once')).toBe(false)
    expect(v3clean.verdict).toBe('accepted-for-review')
    expect(v3fired.verdict).toBe('rejected')
    expect(v3fired.reason).toContain('proposed-once')
  })

  it('does not count a not-applicable predicate as a pass', () => {
    const na = [...clean.slice(1), result('read-before-propose', 'not-applicable')]
    const v3 = evaluate(all, bundle('keyed-v2'), { spec: SPEC_V3, trajectory: na })
    const c = v3.criteria.find((x) => x.id === 'read-before-propose')
    expect(c?.passed).toBe(false)
    expect(c?.rate).toBeNull()
  })

  it('changes no v1 or v2 verdict any committed run carried before it existed', () => {
    const pinned = JSON.parse(
      readFileSync(join(process.cwd(), 'tests', 'fixtures', 'lab-verdicts-before-generation-3.json'), 'utf8'),
    ) as { verdicts: Record<string, Record<string, string>> }
    const manifest = JSON.parse(
      readFileSync(join(process.cwd(), 'public', 'lab-artifacts', 'manifest.json'), 'utf8'),
    ) as { entries: { run_id: string; verdict_by_spec: Record<string, string> }[] }
    const now = new Map(manifest.entries.map((e) => [e.run_id, e.verdict_by_spec]))
    expect(Object.keys(pinned.verdicts).length).toBe(39)
    for (const [run, verdicts] of Object.entries(pinned.verdicts)) {
      expect(now.get(run)?.['1'], run).toBe(verdicts['1'])
      expect(now.get(run)?.['2'], run).toBe(verdicts['2'])
    }
  })
})
