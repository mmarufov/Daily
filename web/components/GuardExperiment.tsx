'use client'

import Link from 'next/link'
import { useState } from 'react'

import type { GuardExperiment as GuardExperimentData } from '@/lib/guard-experiment'

type Variant = 'original' | 'guard'

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
        <div className="guard-toggle" role="group" aria-label="Historical comparison">
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
                {isGuard ? <span className="guard-delta">{delta > 0 ? '+' : ''}{delta.toFixed(1)} pp</span> :
                  <span className="guard-original-label">Original scorecard</span>}
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

      <div className="guard-reading" aria-live="polite">
        <p className="finding-summary-title">
          {isGuard ? 'Refusing the mismatch exposed the cost.' : 'A plausible number can hide a broken join.'}
        </p>
        <p>
          {isGuard
            ? 'The guard discarded batches with the wrong number of verdicts. Recall fell and unwanted delivery rose; retrieval recall stayed unchanged.'
            : 'The original scorer assigned verdicts by position, even when the response count differed. These quality numbers include that ambiguous association.'}
        </p>
      </div>

      <div className="guard-history">
        <div className="guard-failure-count">
          <span>{experiment.historical_test_result.failed}</span>
          <p>recorded gate failures<span>September 21 experiment</span></p>
        </div>
        <p className="finding-muted">
          The baseline was retained. This is a historical working-tree experiment;
          it does not establish the current CI result or a shipped backend guard.
        </p>
      </div>

      <details className="finding-provenance">
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
      </details>
      <div className="guard-footer">
        <p className="finding-footnote">Both charts use the same 0–100% scale. Labels remain provisional.</p>
        <Link href="/engineering" className="text-link">Read the investigation <span aria-hidden="true">↗</span></Link>
      </div>
    </div>
  )
}
