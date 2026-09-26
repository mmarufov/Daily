import type { PersonaArtifact, Story } from '@/lib/artifact'

/**
 * One story's journey, on the same ten-stage track as the sieve.
 *
 * The table row already says "dropped at blended". This says where `blended`
 * is — five stages in, after the scorer, with four stages of work behind it
 * that all passed. That distinction is the difference between "ranking made a
 * mistake" and "nothing ever looked at this article", and it is the question
 * the funnel exists to answer.
 */
export function TraceRibbon({
  story,
  persona,
}: {
  readonly story: Story
  readonly persona: PersonaArtifact
}) {
  const stages = persona.funnel
  if (stages.length === 0) return null

  // `dropped_at` is a drop-reason key, which is not always a stage name: some
  // are mechanisms recorded outside the declared stage order. Matching by
  // prefix covers `prefilter:cap` against `prefilter`; anything that still
  // fails to match is reported as unplaced rather than guessed at.
  const droppedAt = story.dropped_at
  const deathIndex =
    droppedAt === null
      ? stages.length
      : stages.findIndex((s) => s.stage === droppedAt || droppedAt.startsWith(`${s.stage}:`))

  const placed = deathIndex >= 0
  const reached = placed ? deathIndex : stages.length

  return (
    <div className="flex flex-col gap-2">
      <p className="label m-0 text-ink-40">
        {droppedAt === null
          ? 'Reached the delivered feed'
          : placed
            ? `Left the pipeline at ${droppedAt}`
            : `Recorded as ${droppedAt}, which is not one of this runner’s declared stages`}
      </p>

      <ol
        className="m-0 flex list-none gap-px p-0"
        aria-label={
          droppedAt === null
            ? 'This story passed every stage and reached the feed.'
            : `This story passed ${reached} of ${stages.length} stages and left at ${droppedAt}.`
        }
      >
        {stages.map((stage, i) => {
          const survived = placed ? i < deathIndex : droppedAt === null
          const died = placed && i === deathIndex
          return (
            <li
              key={stage.stage}
              className="group relative flex-1"
              title={`${stage.label}: ${survived ? 'passed' : died ? 'left here' : 'never reached'}`}
            >
              <span
                className={[
                  'block h-6',
                  died ? 'bg-signal' : survived ? 'bg-ink' : 'bg-rule',
                ].join(' ')}
                aria-hidden="true"
              />
              <span className="sr-only">
                {stage.label}: {survived ? 'passed' : died ? 'left here' : 'never reached'}.
              </span>
            </li>
          )
        })}
      </ol>

      <ol className="m-0 flex list-none gap-px p-0" aria-hidden="true">
        {stages.map((stage, i) => (
          <li key={stage.stage} className="flex-1 overflow-hidden">
            <span
              className={[
                'block truncate text-[9px] leading-tight',
                placed && i === deathIndex ? 'text-signal' : 'text-ink-40',
              ].join(' ')}
            >
              {stage.stage}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}
