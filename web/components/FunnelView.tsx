import type { Artifact, PersonaArtifact } from '@/lib/artifact'
import { aggregateFunnel, aggregateLossByStage } from '@/lib/aggregate'

interface FunnelViewProps {
  readonly artifact: Artifact
  readonly persona: PersonaArtifact | undefined
}

export function FunnelView({ artifact, persona }: FunnelViewProps) {
  const steps =
    persona !== undefined
      ? persona.funnel.map((s) => ({
          stage: s.stage,
          label: s.label,
          explanation: s.explanation,
          survivors: s.survivors,
          lostEnteringStage: s.lost_entering_stage,
          passRate: s.pass_rate,
          personasReporting: s.absent ? 0 : 1,
        }))
      : aggregateFunnel(artifact.personas, artifact.provenance.runner)

  const head = steps[0]
  const total = head?.survivors ?? 0
  const lossByStage =
    persona !== undefined
      ? new Map(Object.entries(persona.loss_by_stage).sort((a, b) => b[1] - a[1]))
      : aggregateLossByStage(artifact.personas)

  const unrecognised =
    persona !== undefined
      ? persona.unrecognised_stages
      : [...new Set(artifact.personas.flatMap((p) => p.unrecognised_stages))].sort()

  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col gap-3">
        <h3 className="meta-caps m-0 text-ink-60">Candidates surviving each stage</h3>
        <p className="m-0 max-w-2xl text-sm text-ink-60">
          The harness records each article once, at the furthest stage it reached. Survivors at a
          stage are therefore the sum of that stage&rsquo;s tally and every later one — reading the
          raw tallies as a funnel would show it growing.
          {persona === undefined ? (
            <> Totals here are persona/article pairs summed over {artifact.personas.length} fixtures, not distinct articles.</>
          ) : null}
        </p>

        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">
            Candidate funnel: survivors, articles lost entering each stage, and pass rate
          </caption>
          <thead>
            <tr className="border-b border-ink text-left">
              <th scope="col" className="py-2 pr-3 font-semibold">
                Stage
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-semibold">
                Survivors
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-semibold">
                Lost here
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-semibold">
                Pass rate
              </th>
              <th scope="col" className="py-2 font-semibold">
                <span className="sr-only">Proportion of the pool remaining</span>
                <span aria-hidden="true">Remaining</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {steps.map((step) => {
              const share = total === 0 ? 0 : step.survivors / total
              return (
                <tr key={step.stage} className="border-b border-sepia align-top">
                  <th scope="row" className="py-2.5 pr-3 text-left font-normal">
                    <span className="font-semibold">{step.label}</span>
                    {step.personasReporting === 0 ? (
                      <span className="ml-1.5 text-xs text-ink-60">(not reported)</span>
                    ) : null}
                    {step.explanation !== null ? (
                      <span className="block max-w-md pt-0.5 text-xs text-ink-60">
                        {step.explanation}
                      </span>
                    ) : null}
                  </th>
                  <td className="py-2.5 pr-3 text-right tabular-nums">
                    {step.survivors.toLocaleString()}
                  </td>
                  <td className="py-2.5 pr-3 text-right tabular-nums text-ink-60">
                    {step.lostEnteringStage === 0 ? '—' : step.lostEnteringStage.toLocaleString()}
                  </td>
                  <td className="py-2.5 pr-3 text-right tabular-nums text-ink-60">
                    {step.passRate === null ? '—' : `${(step.passRate * 100).toFixed(1)}%`}
                  </td>
                  <td className="py-2.5">
                    <span
                      aria-hidden="true"
                      className="block h-2 bg-ink-blue"
                      style={{ width: `${Math.max(share * 100, 0.4)}%` }}
                    />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>

        {unrecognised.length > 0 ? (
          <p className="m-0 text-xs text-ink-60">
            Stage tallies present in the data but absent from this runner&rsquo;s declared stage
            order, so they are excluded from the funnel above: {unrecognised.join(', ')}.
          </p>
        ) : null}
      </section>

      <section className="flex flex-col gap-3">
        <h3 className="meta-caps m-0 text-ink-60">Where wanted stories were lost</h3>
        <p className="m-0 max-w-2xl text-sm text-ink-60">
          This attributes only the must-see stories that never reached the reader. A story lost
          before the scorer could not have been rescued by better ranking.
        </p>
        {lossByStage.size === 0 ? (
          <p className="m-0 text-sm">
            No must-see losses were attributed for this selection.
          </p>
        ) : (
          <table className="w-full max-w-lg border-collapse text-sm">
            <caption className="sr-only">Must-see losses attributed by stage or mechanism</caption>
            <thead>
              <tr className="border-b border-ink text-left">
                <th scope="col" className="py-2 pr-3 font-semibold">
                  Stage or mechanism
                </th>
                <th scope="col" className="py-2 text-right font-semibold">
                  Must-see stories lost
                </th>
              </tr>
            </thead>
            <tbody>
              {[...lossByStage].map(([stage, count]) => (
                <tr key={stage} className="border-b border-sepia">
                  <th scope="row" className="py-2 pr-3 text-left font-normal font-mono text-xs">
                    {stage}
                  </th>
                  <td className="py-2 text-right tabular-nums">{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}
