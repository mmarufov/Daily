import { HEADLINE_METRICS, SECONDARY_METRICS } from '@/lib/aggregate'
import { resolveMetric } from '@/lib/metrics'

/**
 * The full definitions, collapsed.
 *
 * The table carries a one-line gloss per metric so it can be scanned. Several
 * of these are easy to get backwards, though, and the exact wording is the
 * difference between reading a number and misreading it — so the long form is
 * kept, one click away, rather than deleted.
 */
export function Glossary() {
  const metrics = [...HEADLINE_METRICS, ...SECONDARY_METRICS]
  return (
    <details className="border border-rule bg-paper-secondary">
      <summary className="disclosure label px-4 py-3 text-ink">
        What each metric means, exactly
      </summary>
      <dl className="m-0 grid gap-x-8 gap-y-4 border-t border-rule bg-paper p-4 md:grid-cols-2">
        {metrics.map((key) => {
          const def = resolveMetric(key)
          return (
            <div key={key}>
              <dt className="label m-0 text-ink">
                {def.label}
                <span className="ml-2 text-ink-40">
                  {def.direction === 'higher-better'
                    ? 'higher is better'
                    : def.direction === 'lower-better'
                      ? 'lower is better'
                      : 'no direction'}
                </span>
              </dt>
              <dd className="m-0 mt-1 text-xs text-ink-60">{def.plain}</dd>
            </div>
          )
        })}
      </dl>
    </details>
  )
}
