import { describe, expect, it } from 'vitest'

import { computeDelta, describeDelta, formatValue, isMissing, MATERIALITY_THRESHOLD } from '@/lib/format'
import { resolveMetric } from '@/lib/metrics'

describe('formatValue', () => {
  it('renders fractions as percentages', () => {
    expect(formatValue(0.2297, 'fraction')).toBe('23.0%')
  })

  it('renders a missing value as a dash, never as zero', () => {
    expect(formatValue(null, 'fraction')).toBe('—')
    expect(formatValue(undefined, 'count')).toBe('—')
    expect(formatValue(0, 'fraction')).toBe('0.0%')
  })

  it('distinguishes zero cost from unknown cost', () => {
    expect(formatValue(0, 'usd')).toBe('$0')
    expect(formatValue(null, 'usd')).toBe('—')
  })

  it('treats NaN as missing', () => {
    expect(isMissing(Number.NaN)).toBe(true)
  })
})

describe('computeDelta', () => {
  it('expresses a fraction change in percentage points, not percent', () => {
    const delta = computeDelta(0.2297, 0.3796, 'recall_at_k')
    // 0.2297 -> 0.3796 is +15.0 points. It is NOT "+65%".
    expect(delta.display).toBe('+15.0 pp')
    expect(delta.unit).toBe('pp')
    expect(delta.raw).toBeCloseTo(0.1499, 10)
  })

  it('reads a fall in an unwanted-content rate as an improvement', () => {
    const delta = computeDelta(0.2694, 0.05, 'never_rate')
    expect(delta.verdict).toBe('better')
    expect(delta.display).toBe('−21.9 pp')
  })

  it('reads a rise in recall as an improvement and a fall as a regression', () => {
    expect(computeDelta(0.2, 0.3, 'recall_at_k').verdict).toBe('better')
    expect(computeDelta(0.3, 0.2, 'recall_at_k').verdict).toBe('worse')
  })

  it('reads cheaper and faster as better', () => {
    expect(computeDelta(0.26526, 0.03709, 'cost_usd_total').verdict).toBe('better')
    expect(computeDelta(2.581, 0.021, 'latency_s').verdict).toBe('better')
  })

  it('claims no direction for a metric that has none', () => {
    expect(computeDelta(10, 12, 'feed_size_k').verdict).toBe('no-direction')
    expect(computeDelta(10, 12, 'personas').verdict).toBe('no-direction')
  })

  it('claims no direction for an unrecognised metric', () => {
    const delta = computeDelta(1, 2, 'some_future_metric')
    expect(delta.verdict).toBe('no-direction')
    expect(resolveMetric('some_future_metric').known).toBe(false)
  })

  it('refuses to compute a delta against a missing value', () => {
    const delta = computeDelta(null, 0.4, 'recall_at_k')
    expect(delta.verdict).toBe('not-computable')
    expect(delta.raw).toBeNull()
    expect(delta.reason).toContain('nothing to subtract')
  })

  it('applies the fixed materiality cutoff without calling it significance', () => {
    expect(computeDelta(0.2, 0.2 + MATERIALITY_THRESHOLD, 'recall_at_k').material).toBe(true)
    expect(computeDelta(0.2, 0.21, 'recall_at_k').material).toBe(false)
    expect(describeDelta(0.2, 0.25, 'recall_at_k')).toContain('not a significance test')
  })

  it('reports an unchanged metric as unchanged rather than better', () => {
    expect(computeDelta(0.4001, 0.4001, 'recall_at_retrieval').verdict).toBe('unchanged')
  })
})

describe('metric definitions', () => {
  it('keeps capped and raw recall as separate metrics', () => {
    const capped = resolveMetric('recall_at_k')
    const raw = resolveMetric('raw_recall_at_k')
    expect(capped.key).not.toBe(raw.key)
    expect(capped.formula).toContain('min(n_must_see, k)')
    expect(raw.formula).toContain('/ n_must_see')
  })

  it('resolves summary aggregate suffixes to the base metric', () => {
    const mean = resolveMetric('never_rate_mean')
    expect(mean.known).toBe(true)
    expect(mean.aggregate).toBe('mean')
    expect(mean.direction).toBe('lower-better')
    expect(resolveMetric('recall_at_k_min').aggregate).toBe('min')
  })

  it('marks metrics the harness may legitimately not report', () => {
    expect(resolveMetric('judge_precision').nullable).toBe(true)
    expect(resolveMetric('false_major_rate').appliesOnly).toContain('quiet')
  })
})
