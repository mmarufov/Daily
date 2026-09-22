import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { parseArtifact, type FunnelStepArtifact } from '@/lib/artifact'
import { buildSieve, cellState, DELIVERED } from '@/lib/sieve'

/**
 * The sieve draws one cell per candidate article and calls that the corpus.
 * That is only an honest claim if the cells and the recorded counts agree
 * exactly, so these tests check the arithmetic against the committed artifact
 * rather than against a fixture written to pass.
 */

function loadRay(): readonly FunnelStepArtifact[] {
  const path = join(
    process.cwd(),
    'public',
    'artifacts',
    'prod-llm__2026-09-02__47edb50.json',
  )
  const parsed = parseArtifact(JSON.parse(readFileSync(path, 'utf8')))
  if (!parsed.ok) throw new Error(`fixture artifact is invalid: ${parsed.issues.join('; ')}`)
  const ray = parsed.value.personas.find((p) => p.key === 'ray')
  if (ray === undefined) throw new Error('fixture ray is missing from the committed artifact')
  return ray.funnel
}

describe('buildSieve', () => {
  const steps = loadRay()
  const sieve = buildSieve(steps)

  it('draws exactly one cell per candidate in the pool', () => {
    expect(sieve.total).toBe(1362)
    expect(sieve.deaths).toHaveLength(1362)
  })

  it('assigns each stage exactly the losses the scorecard recorded', () => {
    for (const [index, stage] of sieve.stages.entries()) {
      const assigned = sieve.deaths.filter((d) => d === index).length
      expect(assigned, `stage ${stage.stage}`).toBe(stage.lost)
    }
  })

  it('leaves exactly the delivered feed alive at the end', () => {
    const survivors = sieve.deaths.filter((d) => d === DELIVERED).length
    const last = sieve.stages[sieve.stages.length - 1]
    expect(survivors).toBe(last?.survivors)
    expect(survivors).toBe(50)
  })

  it('never loses or invents a cell between stages', () => {
    const accounted = sieve.stages.reduce((sum, s) => sum + s.lost, 0)
    const delivered = sieve.deaths.filter((d) => d === DELIVERED).length
    expect(accounted + delivered).toBe(sieve.total)
  })

  it('scatters deterministically, so server and client agree', () => {
    expect(buildSieve(steps).deaths).toEqual(sieve.deaths)
  })

  it('handles an empty funnel without inventing a corpus', () => {
    const empty = buildSieve([])
    expect(empty.total).toBe(0)
    expect(empty.deaths).toEqual([])
  })

  it('clamps a stage that claims more losses than there are cells left', () => {
    const inconsistent: FunnelStepArtifact[] = [
      {
        stage: 'pool',
        label: 'Pool',
        explanation: null,
        terminal: 0,
        survivors: 10,
        lost_entering_stage: 0,
        pass_rate: null,
        absent: false,
      },
      {
        stage: 'impossible',
        label: 'Impossible',
        explanation: null,
        terminal: 0,
        survivors: 0,
        lost_entering_stage: 99,
        pass_rate: null,
        absent: false,
      },
    ]
    const sparse = buildSieve(inconsistent)
    expect(sparse.deaths).toHaveLength(10)
    expect(sparse.deaths.every((d) => d === 1)).toBe(true)
  })
})

describe('cellState', () => {
  const last = 9

  it('marks the cells removed at the current stage, and only those', () => {
    expect(cellState(4, 4, last)).toBe('dying')
    expect(cellState(3, 4, last)).toBe('gone')
    expect(cellState(5, 4, last)).toBe('alive')
  })

  it('treats survivors at the final stage as delivered rather than merely alive', () => {
    expect(cellState(DELIVERED, last, last)).toBe('delivered')
    expect(cellState(DELIVERED, 3, last)).toBe('alive')
  })
})
