import {
  caughtByFault,
  wrongOnRecorded,
  type CatalogCase,
  type LiveCase,
  type LiveGrading,
  type LiveOutcome,
  type SandboxSummary,
} from '@/lib/lab/live'

import { VerdictBadge } from './LabVerdict'
import { CaseStatusMark, type CaseStatusTone } from './CaseStatusMark'

/**
 * A live run's result, in the order a visitor asks about it: did it pass,
 * what caught it, where across the 64 cases, and what the microVM reported.
 *
 * Every value is read off the run. Nothing here is computed from a guess, and
 * a value the run did not report is labelled "not measured" rather than drawn
 * as zero. Text the parser itself produced (a refusal kind, a crash message)
 * is labelled as the parser's, because a shared run link should not be able
 * to put words in the evaluator's mouth.
 */
export function LiveResult({
  runId,
  outcome,
  catalog,
}: {
  runId: string
  outcome: LiveOutcome
  catalog: readonly CatalogCase[]
}) {
  if (outcome.kind === 'rejected-by-scope') {
    return (
      <div className="flex flex-col gap-3 border-t border-signal pt-4">
        <p className="label m-0 text-signal">Refused by the scope gate</p>
        <p className="m-0 max-w-2xl text-sm text-ink-60">{outcome.detail}</p>
      </div>
    )
  }

  if (outcome.kind !== 'graded' && outcome.kind !== 'incomplete') {
    // A run id is a run id: a link can point at an investigation, whose
    // outcome is shaped differently. Say so rather than render it as this.
    return (
      <p className="m-0 max-w-2xl text-sm text-unknown">
        This run is not a candidate run started from this page, so there is no grading to show here.
      </p>
    )
  }

  const grading = outcome.grading ?? null
  return (
    <div className="flex flex-col gap-10">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          {outcome.verdict !== undefined && outcome.verdict !== null ? <VerdictBadge verdict={outcome.verdict} /> : null}
          <p className="m-0 max-w-2xl text-sm text-ink-60">{outcome.reason ?? outcome.detail}</p>
        </div>
        {grading !== null ? (
          <p className="m-0 text-xs text-ink-40">
            Graded outside the microVM under criteria generation {grading.spec_version}, spec{' '}
            {grading.spec_hash}. The parser declared{' '}
            <span className="text-ink-60">{grading.declared_protocol}</span>; that is checked, not
            believed. {outcome.verdict === 'accepted-for-review'
              ? 'Accepted means eligible for human review. A live run is not added to the published set.'
              : null}
          </p>
        ) : null}
      </div>

      {grading !== null && grading.cases.length > 0 ? (
        <>
          <Faults grading={grading} />
          <CaseGrid catalog={catalog} grading={grading} />
          <Recorded grading={grading} />
          <Criteria grading={grading} />
        </>
      ) : null}

      <Sandbox sandbox={outcome.sandbox ?? null} />

      <p className="m-0 text-xs text-ink-40">
        This result, as the API returns it:{' '}
        <a href={`/api/lab/run/${runId}`} className="link break-all">
          /api/lab/run/{runId}
        </a>
      </p>
    </div>
  )
}

/** What the parser did, in words, for each way a case can go wrong. */
const DID: Record<LiveCase['status'], string> = {
  correct: 'handled it correctly',
  // Deliberately not "gave an article the wrong verdict". Three recorded
  // batches have no ground truth at all, and the evaluator rejects any
  // association there because none can be shown correct. Its own detail,
  // printed beside this, says which of the two happened.
  'wrong-association': 'produced an association the evaluator could not accept',
  'should-have-refused': 'produced verdicts where none could be recovered, instead of refusing',
  'should-have-parsed': 'refused a response it should have read',
  crashed: 'crashed',
  timeout: 'ran out of time',
  'missing-record': 'produced no record at all',
  'not-applicable': 'was not scored here',
}

