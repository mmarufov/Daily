import { wrongOnRecorded, type LiveCase, type LiveGrading, type LiveOutcome, type SandboxSummary } from '@/lib/lab/live'

/**
 * Everything a finished run reported that the console has no room for: the
 * recorded cases it got wrong, the six criteria, and the microVM's own
 * account of itself.
 *
 * Every value is read off the run. A value the run did not report is labelled
 * "not measured" rather than drawn as zero.
 */
export function RunDetail({ runId, outcome }: { runId: string; outcome: LiveOutcome }) {
  const grading = outcome.grading ?? null
  return (
    <div className="mt-6 flex flex-col gap-12">
      {grading !== null && grading.cases.length > 0 ? (
        <>
          <Recorded grading={grading} />
          <Criteria grading={grading} />
        </>
      ) : null}
      <Sandbox sandbox={outcome.sandbox ?? null} />
      <p className="m-0 text-[0.8125rem] text-ink-40">
        This result, as the API returns it:{' '}
        <a href={`/api/lab/run/${runId}`} className="data link break-all">
          /api/lab/run/{runId}
        </a>
      </p>
    </div>
  )
}

const DID: Record<LiveCase['status'], string> = {
  correct: 'handled it correctly',
  'wrong-association': 'produced an association the evaluator could not accept',
  'should-have-refused': 'produced verdicts where none could be recovered, instead of refusing',
  'should-have-parsed': 'refused a response it should have read',
  crashed: 'crashed',
  timeout: 'ran out of time',
  'missing-record': 'produced no record at all',
  'not-applicable': 'was not scored here',
}

function Recorded({ grading }: { grading: LiveGrading }) {
  const wrong = wrongOnRecorded(grading)
  if (wrong.length === 0) return null
  return (
    <section className="flex flex-col gap-3">
      <h3 className="label-lg m-0">Recorded cases it got wrong · {wrong.length}</h3>
      <ul className="m-0 flex list-none flex-col border-y border-rule p-0">
        {wrong.slice(0, 8).map((c) => (
          <li key={c.case_id} className="grid gap-x-6 border-b border-rule py-2.5 text-[0.8125rem] last:border-b-0 sm:grid-cols-[15rem_minmax(0,1fr)]">
            <span className="data text-ink">{c.case_id}</span>
            <span className="text-ink-60">
              It {DID[c.status]}
              {c.detail !== '' && c.detail !== c.why ? `: ${c.detail}` : ''}.{' '}
              <span className="text-ink-40" data-verbatim>
                {c.why}
              </span>
            </span>
          </li>
        ))}
      </ul>
      {wrong.length > 8 ? (
        <p className="m-0 text-[0.8125rem] text-ink-40">
          The first 8 of {wrong.length}. Every case is in the API response linked below.
        </p>
      ) : null}
    </section>
  )
}

function Criteria({ grading }: { grading: LiveGrading }) {
  return (
    <section className="-mx-5 overflow-x-auto px-5 md:mx-0 md:px-0">
      <table className="w-full min-w-md border-collapse text-[0.8125rem]">
        <caption className="label-lg pb-3 text-left">The {grading.criteria.length} acceptance criteria</caption>
        <thead>
          <tr className="border-b border-rule-strong text-left">
            <th scope="col" className="py-2 pr-3 font-medium text-ink-40">Criterion</th>
            <th scope="col" className="py-2 pr-3 text-right font-medium text-ink-40">Satisfied</th>
            <th scope="col" className="py-2 text-right font-medium text-ink-40">Result</th>
          </tr>
        </thead>
        <tbody>
          {grading.criteria.map((c) => (
            <tr key={c.id} className="border-b border-rule align-top">
              <th scope="row" className="py-3 pr-3 text-left font-normal">
                <span className="data text-ink">{c.id}</span>
                <span className="block max-w-lg pt-1 text-ink-60" data-verbatim>
                  {c.question}
                </span>
              </th>
              <td className="data py-3 pr-3 text-right text-ink-60">
                {c.applicable === 0 ? <span className="font-sans text-unknown">nothing applicable</span> : `${c.satisfied}/${c.applicable}`}
              </td>
              <td className={`py-3 text-right ${c.passed ? 'text-ink' : 'text-signal'}`}>{c.passed ? 'met' : 'not met'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}

const NOT_MEASURED = 'not measured'

function ms(value: number | null): string {
  if (value === null) return NOT_MEASURED
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value} ms`
}

function Sandbox({ sandbox }: { sandbox: SandboxSummary | null }) {
  if (sandbox === null) {
    return (
      <section className="flex flex-col gap-2">
        <h3 className="label-lg m-0">The microVM</h3>
        <p className="m-0 text-[0.875rem] text-unknown">This run reported no microVM evidence.</p>
      </section>
    )
  }
  const held = sandbox.isolation.filter((p) => p.held).length
  const rows: [string, string, string?][] = [
    ['Sandbox', sandbox.sandbox_id, 'the platform’s own id for this microVM'],
    ['Region', sandbox.region],
    ['Network policy applied', sandbox.network_policy, 'read back off the microVM, not the value requested'],
    ['Booted in', ms(sandbox.boot_ms)],
    ['Harness ran for', ms(sandbox.wall_clock_ms)],
    ['Active CPU', ms(sandbox.active_cpu_ms), 'as the platform metered it'],
  ]
  return (
    <section className="flex flex-col gap-4">
      <h3 className="label-lg m-0">The microVM</h3>
      <dl className="m-0 grid gap-x-8 gap-y-4 text-[0.8125rem] sm:grid-cols-2 lg:grid-cols-3">
        {rows.map(([term, value, note]) => (
          <div key={term} className="min-w-0">
            <dt className="text-ink-40">{term}</dt>
            <dd className={`data m-0 mt-0.5 break-all ${value === NOT_MEASURED ? 'text-unknown' : 'text-ink'}`}>
              {value}
              {note !== undefined ? <span className="block pt-1 font-sans text-[0.75rem] text-ink-40">{note}</span> : null}
            </dd>
          </div>
        ))}
      </dl>
      <div>
        <p className={`m-0 text-[0.875rem] ${held === sandbox.isolation.length ? 'text-ink' : 'text-signal'}`}>
          {held} of {sandbox.isolation.length} isolation probes held, run inside the same microVM after the parser.
        </p>
        <ul className="m-0 mt-1.5 flex list-none flex-col gap-1 p-0 text-[0.8125rem] text-ink-60">
          {sandbox.isolation.map((p) => (
            <li key={p.name}>
              <span className={p.held ? 'text-ink' : 'text-signal'}>{p.held ? 'held' : 'failed'}</span>{' '}
              <span className="data">{p.name}</span>: {p.expectation}
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
