import Link from 'next/link'

import type { PersonaArtifact, StoryOutcome } from '@/lib/artifact'
import type { ExplorerUrl } from '@/lib/url-state'

/**
 * Every fixture, no averaging.
 *
 * The run summary reports a mean capped recall of 22.1%. Two of the ten
 * fixtures are at 0.0% and one is delivering ten explicitly unwanted stories
 * for every one it gets right, and neither fact survives being averaged. This
 * draws the composition per fixture so the failures are the first thing the
 * eye lands on, which is the entire reason the harness keeps per-fixture
 * results instead of a single score.
 *
 * Colour rule, as everywhere on this site: ink is what worked, vermilion is
 * loss, slate is what cannot be judged either way.
 */

const SEGMENTS: readonly {
  outcome: StoryOutcome
  label: string
  /** Tailwind background for the bar segment. */
  fill: string
  legend: string
}[] = [
  {
    outcome: 'delivered-wanted',
    label: 'Delivered, wanted',
    fill: 'bg-ink',
    legend: 'reached the reader and the labels say they wanted it',
  },
  {
    outcome: 'delivered-unlabelled',
    label: 'Delivered, unlabelled',
    fill: 'bg-unknown',
    legend: 'reached the reader with no ground-truth label either way',
  },
  {
    outcome: 'delivered-unwanted',
    label: 'Delivered, unwanted',
    fill: 'bg-signal',
    legend: 'reached the reader after being labelled never-wanted',
  },
  {
    outcome: 'lost-at-or-after-scorer',
    label: 'Lost at the scorer',
    fill: 'bg-signal/55',
    legend: 'wanted, survived retrieval, then lost while being ranked',
  },
  {
    outcome: 'lost-before-scorer',
    label: 'Lost before the scorer',
    fill: 'bg-signal/25',
    legend: 'wanted, and dropped before anything scored it — ranking could not have saved it',
  },
]

export interface FixtureRow {
  readonly key: string
  readonly counts: Readonly<Record<StoryOutcome, number>>
  readonly total: number
  readonly cappedRecall: number | null
  readonly href: ExplorerUrl
  readonly selected: boolean
}

export function toFixtureRows(
  personas: readonly PersonaArtifact[],
  hrefFor: (key: string) => ExplorerUrl,
  selectedKey: string | undefined,
): readonly FixtureRow[] {
  return personas.map((persona) => {
    const counts = {
      'delivered-wanted': 0,
      'delivered-unlabelled': 0,
      'delivered-unwanted': 0,
      'lost-at-or-after-scorer': 0,
      'lost-before-scorer': 0,
    } satisfies Record<StoryOutcome, number>

    for (const story of persona.stories) counts[story.outcome] += 1

    return {
      key: persona.key,
      counts,
      total: persona.stories.length,
      cappedRecall: persona.metrics.recall_at_k ?? null,
      href: hrefFor(persona.key),
      selected: persona.key === selectedKey,
    }
  })
}

export function FixtureStrip({
  rows,
  caption,
}: {
  readonly rows: readonly FixtureRow[]
  readonly caption: string
}) {
  const widest = Math.max(1, ...rows.map((r) => r.total))
  const reported = rows.map((r) => r.cappedRecall).filter((v): v is number => v !== null)
  const mean =
    reported.length === 0 ? null : reported.reduce((a, b) => a + b, 0) / reported.length

  return (
    <div className="flex flex-col gap-4">
      <ul className="m-0 flex list-none flex-col gap-px border-y border-rule p-0">
        {rows.map((row) => (
          <li key={row.key}>
            <Link
              href={row.href}
              aria-current={row.selected ? 'true' : undefined}
              className={[
                'grid grid-cols-[4.5rem_1fr_3.75rem] items-center gap-3 py-1.5 no-underline transition-colors duration-150 sm:grid-cols-[5.5rem_1fr_4.5rem]',
                row.selected ? 'bg-paper-secondary' : 'hover:bg-paper-secondary',
              ].join(' ')}
            >
              <span
                className={`text-xs ${row.selected ? 'text-ink' : 'text-ink-60'}`}
              >
                {row.key}
              </span>

              <span
                className="flex h-4 items-stretch gap-px"
                style={{ width: `${(row.total / widest) * 100}%` }}
                aria-hidden="true"
              >
                {SEGMENTS.map((segment) => {
                  const n = row.counts[segment.outcome]
                  if (n === 0) return null
                  return (
                    <span
                      key={segment.outcome}
                      className={segment.fill}
                      style={{ flexGrow: n, flexBasis: 0 }}
                      title={`${n} ${segment.label.toLowerCase()}`}
                    />
                  )
                })}
              </span>

              <span
                className={[
                  'text-right text-xs',
                  row.cappedRecall === null
                    ? 'text-unknown'
                    : row.cappedRecall === 0
                      ? 'text-signal'
                      : 'text-ink-60',
                ].join(' ')}
              >
                {row.cappedRecall === null
                  ? '—'
                  : `${(row.cappedRecall * 100).toFixed(1)}%`}
              </span>

              <span className="sr-only">
                {row.total} labelled story placements for fixture {row.key}:{' '}
                {SEGMENTS.filter((s) => row.counts[s.outcome] > 0)
                  .map((s) => `${row.counts[s.outcome]} ${s.label.toLowerCase()}`)
                  .join(', ')}
                . Capped recall{' '}
                {row.cappedRecall === null
                  ? 'not reported'
                  : `${(row.cappedRecall * 100).toFixed(1)} percent`}
                .
              </span>
            </Link>
          </li>
        ))}
      </ul>

      <div className="flex flex-col gap-2">
        <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1.5 p-0">
          {SEGMENTS.map((segment) => (
            <li key={segment.outcome} className="flex items-center gap-1.5 text-xs text-ink-60">
              <span className={`inline-block h-2.5 w-2.5 shrink-0 ${segment.fill}`} aria-hidden="true" />
              {segment.label}
            </li>
          ))}
        </ul>
        <p className="m-0 max-w-2xl text-xs text-ink-40">
          {caption} Bar length is the number of labelled story placements the fixture had; the
          right-hand column is capped recall at k.
          {mean !== null ? (
            <> The run&rsquo;s reported mean is {(mean * 100).toFixed(1)}%.</>
          ) : null}{' '}
          A fixture at 0.0% is not a rounding artefact — it received none of the stories its labels
          said it needed.
        </p>
      </div>
    </div>
  )
}
