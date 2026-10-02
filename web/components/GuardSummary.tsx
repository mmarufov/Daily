import Link from 'next/link'

import { GUARD_EXPERIMENT_HREF, type GuardExperiment } from '@/lib/guard-experiment'

export function GuardSummary({ experiment }: { readonly experiment: GuardExperiment | null }) {
  const metrics = experiment ? [
    { key: 'recall_at_k_mean', label: `Capped recall@${experiment.k}`, direction: 'Higher is better' },
    { key: 'never_rate_mean', label: 'Unwanted rate', direction: 'Lower is better' },
  ] as const : []

  return (
    <section className="frame guard-summary" id="experiment" aria-labelledby="guard-summary-heading">
      <div className="guard-summary-heading">
        <div>
          <p className="eyebrow">02 / Guard experiment</p>
          <h2 id="guard-summary-heading">A safer guard. A worse score.</h2>
        </div>
      </div>

      {experiment ? <>
        <dl className="guard-summary-metrics">
          {metrics.map((metric) => (
            <div className="guard-summary-metric" key={metric.key}>
              <dt><span>{metric.label}</span><span>{metric.direction}</span></dt>
              <dd>
                <span className="guard-summary-value"><strong>{(experiment.original.summary[metric.key] * 100).toFixed(1)}%</strong><span>Original</span></span>
                <span className="guard-summary-arrow" aria-hidden="true">→</span>
                <span className="guard-summary-value" data-guard="true"><strong>{(experiment.guard.summary[metric.key] * 100).toFixed(1)}%</strong><span>With guard</span></span>
              </dd>
            </div>
          ))}
        </dl>
      </> : <p className="guard-summary-unavailable" role="status">The historical guard experiment is unavailable.</p>}

      <div className="guard-summary-links">
        <Link href="/engineering" className="text-link">Read the investigation <span aria-hidden="true">↗</span></Link>
        <a href={GUARD_EXPERIMENT_HREF} className="text-link">Inspect source hashes <span aria-hidden="true">↗</span></a>
      </div>
    </section>
  )
}
