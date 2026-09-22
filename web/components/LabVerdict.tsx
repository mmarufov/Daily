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
