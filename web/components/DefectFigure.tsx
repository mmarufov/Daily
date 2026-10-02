'use client'

import { useEffect, useRef, useState } from 'react'

import type { DefectBatch, GuardMetric } from '@/lib/home'

type Mode = 'positional' | 'guard'

/** Rows of the pairs table: the start, the slip, and the loop. */
const SHOWN_POSITIONS = [2, 3, 4, 5]

/**
 * One recorded batch, and what the fix did to the numbers.
 *
 * The cells are laid out forty to a row so that the first row of verdicts
 * sits under the forty articles it was paired with by position, and the
 * other 214 hang below with nothing at their position to attach to. The
 * toggle switches the parse, not the data: both modes show the same response.
 * The scoreboard is the whole run, every batch for ten fixtures, measured
 * twice on identical inputs with only the parse changed.
 */
export function DefectFigure({
  batch,
  metrics,
  revision,
  date,
}: {
  batch: DefectBatch
  metrics: readonly GuardMetric[] | null
  revision: string | null
  date: string | null
}) {
  const [mode, setMode] = useState<Mode>('positional')
  const guard = mode === 'guard'
  const sent = batch.articles.length
  const verdictAt = (i: number) => (i < batch.distinct.length ? batch.distinct[i] : batch.loop.text) ?? ''
  const loopIn = Math.max(0, sent - batch.loop.start)

  const loopPositions = batch.loop.start < sent ? [batch.loop.start] : []

  return (
    <div className="flex flex-col gap-6">
      <div role="radiogroup" aria-label="How the response is parsed" className="inline-flex w-max rounded-lg bg-paper-secondary p-1">
        {(
          [
            ['positional', 'What production does', 'Production'],
            ['guard', 'With the count guard', 'Count guard'],
          ] as const
        ).map(([value, label, short]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={mode === value}
            aria-label={label}
            onClick={() => setMode(value)}
            className={`h-8 rounded-md px-3 text-[0.8125rem] font-medium transition-[background-color,color,box-shadow] duration-200 ${
              mode === value ? 'bg-sheet text-ink shadow-[var(--shadow-1)]' : 'text-ink-60 hover:text-ink'
            }`}
          >
            <span className="max-[24rem]:hidden">{label}</span>
            <span className="hidden max-[24rem]:inline">{short}</span>
          </button>
        ))}
      </div>

      <p className="m-0 -mt-2 min-h-[3em] max-w-2xl text-[0.875rem] text-ink-60" aria-live="polite">
        {guard ? (
          <>
            {batch.returned} is not {sent}, so the guard refuses the whole batch and none of the {sent} is scored.{' '}
            <span className="text-ink">Correct, and worse on paper:</span> the old numbers were partly computed from
            verdicts attached to the wrong articles.
          </>
        ) : (
          <>
            Production pairs the verdicts to the articles by position and keeps going. {loopIn} of these {sent} articles
            get the same sentence.
          </>
        )}
      </p>

      <div className="grid gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,21rem)]">
        <div className="flex min-w-0 flex-col gap-6">
          <figure className="m-0 flex flex-col gap-2">
            <figcaption className="flex flex-wrap items-baseline justify-between gap-x-4 text-[0.8125rem]">
              <span className="font-medium text-ink">{sent} articles sent</span>
              <span className="text-ink-40">
                {guard ? 'refused as a batch, so none is scored' : 'each paired with the verdict at its position'}
              </span>
            </figcaption>
            <div
              className="defect-grid"
              style={{ ['--cols' as string]: sent }}
              role="img"
              aria-label={`${sent} articles. ${guard ? 'None scored: the batch was refused.' : 'Each scored with the verdict at the same position.'}`}
            >
              {batch.articles.map((_, i) => (
                <span
                  key={i}
                  className="cell defect-cell"
                  data-tone={guard ? 'open' : 'ink'}
                  style={{ transitionDelay: `${i * 8}ms` }}
                />
              ))}
            </div>
            <div className="defect-grid" style={{ ['--cols' as string]: sent }} aria-hidden="true">
              {batch.articles.map((_, i) => (
                <span key={i} className="defect-wire" data-on={guard ? undefined : ''} />
              ))}
            </div>
            <div
              className="defect-grid"
              style={{ ['--cols' as string]: sent }}
              role="img"
              aria-label={`${batch.returned} verdicts returned: ${batch.loop.start} distinct, then one sentence repeated ${batch.loop.count} times.`}
            >
              {Array.from({ length: batch.returned }, (_, i) => {
                const repeated = i >= batch.loop.start && i < batch.loop.start + batch.loop.count
                return (
                  <span
                    key={i}
                    className="cell defect-cell"
                    data-tone={repeated ? 'unknown' : 'mid'}
                    data-dim={guard || i >= sent ? '' : undefined}
                  />
                )
              })}
            </div>
            <p className="m-0 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-[0.8125rem]">
              <span className="font-medium text-ink">{batch.returned} verdicts returned</span>
              <span className="flex items-center gap-1.5 text-ink-40">
                <span className="cell" data-tone="unknown" style={{ ['--c' as string]: '10px' }} />
                the same sentence, {batch.loop.count} times in a row
              </span>
            </p>
          </figure>

          <ol
            className="m-0 flex list-none flex-col overflow-hidden rounded-lg border border-rule p-0"
            aria-label="Articles and the verdicts that landed on them, by position"
          >
            <li
              className="hidden grid-cols-[2.25rem_minmax(0,1fr)_minmax(0,0.9fr)] gap-x-4 border-b border-rule bg-paper-secondary px-3 py-2 text-[0.75rem] font-medium text-ink-40 sm:grid"
              aria-hidden="true"
            >
              <span>#</span>
              <span>Article sent</span>
              <span>{guard ? 'Score' : 'Verdict at that position'}</span>
            </li>
            {[...SHOWN_POSITIONS, -1, ...loopPositions].map((i) =>
              i === -1 ? (
                <li key="gap" className="border-b border-rule bg-paper-secondary px-3 py-1.5 text-[0.75rem] text-ink-40 sm:pl-[3.25rem]">
                  {loopPositions.length > 0
                    ? `From position ${batch.loop.start}, the same sentence lands on all ${loopIn} remaining articles.`
                    : null}
                </li>
              ) : (
                <li
                  key={i}
                  className="grid grid-cols-[2.25rem_minmax(0,1fr)] gap-x-4 gap-y-1.5 border-b border-rule px-3 py-3 text-[0.8125rem] last:border-b-0 sm:grid-cols-[2.25rem_minmax(0,1fr)_minmax(0,0.9fr)]"
                >
                  <span className="data text-ink-40">{i}</span>
                  <span className="headline text-[0.9375rem] text-ink" data-verbatim>
                    {batch.articles[i]?.title}
                  </span>
                  <span className="col-start-2 sm:col-start-3">
                    {guard ? (
                      <span className="text-ink-40">unscored</span>
                    ) : (
                      <span
                        className={`line-clamp-2 ${i >= batch.loop.start ? 'text-ink-40' : 'text-ink-60'}`}
                        data-verbatim
                      >
                        {verdictAt(i)}
                      </span>
                    )}
                  </span>
                </li>
              ),
            )}
          </ol>
          <p className="m-0 text-[0.8125rem] text-ink-40">
            Recorded response <span className="data">{batch.caseId}</span>, corpus {batch.snapshot}.
            {batch.finishReason !== null
              ? ` The model reported finish_reason "${batch.finishReason}": it thought it was done.`
              : ''}
          </p>
        </div>

        {metrics !== null ? <Scoreboard metrics={metrics} guard={guard} revision={revision} date={date} /> : null}
      </div>
    </div>
  )
}

