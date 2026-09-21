/**
 * Number formatting and delta arithmetic for evaluation metrics.
 *
 * Two rules drive every function here:
 *
 * 1. A missing value is missing. It is never coerced to zero, and a delta
 *    against a missing value is not computable rather than equal to the other
 *    side.
 * 2. A fraction changing from 0.23 to 0.38 has moved +15 percentage points.
 *    Calling that "+65%" is a different statement about a different quantity,
 *    so fraction deltas are always expressed in percentage points and labelled.
 */

import { resolveMetric, type MetricDirection, type MetricKind } from './metrics'

/**
 * The materiality threshold used by backend/evals/compare.py. It is a fixed
 * cutoff chosen by the harness author, not a statistical test: the harness runs
 * ten persona fixtures with no variance estimate, so nothing here supports a
 * significance claim. The UI must say "material" and never "significant".
 */
export const MATERIALITY_THRESHOLD = 0.02

/** Tolerance for the threshold comparison; see computeDelta. */
export const MATERIALITY_EPSILON = 1e-9

export type MetricValue = number | null | undefined

export function isMissing(value: MetricValue): value is null | undefined {
  return value === null || value === undefined || Number.isNaN(value)
}

export function formatValue(value: MetricValue, kind: MetricKind): string {
  if (isMissing(value)) return '—'
  switch (kind) {
    case 'fraction':
      return `${(value * 100).toFixed(1)}%`
    case 'usd':
      return value === 0 ? '$0' : `$${value.toFixed(value < 0.01 ? 4 : 3)}`
    case 'seconds':
      return `${value.toFixed(3)}s`
    case 'count':
      return Number.isInteger(value) ? String(value) : value.toFixed(2)
  }
}

export type DeltaVerdict = 'better' | 'worse' | 'unchanged' | 'not-computable' | 'no-direction'

export interface Delta {
  /** Raw arithmetic difference, b - a, in the metric's native units. */
  readonly raw: number | null
  /** Human-readable difference, in percentage points for fractions. */
  readonly display: string
  /** Unit word for the difference, e.g. "pp" or "calls". */
  readonly unit: string
  readonly verdict: DeltaVerdict
  /** True when |raw| meets compare.py's fixed materiality cutoff. */
  readonly material: boolean
  /** Why the delta could not be computed, when applicable. */
  readonly reason?: string
}

const NOT_COMPUTABLE: Omit<Delta, 'reason'> = {
  raw: null,
  display: '—',
  unit: '',
  verdict: 'not-computable',
  material: false,
}

export function computeDelta(a: MetricValue, b: MetricValue, metricKey: string): Delta {
  const def = resolveMetric(metricKey)

  if (isMissing(a) || isMissing(b)) {
    return {
      ...NOT_COMPUTABLE,
      reason: isMissing(a) && isMissing(b)
        ? 'Neither run reported this metric.'
        : `Only ${isMissing(a) ? 'the comparison run' : 'the baseline run'} reported this metric, so there is nothing to subtract.`,
    }
  }

  const raw = b - a
  const magnitude = Math.abs(raw)
  // A delta that is mathematically exactly at the cutoff must count as
  // material. Comparing binary floats with a bare >= does not reliably give
  // that -- (0.2 + 0.02) - 0.2 is slightly under 0.02 -- so the comparison
  // carries a tolerance far smaller than any real metric difference.
  const material = magnitude >= MATERIALITY_THRESHOLD - MATERIALITY_EPSILON

  let display: string
  let unit: string
  if (def.kind === 'fraction') {
    unit = 'pp'
    display = `${raw >= 0 ? '+' : '−'}${(magnitude * 100).toFixed(1)} pp`
  } else if (def.kind === 'usd') {
    unit = 'USD'
    display = `${raw >= 0 ? '+' : '−'}$${magnitude.toFixed(magnitude < 0.01 ? 4 : 3)}`
  } else if (def.kind === 'seconds') {
    unit = 's'
    display = `${raw >= 0 ? '+' : '−'}${magnitude.toFixed(3)}s`
  } else {
    unit = ''
    display = `${raw >= 0 ? '+' : '−'}${Number.isInteger(magnitude) ? magnitude : magnitude.toFixed(2)}`
  }

  return { raw, display, unit, verdict: verdictFor(raw, def.direction), material }
}

function verdictFor(raw: number, direction: MetricDirection): DeltaVerdict {
  if (raw === 0) return 'unchanged'
  if (direction === 'neutral') return 'no-direction'
  if (direction === 'higher-better') return raw > 0 ? 'better' : 'worse'
  return raw > 0 ? 'worse' : 'better'
}

/** Accessible sentence describing a delta, for screen readers and tooltips. */
export function describeDelta(a: MetricValue, b: MetricValue, metricKey: string): string {
  const def = resolveMetric(metricKey)
  const delta = computeDelta(a, b, metricKey)
  if (delta.verdict === 'not-computable') return delta.reason ?? 'Not computable.'
  if (delta.verdict === 'unchanged') return `${def.label} is unchanged.`
  if (delta.verdict === 'no-direction') {
    return `${def.label} changed by ${delta.display}. This metric has no better-or-worse direction.`
  }
  const better = delta.verdict === 'better'
  const materiality = delta.material
    ? 'past compare.py’s fixed ±0.02 materiality cutoff'
    : 'within compare.py’s fixed ±0.02 materiality cutoff'
  return `${def.label} moved ${delta.display}, which is ${better ? 'better' : 'worse'} for this metric, ${materiality}. This is a fixed cutoff, not a significance test.`
}
