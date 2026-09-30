import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { evaluate } from '@/lib/lab/evaluator'
import { parseCaseSuite, parseRecordBundle, type Case, type RecordBundle } from '@/lib/lab/records'

/**
 * The numbers the Lab is quoted by, pinned.
 *
 * lab-evaluator.test.ts checks verdicts and properties. Nothing checked the
 * counts themselves, so "positional 0/52, count guard 48/52, id-keyed 60/60,
 * 2 of 31 agent runs accepted" could drift while every verdict stayed the
 * same. Each pin below is recomputed from the committed records and exports,
 * and each has a control showing the same function reports a different number
 * when the input is wrong.
 */

const BACKEND = join(process.cwd(), '..', 'backend')
const LAB_ARTIFACTS = join(process.cwd(), 'public', 'lab-artifacts')

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

/** Correct over applicable, the form the numbers are quoted in. */
function score(bundle: RecordBundle): { correct: number; applicable: number } {
  const { counts } = evaluate(CASES, bundle)
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0)
  return { correct: counts.correct, applicable: total - counts['not-applicable'] }
}

/** Keyed by file name, which is what the /lab/<name> page is routed by. */
type AgentExport = { file: string; verdict: string }

function agentExports(): AgentExport[] {
  return readdirSync(LAB_ARTIFACTS)
    .filter((name) => name.startsWith('agent-') && name.endsWith('.json'))
    .sort()
    .map((name) => ({
      file: name.replace(/\.json$/, ''),
      verdict: (JSON.parse(readFileSync(join(LAB_ARTIFACTS, name), 'utf8')) as { verdict: string }).verdict,
    }))
}

function accepted(runs: readonly AgentExport[]): string[] {
  return runs.filter((r) => r.verdict === 'accepted-for-review').map((r) => r.file)
}

describe('the three contracts, as quoted', () => {
  it('holds 64 cases', () => {
    expect(CASES).toHaveLength(64)
  })

  it('positional: 0/52', () => {
    expect(score(loadBundle('positional-v0'))).toEqual({ correct: 0, applicable: 52 })
  })

  it('count guard: 48/52', () => {
    expect(score(loadBundle('count-guard-v1'))).toEqual({ correct: 48, applicable: 52 })
  })

  it('id-keyed: 60/60', () => {
    expect(score(loadBundle('keyed-v2'))).toEqual({ correct: 60, applicable: 60 })
  })

  it('control: one swapped association in the keyed records is no longer 60/60', () => {
    // If score() ignored associations, the id-keyed pin could never fail.
    const keyed = loadBundle('keyed-v2')
    const target = keyed.records.find(
      (r) => r.outcome === 'parsed' && r.association && Object.keys(r.association).length >= 2,
    )
    expect(target).toBeDefined()
    const original = target!.association!
    const [a, b] = Object.keys(original) as [string, string]
    const swapped = { ...original, [a]: original[b]!, [b]: original[a]! }
    const doctored: RecordBundle = {
      ...keyed,
      records: keyed.records.map((r) => (r === target ? { ...r, association: swapped } : r)),
    }
    expect(score(doctored)).not.toEqual({ correct: 60, applicable: 60 })
  })
})

describe('the agent sweep, as quoted', () => {
  const runs = agentExports()

  it('has 31 committed runs', () => {
    expect(runs).toHaveLength(31)
  })

  it('accepted exactly 2 of them for review', () => {
    expect(accepted(runs)).toEqual(['agent-k2-generous-out-02-sandbox', 'agent-k2-generous-out-06-sandbox'])
  })

  it('grades both accepted runs 60/60 from their own records, not just their export', () => {
    for (const id of ['agent-k2-generous-out-02', 'agent-k2-generous-out-06']) {
      expect(evaluate(CASES, loadBundle(id)).verdict).toBe('accepted-for-review')
      expect(score(loadBundle(id))).toEqual({ correct: 60, applicable: 60 })
    }
  })

  it('control: flipping one rejected run changes the count', () => {
    const flipped = runs.map((r) =>
      r.file === 'agent-k2-generous-out-01-sandbox' ? { ...r, verdict: 'accepted-for-review' } : r,
    )
    expect(accepted(flipped)).toHaveLength(3)
  })
})
