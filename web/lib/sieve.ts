/**
 * The sieve: one cell per candidate article, not one bar per stage.
 *
 * `FunnelStepArtifact.survivors` is already the reconstructed survivorship
 * curve (see lib/funnel.ts — the harness stores each article once at the
 * furthest stage it reached, so raw tallies read as a funnel that grows).
 * This module turns that curve into a per-candidate assignment so the pipeline
 * can be drawn at 1:1 with the corpus instead of summarised into rectangles.
 *
 * Two properties matter and both are asserted in tests/unit/sieve.test.ts:
 *
 *  1. The cell count equals the pool exactly. A field of 1,362 marks is a
 *     claim about the corpus; rounding it to a tidy grid would make it a
 *     decoration instead.
 *  2. The number of cells assigned to each stage equals that stage's recorded
 *     loss. Nothing is invented and nothing is dropped.
 *
 * What is NOT claimed: *which* article each cell is. The harness records how
 * many candidates a stage removed, not an ordering over them, so cells are
 * scattered by a deterministic hash. The scatter is presentation — it makes
 * thinning legible as density rather than as a shrinking block — and the
 * component says so on the page.
 */

import type { FunnelStepArtifact } from './artifact'

export interface SieveStage {
  readonly stage: string
  readonly label: string
  readonly explanation: string | null
  /** Candidates still in the pipeline after this stage. */
  readonly survivors: number
  /** Candidates removed on the way into this stage. */
  readonly lost: number
  readonly passRate: number | null
  /** True when the source scorecard carried no tally for this stage. */
  readonly reconstructed: boolean
}

export interface Sieve {
  /** Size of the candidate pool: the number of cells. */
  readonly total: number
  readonly stages: readonly SieveStage[]
  /**
   * Per-cell stage index at which that candidate was removed. Cells that
   * reached the delivered feed carry `DELIVERED`.
   */
  readonly deaths: readonly number[]
}

/** Sentinel for a candidate that survived every stage. */
export const DELIVERED = Number.MAX_SAFE_INTEGER

type RawStep = Pick<
  FunnelStepArtifact,
  'stage' | 'label' | 'explanation' | 'survivors' | 'lost_entering_stage' | 'pass_rate' | 'absent'
>

/**
 * A 32-bit integer hash. Used only to scatter cells deterministically, so the
 * same artifact always produces the same picture — including between the
 * server render and hydration, where a `Math.random()` scatter would mismatch.
 */
function hash(n: number): number {
  let x = (n + 0x9e3779b9) | 0
  x = Math.imul(x ^ (x >>> 16), 0x21f0aaad)
  x = Math.imul(x ^ (x >>> 15), 0x735a2d97)
  return (x ^ (x >>> 15)) >>> 0
}

export function buildSieve(steps: readonly RawStep[]): Sieve {
  const stages: SieveStage[] = steps.map((step) => ({
    stage: step.stage,
    label: step.label,
    explanation: step.explanation,
    survivors: step.survivors,
    lost: step.lost_entering_stage,
    passRate: step.pass_rate,
    reconstructed: step.absent,
  }))

  const total = stages[0]?.survivors ?? 0
  if (total === 0) return { total: 0, stages, deaths: [] }

  // Scatter order: indices sorted by hash. Ties are broken by index so the
  // result is a total order and therefore stable across engines.
  const order = Array.from({ length: total }, (_, i) => i)
  order.sort((a, b) => {
    const d = hash(a) - hash(b)
    return d !== 0 ? d : a - b
  })

  const deaths = new Array<number>(total).fill(DELIVERED)
  let cursor = 0
  for (let s = 0; s < stages.length; s += 1) {
    // `lost` can exceed what is left only if the source data is inconsistent;
    // clamping keeps the picture faithful to the cells that actually exist
    // rather than silently wrapping.
    const take = Math.min(stages[s]?.lost ?? 0, total - cursor)
    for (let n = 0; n < take; n += 1) {
      const cell = order[cursor]
      if (cell !== undefined) deaths[cell] = s
      cursor += 1
    }
  }

  return { total, stages, deaths }
}

export type CellState = 'alive' | 'dying' | 'gone' | 'delivered'

/** What a cell looks like when the viewer is standing at `stageIndex`. */
export function cellState(death: number, stageIndex: number, lastStage: number): CellState {
  if (death === stageIndex) return 'dying'
  if (death < stageIndex) return 'gone'
  return stageIndex >= lastStage ? 'delivered' : 'alive'
}
