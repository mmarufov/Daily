import type { LabRun } from '@/lib/lab/artifact'

/**
 * Colour rule, unchanged from the rest of the site: ink is what worked,
 * vermilion is loss, slate is what cannot be established. An `incomplete` run
 * is slate rather than red, because "we could not tell" is a different fact
 * from "it was wrong" — and conflating them is how missing evidence starts
 * reading as a result.
 */
const TONE: Record<LabRun['verdict'], { fill: string; text: string; label: string }> = {
  'accepted-for-review': { fill: 'bg-ink', text: 'text-paper', label: 'Accepted for review' },
  rejected: { fill: 'bg-signal', text: 'text-paper', label: 'Rejected' },
  incomplete: { fill: 'bg-unknown', text: 'text-paper', label: 'Incomplete' },
  failed: { fill: 'bg-unknown', text: 'text-paper', label: 'Failed' },
  cancelled: { fill: 'bg-rule-strong', text: 'text-paper', label: 'Cancelled' },
}

export function VerdictBadge({ verdict, small }: { verdict: LabRun['verdict']; small?: boolean }) {
  const tone = TONE[verdict]
  return (
    <span
      className={`label inline-block ${tone.fill} ${tone.text} ${small === true ? 'px-1.5 py-0.5' : 'px-2.5 py-1.5'}`}
    >
      {tone.label}
    </span>
  )
}

export function CriteriaTable({ run }: { run: LabRun }) {
  return (
    <div className="relative -mx-5 overflow-x-auto px-5 md:mx-0 md:px-0">
      <table className="w-full min-w-md border-collapse text-xs">
        <caption className="sr-only">
          Acceptance criteria, how many cases each applied to, and whether it was satisfied
        </caption>
        <thead>
          <tr className="border-b border-ink-40 text-left">
            <th scope="col" className="label py-2 pr-3 text-ink-40">Criterion</th>
            <th scope="col" className="label py-2 pr-3 text-right text-ink-40">Satisfied</th>
            <th scope="col" className="label py-2 text-right text-ink-40">Result</th>
          </tr>
        </thead>
        <tbody>
          {run.criteria.map((c) => (
            <tr key={c.id} className="border-b border-rule align-top">
              <th scope="row" className="py-2.5 pr-3 text-left font-normal">
                <span className="text-ink">{c.id}</span>
                <span className="block max-w-lg pt-1 text-ink-40">{c.question}</span>
              </th>
              <td className="py-2.5 pr-3 text-right text-ink-60">
                {c.applicable === 0 ? (
                  <span className="text-unknown">nothing applicable</span>
                ) : (
                  `${c.satisfied}/${c.applicable}`
                )}
              </td>
              <td className={`py-2.5 text-right ${c.passed ? 'text-ink' : 'text-signal'}`}>
                {c.passed ? 'met' : c.rate === null ? 'not established' : 'not met'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function Counterexample({ run }: { run: LabRun }) {
  const x = run.smallest_counterexample
  if (x === null) return null
  return (
    <div className="border border-signal bg-paper-secondary p-4">
      <p className="label m-0 text-signal">Smallest counterexample</p>
      <p className="headline m-0 mt-2 text-base">{x.article_title}</p>
      <dl className="m-0 mt-3 grid gap-x-8 gap-y-2 text-xs sm:grid-cols-3">
        <div>
          <dt className="label m-0 text-ink-40">Article</dt>
          <dd className="m-0 mt-0.5 text-ink">{x.article_id}</dd>
        </div>
        <div>
          <dt className="label m-0 text-ink-40">Verdict it was given</dt>
          <dd className="m-0 mt-0.5 text-ink">
            score {x.expected.score.toFixed(2)} · {x.expected.relevant ? 'relevant' : 'not relevant'}
          </dd>
        </div>
        <div>
          <dt className="label m-0 text-ink-40">Verdict it received</dt>
          <dd className="m-0 mt-0.5 text-signal">
            {x.actual === null
              ? 'none at all'
              : `score ${x.actual.score === null ? 'unusable' : x.actual.score.toFixed(2)} · ${x.actual.relevant ? 'relevant' : 'not relevant'}`}
          </dd>
        </div>
      </dl>
      {x.actual !== null && x.actual.reason !== '' ? (
        <p className="lede m-0 mt-3 text-base text-ink-60">&ldquo;{x.actual.reason}&rdquo;</p>
      ) : null}
    </div>
  )
}

export function Timeline({ run }: { run: LabRun }) {
  return (
    <ol className="m-0 flex list-none flex-col gap-px border-y border-rule p-0">
      {run.attempts.map((a, index) => {
        const uncertain = a.status === 'unknown-outcome'
        return (
          <li key={a.attempt_id} className="grid gap-2 py-2.5 sm:grid-cols-[3rem_9rem_1fr]">
            <span className="band-index">{String(index + 1).padStart(2, '0')}</span>
            <span className={`label ${uncertain ? 'text-unknown' : a.status === 'succeeded' ? 'text-ink' : 'text-signal'}`}>
              {a.status}
            </span>
            <span className="text-xs text-ink-60">
              {a.note}
              <span className="block pt-1 text-ink-40">
                {a.runner} · started {a.started_at}
                {a.ended_at === 'unknown' ? ' · no end recorded' : ` · ended ${a.ended_at}`}
              </span>
            </span>
          </li>
        )
      })}
    </ol>
  )
}
