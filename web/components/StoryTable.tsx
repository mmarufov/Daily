import Link from 'next/link'

import { TraceRibbon } from '@/components/TraceRibbon'
import type { PersonaArtifact, Story, StoryOutcome } from '@/lib/artifact'
import { explorerHref, type ExplorerState, type OutcomeFilter } from '@/lib/url-state'

const OUTCOME_TEXT: Record<StoryOutcome, string> = {
  'delivered-wanted': 'Delivered · wanted',
  'delivered-unwanted': 'Delivered · unwanted',
  'delivered-unlabelled': 'Delivered · unlabelled',
  'lost-before-scorer': 'Lost before the scorer',
  'lost-at-or-after-scorer': 'Lost at or after the scorer',
}

const OUTCOME_TONE: Record<StoryOutcome, string> = {
  'delivered-wanted': 'text-ink',
  'delivered-unwanted': 'text-signal',
  'delivered-unlabelled': 'text-unknown',
  'lost-before-scorer': 'text-signal',
  'lost-at-or-after-scorer': 'text-signal',
}

/** Same colour rule as every other figure: ink survived, vermilion is loss. */
const OUTCOME_SWATCH: Record<StoryOutcome, string> = {
  'delivered-wanted': 'bg-ink',
  'delivered-unwanted': 'bg-signal',
  'delivered-unlabelled': 'bg-unknown',
  'lost-before-scorer': 'bg-signal/25',
  'lost-at-or-after-scorer': 'bg-signal/55',
}

export function filterStories(stories: readonly Story[], outcome: OutcomeFilter): readonly Story[] {
  if (outcome === 'all') return stories
  return stories.filter((s) => s.outcome === outcome)
}

interface StoryTableProps {
  readonly persona: PersonaArtifact
  readonly state: ExplorerState
}

export function StoryTable({ persona, state }: StoryTableProps) {
  if (!persona.trace_available) {
    return (
      <p className="m-0 max-w-2xl border border-rule bg-paper-secondary p-4 text-xs">
        This scorecard carries no per-story trace for <strong>{persona.key}</strong>, so there is
        nothing to follow. The explorer shows the gap rather than reconstructing an explanation the
        data does not contain.
      </p>
    )
  }

  const stories = filterStories(persona.stories, state.outcome)

  if (stories.length === 0) {
    return (
      <p className="m-0 max-w-2xl border border-rule bg-paper-secondary p-4 text-xs">
        No stories for <strong>{persona.key}</strong> match this outcome filter.{' '}
        <Link href={explorerHref(state, { outcome: 'all' })} className="link">
          Show every story
        </Link>
        .
      </p>
    )
  }

  return (
    <table className="w-full border-collapse text-xs">
      <caption className="sr-only">
        Stories for reader fixture {persona.key}, filtered to {state.outcome}. Select a row to see
        its recorded trace.
      </caption>
      <thead>
        <tr className="border-b border-ink-40 text-left">
          <th scope="col" className="label py-2 pr-3 text-ink-40">
            Rank
          </th>
          <th scope="col" className="label py-2 pr-3 text-ink-40">
            Story
          </th>
          <th scope="col" className="label py-2 pr-3 text-ink-40">
            Outcome
          </th>
          <th scope="col" className="label py-2 text-right text-ink-40">
            Score
          </th>
        </tr>
      </thead>
      <tbody>
        {stories.map((story) => {
          const selected = state.story === story.id
          return (
            <tr
              key={story.id}
              className={[
                'border-b border-rule align-top',
                selected ? 'bg-paper-secondary' : '',
              ].join(' ')}
              aria-current={selected ? 'true' : undefined}
            >
              <td className="py-2.5 pr-3 tabular-nums text-ink-60">
                {story.rank === null ? '—' : story.rank}
              </td>
              <th scope="row" className="py-2.5 pr-3 text-left font-normal">
                <span className="flex items-baseline gap-2">
                  <span
                    className={`inline-block h-2.5 w-2.5 shrink-0 translate-y-px ${OUTCOME_SWATCH[story.outcome]}`}
                    aria-hidden="true"
                  />
                  <Link
                    href={explorerHref(state, { story: story.id })}
                    className="headline text-sm text-ink no-underline hover:text-signal"
                  >
                    {story.title ?? story.id}
                  </Link>
                </span>
                {story.source !== null ? (
                  <span className="label block pt-1 pl-4.5 text-ink-40">{story.source}</span>
                ) : null}
              </th>
              <td className={`py-2.5 pr-3 text-xs ${OUTCOME_TONE[story.outcome]}`}>
                {OUTCOME_TEXT[story.outcome]}
                {story.dropped_at !== null ? (
                  <span className="block pt-0.5 text-[11px] text-ink-40">{story.dropped_at}</span>
                ) : null}
              </td>
              <td className="py-2.5 text-right tabular-nums text-ink-60">
                {story.score === null ? '—' : story.score.toFixed(3)}
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

export function StoryDetail({
  story,
  persona,
}: {
  readonly story: Story
  readonly persona: PersonaArtifact
}) {
  return (
    <aside
      aria-label={`Recorded trace for ${story.title ?? story.id}`}
      className="flex flex-col gap-4 border border-ink bg-paper-secondary p-4"
    >
      <h3 className="headline m-0 text-lg">{story.title ?? story.id}</h3>

      <TraceRibbon story={story} persona={persona} />

      <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-3 text-xs sm:grid-cols-3">
        <Row term="Article id" value={story.id} mono />
        <Row term="Source" value={story.source ?? 'not recorded'} />
        <Row term="Ground-truth label" value={story.label ?? 'unlabelled'} />
        <Row term="Final rank" value={story.rank === null ? 'not delivered' : String(story.rank)} />
        <Row term="Score" value={story.score === null ? 'not recorded' : story.score.toFixed(4)} />
        <Row term="Left the pipeline at" value={story.dropped_at ?? 'reached the feed'} mono />
      </dl>

      {story.reason !== null ? (
        <div className="flex flex-col gap-1.5 border-t border-signal pt-3">
          <h4 className="label m-0 text-ink-40">Recorded reason</h4>
          <p className="lede m-0 text-base">
            {story.reason}
            {story.reason_truncated ? (
              <span className="ml-1 text-xs not-italic text-ink-60">
                (stored truncated; preserved as recorded)
              </span>
            ) : null}
          </p>
          <p className="m-0 text-xs text-ink-60">
            Diagnostic text recorded beside the drop. For some stages it is a model rationale, for
            others a mechanical label. It is evidence about what the pipeline logged, not proof
            that the explanation is correct — and on the production scorer it is known to be
            misattributed.{' '}
            <Link href="/engineering" className="link">
              Why that happens
            </Link>
            .
          </p>
        </div>
      ) : null}
    </aside>
  )
}

function Row({ term, value, mono }: { term: string; value: string; mono?: boolean }) {
  return (
    <div>
      <dt className="label m-0 text-ink-40">{term}</dt>
      <dd className={`m-0 mt-0.5 ${mono === true ? 'text-ink-60' : ''}`}>{value}</dd>
    </div>
  )
}
