'use client'

import { useState } from 'react'

import type { Grading, LabRun } from '@/lib/lab/artifact'

import { VerdictBadge } from './LabVerdict'

/**
 * The same run, under every generation of the criteria.
 *
 * This exists because a criterion was added after eight runs were published,
 * and the tempting thing to do with a new criterion is re-grade quietly and
 * show only the newest answer. That would have removed the most interesting
 * fact in the experiment: `keyed-fallback-v1` satisfied every criterion it
 * faced, and the criteria were incomplete. Showing one verdict hides that.
 * Showing both makes it the point.
 *
 * Defaults to the newest generation — that is the current claim — but opens
 * on the older one when the verdict moved, because a reader who lands on a
 * run whose verdict changed should see the change rather than have to find it.
 */
export function Gradings({ run }: { run: LabRun }) {
  const gradings = run.gradings
  const newest = gradings[gradings.length - 1]
  const moved = gradings.some((g) => g.verdict !== newest?.verdict)

  const [selected, setSelected] = useState(newest?.spec_version ?? 1)
  const active = gradings.find((g) => g.spec_version === selected) ?? newest
  if (active === undefined || newest === undefined) return null

  return (
    <div className="flex flex-col gap-5">
      {gradings.length > 1 ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <p className="label m-0 shrink-0 text-ink-40">Criteria generation</p>
          <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
            {gradings.map((g) => (
              <li key={g.spec_version}>
                <button
                  type="button"
                  onClick={() => setSelected(g.spec_version)}
                  aria-pressed={g.spec_version === selected}
                  className={`chip ${g.spec_version === selected ? 'chip-on' : ''}`}
                >
                  v{g.spec_version}
                  <span className="ml-1.5 opacity-60">{g.criteria.length} criteria</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="m-0 text-xs text-ink-40">spec {active.spec_hash}</p>
        </div>
      ) : null}

      {moved ? <Moved gradings={gradings} /> : null}

      <div className="flex flex-wrap items-center gap-3">
        <VerdictBadge verdict={active.verdict} />
        <p className="m-0 max-w-2xl text-sm text-ink-60">{active.verdict_reason}</p>
      </div>

      <CriteriaRows grading={active} />
    </div>
  )
}

/**
 * Stated plainly, because it is the finding rather than a footnote.
 *
 * Deliberately does not say which verdict is "right". Generation 2 is the
 * current claim; generation 1 is what this candidate actually faced when it
 * ran, and both are true statements about different criteria.
 */
function Moved({ gradings }: { gradings: readonly Grading[] }) {
  return (
    <div className="border-y border-signal py-3">
      <p className="m-0 max-w-3xl text-sm text-ink-60">
        <strong className="text-ink">This verdict moved between generations.</strong> The candidate
        satisfied every criterion it faced; the criteria were the thing that was incomplete. Nothing
        was re-executed to produce the second verdict — grading is a function of the records and a
        spec, so both were computed from the same run.
      </p>
      <ul className="m-0 mt-2 flex list-none flex-wrap gap-x-5 gap-y-1 p-0">
        {gradings.map((g) => (
          <li key={g.spec_version} className="flex items-center gap-2 text-xs text-ink-40">
            v{g.spec_version}
            <VerdictBadge verdict={g.verdict} small />
          </li>
        ))}
      </ul>
    </div>
  )
}

function CriteriaRows({ grading }: { grading: Grading }) {
  return (
    <div className="relative -mx-5 overflow-x-auto px-5 md:mx-0 md:px-0">
      <table className="w-full min-w-md border-collapse text-xs">
        <caption className="sr-only">
          Acceptance criteria under generation {grading.spec_version}, how many cases each applied
          to, and whether it was satisfied
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