function Scoreboard({
  metrics,
  guard,
  revision,
  date,
}: {
  metrics: readonly GuardMetric[]
  guard: boolean
  revision: string | null
  date: string | null
}) {
  return (
    <aside className="panel order-first flex h-max flex-col gap-0 p-0 lg:order-none lg:sticky lg:top-24" aria-live="polite">
      <div className="border-b border-rule px-5 py-4">
        <p className="m-0 text-[0.875rem] font-medium text-ink">The whole run</p>
        <p className="m-0 mt-0.5 text-[0.8125rem] text-ink-40">
          Every batch for ten readers, replayed twice on identical inputs. Only the parse differs.
        </p>
      </div>
      <dl className="m-0 flex flex-col">
        {metrics.map((m) => {
          const value = guard ? m.after : m.before
          const delta = (m.after - m.before) * 100
          const worse = m.lowerIsBetter ? delta > 0.05 : delta < -0.05
          const same = Math.abs(delta) <= 0.05
          return (
            <div key={m.key} className="flex items-start justify-between gap-4 border-b border-rule px-5 py-4">
              <dt className="pt-1 text-[0.8125rem] text-ink-60">{m.label}</dt>
              <dd className="m-0 text-right">
                <Tween value={value * 100} className="readout-sm block" suffix="%" />
                <span
                  className={`data block !text-[0.75rem] transition-opacity duration-300 ${guard ? 'opacity-100' : 'opacity-0'} ${
                    same ? 'text-ink-40' : worse ? 'text-signal' : 'text-ink-60'
                  }`}
                >
                  {same ? 'unchanged' : `${delta > 0 ? '+' : '−'}${Math.abs(delta).toFixed(1)} pts`}
                </span>
              </dd>
            </div>
          )
        })}
        <div className="flex items-center justify-between gap-4 border-b border-rule px-5 py-4">
          <dt className="text-[0.8125rem] text-ink-60">Baseline re-recorded</dt>
          <dd className="m-0 text-[0.875rem] font-medium text-ink">No</dd>
        </div>
        <div className="flex items-center justify-between gap-4 px-5 py-4">
          <dt className="text-[0.8125rem] text-ink-60">The fix&rsquo;s regression gate</dt>
          <dd className="m-0">
            <a
              href="https://github.com/mmarufov/Daily/pull/59/checks"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-[0.875rem] font-medium text-signal no-underline hover:underline"
            >
              <span className="size-2 rounded-full bg-loss" aria-hidden="true" />
              Failing
            </a>
          </dd>
        </div>
      </dl>
      {revision !== null ? (
        <p className="m-0 border-t border-rule bg-paper-secondary px-5 py-3 text-[0.75rem] text-ink-40">
          Guarded replay at <span className="data">{revision}</span>, {date}.{' '}
          <a href="/experiments/count-guard-prod-llm-2026-09-02.json" className="link">
            The scorecard
          </a>
        </p>
      ) : null}
    </aside>
  )
}

/** A number that eases to its new value instead of jumping. */
function Tween({ value, className, suffix }: { value: number; className?: string; suffix?: string }) {
  const [shown, setShown] = useState(value)
  const from = useRef(value)
  useEffect(() => {
    const start = from.current
    if (start === value) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      from.current = value
      setShown(value)
      return
    }
    const began = performance.now()
    let raf = 0
    const tick = (t: number) => {
      const k = Math.min(1, (t - began) / 520)
      const eased = 1 - Math.pow(1 - k, 4)
      const v = start + (value - start) * eased
      from.current = v
      setShown(v)
      if (k < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [value])
  return (
    <span className={className}>
      {shown.toFixed(1)}
      {suffix}
    </span>
  )
}
