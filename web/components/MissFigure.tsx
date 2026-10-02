'use client'

import { useState } from 'react'

import type { MissStage } from '@/lib/home'

/**
 * Every must-see story that never reached its reader, placed at the stage
 * that lost it.
 *
 * The switch is arithmetic on the recorded attribution, not a new run: if
 * every stage after the recency window were perfect, the misses attributed to
 * those stages are the most that could come back. The ones lost at the
 * window stay lost, because nothing after the window ever sees them.
 */
export function MissFigure({ stages, total }: { stages: readonly MissStage[]; total: number }) {
  const [perfect, setPerfect] = useState(false)
  const lookback = stages[0]
  const after = stages.slice(1)
  const recoverable = after.reduce((s, m) => s + m.count, 0)
  const remaining = perfect ? total - recoverable : total
  if (lookback === undefined) return null

  return (
    <div className="flex flex-col gap-8">
      <div className="flex flex-wrap items-end justify-between gap-6">
        <div>
          <p className="readout m-0 text-[clamp(2.5rem,5vw,3.5rem)]" aria-live="polite">
            {remaining}
            {perfect ? <span className="ml-2 align-baseline text-[0.4em] font-medium tracking-normal text-ink-40 line-through">{total}</span> : null}
          </p>
          <p className="m-0 mt-1.5 text-[0.8125rem] text-ink-60">
            {perfect ? 'still missing with every later stage perfect' : 'needed stories that never arrived'}
          </p>
        </div>
        <label className="flex cursor-pointer items-center gap-3 select-none">
          <span className="text-right text-[0.875rem] leading-snug">
            <span className="block font-medium text-ink">Make every later stage perfect</span>
            <span className="block text-[0.8125rem] text-ink-40">prefilter, scoring, blend and rank</span>
          </span>
          <button
            type="button"
            role="switch"
            aria-checked={perfect}
            onClick={() => setPerfect((p) => !p)}
            className={`relative h-6 w-10 shrink-0 rounded-full transition-colors duration-200 ${perfect ? 'bg-ink' : 'bg-rule-strong'}`}
          >
            <span
              className={`absolute top-0.5 left-0.5 size-5 rounded-full bg-sheet shadow-[var(--shadow-1)] transition-transform duration-200 [transition-timing-function:var(--ease-out-quart)] ${
                perfect ? 'translate-x-4' : ''
              }`}
            />
            <span className="sr-only">Make every stage after the recency window perfect</span>
          </button>
        </label>
      </div>

      <div className="grid gap-6 md:grid-cols-[minmax(0,1.6fr)_auto_minmax(0,1fr)] md:items-end">
        <Cluster stage={lookback} columns={15} recovered={false} />
        <div className="relative hidden self-stretch md:block" aria-hidden="true">
          <div className="h-full w-px bg-[repeating-linear-gradient(to_bottom,var(--d-control)_0_3px,transparent_3px_7px)]" />
        </div>
        <div className="grid grid-cols-3 items-end gap-5">
          {after.map((m) => (
            <Cluster key={m.key} stage={m} columns={3} recovered={perfect} />
          ))}
        </div>
      </div>

      <div className="grid gap-4 text-[0.8125rem] md:grid-cols-[minmax(0,1.6fr)_auto_minmax(0,1fr)]">
        <p className="m-0 text-ink-60">
          <span className="font-medium text-ink">Lost before anything judged them.</span> {lookback.note}
        </p>
        <span className="hidden w-px md:block" />
        <p className="m-0 text-ink-60">
          <span className="font-medium text-ink">Lost after relevance was judged.</span>{' '}
          {perfect ? `At most ${recoverable} come back.` : 'This is all better ranking can reach.'}
        </p>
      </div>
    </div>
  )
}

function Cluster({ stage, columns, recovered }: { stage: MissStage; columns: number; recovered: boolean }) {
  return (
    <figure className="m-0 flex min-w-0 flex-col gap-2.5">
      <div
        role="img"
        aria-label={`${stage.count} lost at ${stage.label}${recovered ? ', recovered if this stage were perfect' : ''}`}
        className="grid w-max gap-1"
        style={{ gridTemplateColumns: `repeat(${columns}, 14px)` }}
      >
        {Array.from({ length: stage.count }, (_, i) => (
          <span
            key={i}
            className="cell transition-colors duration-300"
            style={{ ['--c' as string]: '14px', transitionDelay: recovered ? `${i * 25}ms` : '0ms' }}
            data-tone={recovered ? 'ink' : 'loss'}
          />
        ))}
      </div>
      <figcaption className="flex min-w-0 flex-col">
        <span className="truncate text-[0.8125rem] font-medium text-ink">{stage.label}</span>
        <span className={`data !text-[0.75rem] ${recovered ? 'text-ink-40 line-through' : 'text-ink-60'}`}>{stage.count}</span>
      </figcaption>
    </figure>
  )
}