function Faults({ grading }: { grading: LiveGrading }) {
  const caught = caughtByFault(grading)
  const faults = grading.cases.filter((c) => c.origin === 'fault-injection')
  const scored = faults.filter((c) => c.applicability === 'scored')

  if (caught.length === 0) {
    const unscored = faults.length - scored.length
    return (
      <section className="flex flex-col gap-2 border-t border-rule-strong pt-4">
        <h3 className="label m-0 text-ink">No fault-injected case caught this parser</h3>
        <p className="m-0 max-w-2xl text-sm text-ink-60">
          {scored.length} of the {faults.length} faults apply to the protocol it declared, and it
          handled every one.
          {unscored > 0
            ? ` The other ${unscored} ${unscored === 1 ? 'is an association rule' : 'are association rules'} of another protocol and ${unscored === 1 ? 'was' : 'were'} not scored. Not scored is not passed.`
            : null}
        </p>
      </section>
    )
  }

  return (
    <section className="flex flex-col gap-5 border-t border-signal pt-4">
      <h3 className="label m-0 text-signal">
        Caught by {caught.length === 1 ? 'a fault-injected case' : `${caught.length} fault-injected cases`}
      </h3>
      <ol className="m-0 flex list-none flex-col gap-6 p-0">
        {caught.map((c) => (
          <li key={c.case_id} className="grid gap-x-8 gap-y-3 md:grid-cols-[minmax(0,14rem)_minmax(0,1fr)]">
            <p className="m-0 break-all font-mono text-sm text-ink">{c.case_id}</p>
            <dl className="m-0 flex min-w-0 flex-col gap-3">
              <div>
                <dt className="label m-0 text-ink-40">The fault</dt>
                <dd className="m-0 mt-1 text-sm text-ink" data-verbatim>
                  {c.why}
                </dd>
              </div>
              <div>
                <dt className="label m-0 text-ink-40">What the parser did</dt>
                <dd className="m-0 mt-1 text-sm text-signal">
                  It {DID[c.status]}.
                  {c.detail !== '' && c.detail !== c.why ? (
                    <span className="block pt-1 text-ink-60">{c.detail}</span>
                  ) : null}
                </dd>
              </div>
              {c.expected_refusal_kinds.length > 0 ? (
                <div>
                  <dt className="label m-0 text-ink-40">What a correct parser does</dt>
                  <dd className="m-0 mt-1 text-sm text-ink-60">
                    Refuses, naming it as{' '}
                    {c.expected_refusal_kinds.map((k, i) => (
                      <span key={k}>
                        {i > 0 ? (i === c.expected_refusal_kinds.length - 1 ? ' or ' : ', ') : null}
                        <span className="font-mono text-xs text-ink">{k}</span>
                      </span>
                    ))}
                    .
                    {c.observed_refusal_kind !== null ? (
                      <span className="block pt-1 text-ink-40">
                        The parser&rsquo;s own word for it:{' '}
                        <span className="font-mono text-xs">{c.observed_refusal_kind}</span>
                      </span>
                    ) : null}
                  </dd>
                </div>
              ) : null}
            </dl>
          </li>
        ))}
      </ol>
    </section>
  )
}

type CellTone = CaseStatusTone

const CELL: Record<CellTone, { className: string; label: string }> = {
  pending: { className: 'border border-rule bg-paper', label: 'not run yet' },
  correct: { className: 'bg-success', label: 'correct' },
  wrong: { className: 'bg-signal', label: 'wrong' },
  unscored: { className: 'border border-rule bg-paper-secondary', label: 'not scored, another protocol' },
  outside: { className: 'border-2 border-signal bg-paper', label: 'associated outside its declared protocol' },
}

function tone(c: LiveCase | undefined, outside: ReadonlySet<string>): CellTone {
  if (c === undefined) return 'pending'
  if (c.applicability === 'not-applicable') return outside.has(c.case_id) ? 'outside' : 'unscored'
  return c.status === 'correct' ? 'correct' : 'wrong'
}

/**
 * All 64 cases at once, split the way the suite is: recorded batches and
 * fault injections. Before a run every cell is hollow; the grid is the same
 * object before and after, so what changed is the result and nothing else.
 */
export function CaseGrid({ catalog, grading }: { catalog: readonly CatalogCase[]; grading: LiveGrading | null }) {
  const byId = new Map((grading?.cases ?? []).map((c) => [c.case_id, c]))
  const outside = new Set(grading?.out_of_protocol_case_ids ?? [])
  const groups = [
    { title: 'Recorded', note: 'real batches, replayed', cases: catalog.filter((c) => c.origin === 'recorded-replay') },
    { title: 'Fault-injected', note: 'each built to catch one mistake', cases: catalog.filter((c) => c.origin === 'fault-injection') },
  ]
  const used = new Set<CellTone>(grading === null ? ['pending'] : catalog.map((c) => tone(byId.get(c.case_id), outside)))

  return (
    <section className="flex flex-col gap-4" aria-label={`All ${catalog.length} cases`}>
      {groups.map((g) => (
        <div key={g.title} className="flex flex-col gap-2">
          <p className="label m-0 text-ink-40">
            {g.title} · {g.cases.length}
            <span className="ml-2 font-sans normal-case tracking-normal">{g.note}</span>
          </p>
          <ol className="live-case-grid m-0 flex list-none flex-wrap gap-[3px] p-0">
            {g.cases.map((c) => {
              const t = tone(byId.get(c.case_id), outside)
              return (
                <li
                  key={c.case_id}
                  title={`${c.case_id}: ${CELL[t].label}`}
                  data-case={c.case_id}
                  data-tone={t}
                  className={`case-status-cell ${CELL[t].className}`}
                >
                  <CaseStatusMark tone={t} />
                  <span className="sr-only">
                    {c.case_id}: {CELL[t].label}
                  </span>
                </li>
              )
            })}
          </ol>
        </div>
      ))}
      <ul className="case-status-legend" aria-hidden="true">
        {(Object.keys(CELL) as CellTone[])
          .filter((t) => used.has(t))
          .map((t) => (
            <li key={t}>
              <span className={`case-status-cell ${CELL[t].className}`} data-tone={t}>
                <CaseStatusMark tone={t} />
              </span>
              {CELL[t].label}
            </li>
          ))}
      </ul>
    </section>
  )
}

