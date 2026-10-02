'use client'

import Link from 'next/link'
import { AnimatedDetails } from '@/components/AnimatedDetails'
import { MotionContent } from '@/components/MotionContent'
import { useState } from 'react'

import type { GuardExperiment as GuardExperimentData } from '@/lib/guard-experiment'

type Variant = 'original' | 'guard'

const READINGS = {
  original: {
    title: 'A plausible number can hide a broken join.',
    detail: 'The original scorer assigned verdicts by position despite count mismatches; these quality scores include that ambiguous association.',
  },
  guard: {
    title: 'Refusing the mismatch exposed the cost.',
    detail: 'Discarding mismatched batches lowered recall and raised unwanted delivery. Retrieval recall stayed unchanged.',
  },
} as const

export function GuardExperiment({ experiment }: { readonly experiment: GuardExperimentData | null }) {
  const [variant, setVariant] = useState<Variant>('original')
  if (experiment === null) {
    return <div className="finding-unavailable" role="status">The historical guard experiment is unavailable.</div>
  }
  const metrics = [
    { id: 'recall', key: 'recall_at_k_mean', label: `Capped recall@${experiment.k}`, direction: 'Higher is better' },
    { id: 'unwanted', key: 'never_rate_mean', label: 'Unwanted rate', direction: 'Lower is better' },
  ] as const
  const current = experiment[variant].summary
  const isGuard = variant === 'guard'

  return (
    <div className="finding-panel guard-panel" data-testid="guard-experiment-panel">
      <div className="guard-toolbar">
        <div className="guard-toggle" data-variant={variant} role="group" aria-label="Historical comparison">
          <button type="button" aria-pressed={!isGuard} onClick={() => setVariant('original')}>Original</button>
          <button type="button" aria-pressed={isGuard} onClick={() => setVariant('guard')}>Guard experiment</button>
        </div>
        <p className="guard-date">Recorded September 21, 2026</p>
      </div>

      <div className="guard-metrics" aria-live="polite">
        {metrics.map((metric) => {
          const value = current[metric.key]
          const original = experiment.original.summary[metric.key]
          const delta = (value - original) * 100
          return (
            <figure className="guard-metric" key={metric.id} data-testid={`guard-metric-${metric.id}`}>
              <figcaption>
                <span className="guard-metric-name">{metric.label}</span>
                <span className="guard-metric-direction">{metric.direction}</span>
              </figcaption>
              <div className="guard-metric-value">
                <span>{(value * 100).toFixed(1)}<span className="guard-percent">%</span></span>
                <span className="guard-value-note">
                  <span className="guard-original-label" data-active={!isGuard} aria-hidden={isGuard} inert={isGuard}>Original scorecard</span>
                  <span className="guard-delta" data-active={isGuard} aria-hidden={!isGuard} inert={!isGuard}>{delta > 0 ? '+' : ''}{delta.toFixed(1)} pp</span>
                </span>
              </div>
              <div className="guard-chart" aria-hidden="true">
                <div className="guard-chart-fill" data-guard={isGuard} style={{ width: `${value * 100}%` }} />
                {isGuard ? <div className="guard-chart-origin" style={{ left: `${original * 100}%` }} /> : null}
              </div>
              <div className="guard-axis" aria-hidden="true"><span>0%</span><span>100%</span></div>
              <p className="sr-only">{isGuard ? 'Guard experiment' : 'Original'}, {(value * 100).toFixed(2)} percent, on a scale from zero to one hundred percent.</p>
            </figure>
          )
        })}
      </div>

      {/* Both readings determine intrinsic height; only the active one is accessible. */}
      <MotionContent changeKey={variant} className="guard-reading" aria-live="polite">
        {(Object.keys(READINGS) as Variant[]).map((key) => (
          <div key={key} className="guard-reading-state" data-active={variant === key} aria-hidden={variant !== key} inert={variant !== key}>
            <p className="finding-summary-title">{READINGS[key].title}</p>
            <p>{READINGS[key].detail}</p>
          </div>
        ))}
      </MotionContent>

      <div className="guard-history">
        <p className="guard-failure-count">
          <strong>{experiment.historical_test_result.failed} recorded gate failures</strong>
        </p>
        <p className="finding-muted">
          Baseline retained. This historical working-tree experiment does not establish
          current CI status or a shipped backend guard.
        </p>
      </div>

      <AnimatedDetails className="finding-provenance">
        <summary>Experiment provenance</summary>
        <div className="finding-provenance-body">
          <p>
            Corpus {experiment.snapshot}, {experiment.fixtures} fixtures, k={experiment.k}.
            {' '}Reported cache misses: {experiment.original.summary.cache_misses_total} original,
            {' '}{experiment.guard.summary.cache_misses_total} guard.
            {' '}Offline replay is reported by the historical note; the original scorecard does not record execution mode.
          </p>
          <p>
            The guard file records revision <code>{experiment.guard.source.recorded_git_sha}</code>.
            {' '}That is the base checkout, not a verified commit of the tested guard.
            Exact working-tree implementation bytes remain unknown.
          </p>
          <a href="/experiments/batch-alignment.json" className="text-link">Inspect summary and source hashes ↗</a>
        </div>
      </AnimatedDetails>
      <div className="guard-footer">
        <p className="finding-footnote">Both charts use the same 0–100% scale. Labels remain provisional.</p>
        <Link href="/engineering" className="text-link">Read the investigation <span aria-hidden="true">↗</span></Link>
      </div>
    </div>
  )
}
