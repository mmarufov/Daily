import type { Artifact } from '@/lib/artifact'
import { HEADLINE_METRICS, SECONDARY_METRICS, summaryValue, weakestPersona } from '@/lib/aggregate'
import { computeDelta, describeDelta, formatValue } from '@/lib/format'
import { resolveMetric } from '@/lib/metrics'
import { personaName } from '@/lib/personas'

interface MetricTableProps {
  readonly primary: Artifact
  readonly comparison: Artifact | null
  /** False when the two runs cannot be compared; deltas are then suppressed. */
  readonly showDeltas: boolean
  readonly personaKey: string | undefined
}

export function MetricTable({ primary, comparison, showDeltas, personaKey }: MetricTableProps) {
  const metrics = [...HEADLINE_METRICS, ...SECONDARY_METRICS]

  const read = (artifact: Artifact | null, metric: string): number | null => {
    if (artifact === null) return null
    if (personaKey !== undefined) {
      const persona = artifact.personas.find((p) => p.key === personaKey)
      return persona?.metrics[metric] ?? null
    }
    return summaryValue(artifact, metric, 'mean')
  }

  return (
    <table className="w-full border-collapse text-xs">
      <caption className="sr-only">
        {personaKey === undefined
          ? 'Evaluation metrics, averaged across the ten reader fixtures'
          : `Evaluation metrics for reader fixture ${personaName(personaKey)}`}
        {comparison !== null && showDeltas ? ', with the comparison run’s difference' : ''}
      </caption>
      <thead>
        <tr className="border-b border-ink-40 text-left">
          <th scope="col" className="label py-2 pr-3 text-ink-40">
            Metric
          </th>
          <th scope="col" className="label py-2 pr-3 text-right text-ink-40">
            {primary.provenance.runner}
          </th>
          {comparison !== null ? (
            <th scope="col" className="label py-2 pr-3 text-right text-ink-40">
              {comparison.provenance.runner}
            </th>
          ) : null}
          {comparison !== null && showDeltas ? (
            <th scope="col" className="label py-2 pr-3 text-right text-ink-40">
              Difference
            </th>
          ) : null}
          {personaKey === undefined ? (
            <th scope="col" className="label py-2 text-right text-ink-40">
              Weakest fixture
            </th>
          ) : null}
        </tr>
      </thead>
      <tbody>
        {metrics.map((metric) => {
          const def = resolveMetric(metric)
          const a = read(primary, metric)
          const b = read(comparison, metric)
          const delta = comparison !== null ? computeDelta(a, b, metric) : null
          const weakest =
            personaKey === undefined ? weakestPersona(primary.personas, metric, def.direction) : null

          const bothMissing = a === null && (comparison === null || b === null)
          if (bothMissing && comparison !== null) return null

          return (
            <tr key={metric} className="border-b border-rule align-top">
              <th scope="row" className="py-2.5 pr-3 text-left font-normal">
                <span className="text-ink">{def.label}</span>
                {def.appliesOnly !== undefined ? (
                  <span className="ml-1.5 text-ink-40">({def.appliesOnly})</span>
                ) : null}
                {/* The secondary metrics are reference rows; their definitions
                    live in the glossary rather than on every line. */}
                {(HEADLINE_METRICS as readonly string[]).includes(metric) ? (
                  <span className="block max-w-md pt-1 text-ink-40">{def.short}</span>
                ) : null}
              </th>
              <td className="py-2.5 pr-3 text-right tabular-nums">
                {formatValue(a, def.kind)}
                {a === null ? <span className="sr-only">not reported</span> : null}
              </td>
              {comparison !== null ? (
                <td className="py-2.5 pr-3 text-right tabular-nums">{formatValue(b, def.kind)}</td>
              ) : null}
              {comparison !== null && showDeltas && delta !== null ? (
                <td className="py-2.5 pr-3 text-right tabular-nums">
                  <DeltaCell
                    text={delta.display}
                    verdict={delta.verdict}
                    material={delta.material}
                    description={describeDelta(a, b, metric)}
                  />
                </td>
              ) : null}
              {personaKey === undefined ? (
                <td className="py-2.5 text-right text-xs tabular-nums text-ink-60">
                  {weakest === null ? '—' : `${weakest.key} ${formatValue(weakest.value, def.kind)}`}
                </td>
              ) : null}
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function DeltaCell({
  text,
  verdict,
  material,
  description,
}: {
  text: string
  verdict: string
  material: boolean
  description: string
}) {
  const colour =
    verdict === 'better'
      ? 'text-ink'
      : verdict === 'worse'
        ? 'text-signal'
        : 'text-ink-40'

  return (
    <span className={colour} title={description}>
      <span aria-hidden="true">{text}</span>
      {material ? <span aria-hidden="true" className="ml-1 text-[10px]">●</span> : null}
      <span className="sr-only">{description}</span>
    </span>
  )
}
