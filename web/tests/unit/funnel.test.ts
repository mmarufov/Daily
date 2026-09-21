import { describe, expect, it } from 'vitest'

import { buildFunnel, normaliseDropReasons, PROD_ORDER, stageOrderFor } from '@/lib/funnel'

/**
 * Persona `ray`, prod-llm, snapshot 2026-09-02, read straight from
 * backend/evals/results/47edb50-prod-llm-2026-09-02.json.
 *
 * These tallies are the reason the funnel needs reconstructing: read as
 * survivorship they say `scored` 45 and `feed` 50, i.e. a funnel that grows.
 */
const RAY_STAGE_COUNTS = {
  loaded: 198,
  pool: 1062,
  scored: 45,
  feed: 50,
  roles: 5,
  loaded_rows: 2,
} as const

describe('buildFunnel', () => {
  const funnel = buildFunnel(RAY_STAGE_COUNTS, 'prod-llm')
  const at = (stage: string) => funnel.steps.find((s) => s.stage === stage)

  it('treats stage tallies as terminal counts, not survivorship', () => {
    // The raw tally at `scored` is lower than at `feed`...
    expect(RAY_STAGE_COUNTS.scored).toBeLessThan(RAY_STAGE_COUNTS.feed)
    // ...but survivors must still decrease monotonically down the pipeline.
    const survivors = funnel.steps.map((s) => s.survivors)
    for (let i = 1; i < survivors.length; i += 1) {
      expect(survivors[i]).toBeLessThanOrEqual(survivors[i - 1] as number)
    }
  })

  it('reproduces the three counts recorded independently in the same scorecard', () => {
    // feed_size as reported by the harness
    expect(at('feed')?.survivors).toBe(50)
    // meta.served: the recency window
    expect(at('loaded_rows')?.survivors).toBe(300)
    // the documented 100-candidate cap in front of the scorer
    expect(at('scored')?.survivors).toBe(100)
  })

  it('accounts for the four needles planted on top of the 1,358-article corpus', () => {
    expect(funnel.total).toBe(1362)
    expect(funnel.total - 1358).toBe(4)
  })

  it('computes losses and pass rates between adjacent stages', () => {
    expect(at('pool')?.passRate).toBeNull()
    // 1362 in the pool, 300 returned by the recency window.
    expect(at('loaded_rows')?.lostEnteringStage).toBe(1062)
    expect(at('loaded')?.lostEnteringStage).toBe(2)
    // `prefilter` reported no tally of its own, so it carries the loss between
    // `loaded` (298 survivors) and `scored` (100).
    expect(at('prefilter')?.lostEnteringStage).toBe(198)
    expect(at('prefilter')?.passRate).toBeCloseTo(100 / 298, 10)
    expect(at('scored')?.passRate).toBe(1)
  })

  it('reconciles the loss entering a stage with that stage\u2019s drop reasons', () => {
    // drop_counts for this persona records prefilter:cap 194 and
    // prefilter:excluded 4. Their sum must equal the funnel's loss entering
    // the prefilter stage, or one of the two is being misread.
    const prefilterDrops = 194 + 4
    expect(at('prefilter')?.lostEnteringStage).toBe(prefilterDrops)
  })

  it('marks stages the harness never reported', () => {
    expect(at('prefilter')?.absent).toBe(true)
    expect(at('dedup')?.absent).toBe(true)
    expect(at('feed')?.absent).toBe(false)
  })

  it('reports stage tallies that are not in the declared order', () => {
    const withJunk = buildFunnel({ ...RAY_STAGE_COUNTS, invented_stage: 7 }, 'prod-llm')
    expect(withJunk.unrecognisedStages).toEqual(['invented_stage'])
  })

  it('selects the prototype stage order for prototype runners', () => {
    expect(stageOrderFor('proto-hybrid-judge-events')).not.toBe(PROD_ORDER)
    expect(stageOrderFor('prod-llm')).toBe(PROD_ORDER)
  })

  it('handles an empty tally map without inventing a funnel', () => {
    const empty = buildFunnel({}, 'prod-llm')
    expect(empty.total).toBe(0)
    expect(empty.steps.every((s) => s.absent)).toBe(true)
  })
})

describe('normaliseDropReasons', () => {
  const reasons = normaliseDropReasons(
    {
      'prefilter:cap': 194,
      lookback: 1062,
      blended: 45,
      rank: 38,
      'after:roles': 5,
      text_too_short: 2,
    },
    'prod-llm',
  )

  it('sorts by count descending', () => {
    expect(reasons.map((r) => r.key)[0]).toBe('lookback')
  })

  it('splits a qualified reason into group and detail', () => {
    const cap = reasons.find((r) => r.key === 'prefilter:cap')
    expect(cap?.group).toBe('prefilter')
    expect(cap?.detail).toBe('cap')
    expect(cap?.mapsToStage).toBe(true)
  })

  it('does not force non-stage mechanisms onto the stage axis', () => {
    // `lookback` is the recency window and `text_too_short` is a content
    // rejection. Neither is a declared stage, and pretending otherwise would
    // misplace the largest single source of loss in this run.
    expect(reasons.find((r) => r.key === 'lookback')?.mapsToStage).toBe(false)
    expect(reasons.find((r) => r.key === 'text_too_short')?.mapsToStage).toBe(false)
  })
})