function Recorded({ grading }: { grading: LiveGrading }) {
  const wrong = wrongOnRecorded(grading)
  if (wrong.length === 0) return null
  return (
    <section className="flex flex-col gap-3">
      <h3 className="label m-0 text-ink">
        Recorded cases it got wrong · {wrong.length}
      </h3>
      <ul className="m-0 flex list-none flex-col gap-px border-y border-rule p-0">
        {wrong.slice(0, 8).map((c) => (
          <li key={c.case_id} className="grid gap-x-4 py-1.5 text-xs sm:grid-cols-[14rem_minmax(0,1fr)]">
            <span className="font-mono text-ink">{c.case_id}</span>
            <span className="text-ink-60">
              It {DID[c.status]}{c.detail !== '' && c.detail !== c.why ? `: ${c.detail}` : ''}.{' '}
              <span className="text-ink-40" data-verbatim>
                {c.why}
              </span>
            </span>
          </li>
        ))}
      </ul>
      {wrong.length > 8 ? (
        <p className="m-0 text-xs text-ink-40">
          The first 8 of {wrong.length}. Every case is in the API response linked below.
        </p>
      ) : null}
    </section>
  )
}

function Criteria({ grading }: { grading: LiveGrading }) {
  return (
    <section className="relative overflow-x-auto">
      <table className="w-full min-w-md border-collapse text-xs">
        <caption className="label pb-2 text-left text-ink-40">
          The {grading.criteria.length} acceptance criteria
        </caption>
        <thead>
          <tr className="border-b border-ink-40 text-left">
            <th scope="col" className="label py-2 pr-3 text-ink-40">Criterion</th>
            <th scope="col" className="label py-2 pr-3 text-right text-ink-40">Satisfied</th>
            <th scope="col" className="label py-2 text-right text-ink-40">Result</th>
          </tr>
        </thead>
        <tbody>
          {grading.criteria.map((c) => (
            <tr key={c.id} className="border-b border-rule align-top">
              <th scope="row" className="py-2.5 pr-3 text-left font-normal">
                <span className="text-ink">{c.id}</span>
                <span className="block max-w-lg pt-1 text-ink-40" data-verbatim>
                  {c.question}
                </span>
              </th>
              <td className="py-2.5 pr-3 text-right text-ink-60">
                {c.applicable === 0 ? (
                  <span className="text-unknown">nothing applicable</span>
                ) : (
                  `${c.satisfied}/${c.applicable}`
                )}
              </td>
              <td className={`py-2.5 text-right ${c.passed ? 'text-ink' : 'text-signal'}`}>
                {c.passed ? 'met' : 'not met'}
              </td>
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
        <h3 className="label m-0 text-ink">The microVM</h3>
        <p className="m-0 text-sm text-unknown">This run reported no microVM evidence.</p>
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
      <h3 className="label m-0 text-ink">The microVM</h3>
      <dl className="m-0 grid gap-x-8 gap-y-4 text-xs sm:grid-cols-2 lg:grid-cols-3">
        {rows.map(([term, value, note]) => (
          <div key={term} className="min-w-0">
            <dt className="label m-0 text-ink-40">{term}</dt>
            <dd className={`m-0 mt-0.5 break-all ${value === NOT_MEASURED ? 'text-unknown' : 'text-ink'}`}>
              {value}
              {note !== undefined ? (
                <span className="block pt-1 font-sans text-[11px] text-ink-40">{note}</span>
              ) : null}
            </dd>
          </div>
        ))}
      </dl>
      <div>
        <p className={`m-0 text-sm ${held === sandbox.isolation.length ? 'text-ink' : 'text-signal'}`}>
          {held} of {sandbox.isolation.length} isolation probes held, run inside the same microVM after
          the parser.
        </p>
        <ul className="m-0 mt-1.5 flex list-none flex-col gap-1 p-0 text-xs text-ink-60">
          {sandbox.isolation.map((p) => (
            <li key={p.name}>
              <span className={p.held ? 'text-ink' : 'text-signal'}>{p.held ? 'held' : 'failed'}</span>{' '}
              <span className="font-mono">{p.name}</span>: {p.expectation}
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}
