'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { buildSieve, cellState } from '@/lib/sieve'
import type { SieveStepData } from '@/lib/home'

/** Sweep buckets, matched by `.sieve-cell[data-b]` rules in globals.css. */
const BUCKETS = 16
/** Per-stage dwell while it plays. Longer than the sweep, so a stage settles. */
const DWELL_MS = 700

/**
 * One reader's edition, one cell per candidate article.
 *
 * Plays once when it first scrolls into view, stage by stage, and stops on
 * the delivered feed. Any interaction takes over. Reduced motion gets the
 * answer instead of the performance. Which cell a stage removed is not
 * recorded anywhere, so cells are scattered by a fixed hash: the counts are
 * evidence, the positions are not, and the caption says so.
 */
export function SieveFigure({ steps, name, snapshot }: { steps: readonly SieveStepData[]; name: string; snapshot: string }) {
  const data = useMemo(() => buildSieve(steps), [steps])
  const last = data.stages.length - 1
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const played = useRef(false)
  const timers = useRef<ReturnType<typeof setTimeout>[]>([])
  const root = useRef<HTMLDivElement>(null)

  const stop = useCallback(() => {
    for (const t of timers.current) clearTimeout(t)
    timers.current = []
    setPlaying(false)
  }, [])

  const play = useCallback(() => {
    stop()
    setIndex(0)
    setPlaying(true)
    for (let s = 1; s <= last; s += 1) {
      timers.current.push(
        setTimeout(() => {
          setIndex(s)
          if (s === last) setPlaying(false)
        }, 500 + s * DWELL_MS),
      )
    }
  }, [last, stop])

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      setIndex(last)
      played.current = true
      return
    }
    const el = root.current
    if (el === null) return
    const io = new IntersectionObserver(
      (entries) => {
        if (played.current) return
        if (entries.some((e) => e.isIntersecting)) {
          played.current = true
          play()
        }
      },
      { threshold: 0.45 },
    )
    io.observe(el)
    return () => {
      io.disconnect()
      stop()
    }
  }, [last, play, stop])

  const select = (next: number) => {
    played.current = true
    stop()
    setIndex(next)
  }

  const current = data.stages[index]
  const first = data.stages[0]
  if (current === undefined || first === undefined) return null
  const atEnd = index >= last

  return (
    <div ref={root} className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div className="flex items-baseline gap-3">
          <span className="readout text-[clamp(2.5rem,5vw,3.5rem)]" aria-live="polite">
            {current.survivors.toLocaleString('en-US')}
          </span>
          <span className="text-[0.875rem] text-ink-40">
            of {first.survivors.toLocaleString('en-US')} {atEnd ? 'delivered' : 'still in'}
          </span>
        </div>
        <div className="min-w-0 text-right">
          <p className="m-0 text-[0.875rem] font-medium text-ink">{current.label}</p>
          <p className="m-0 text-[0.8125rem] text-ink-40">
            {current.lost > 0 ? (
              <>
                <span className="text-signal">−{current.lost.toLocaleString('en-US')}</span> removed here
              </>
            ) : index === 0 ? (
              'Nothing removed yet'
            ) : (
              'Nothing removed here'
            )}
          </p>
        </div>
      </div>

      <div className="sieve-plate">
        <div
          role="img"
          aria-label={`${first.survivors.toLocaleString('en-US')} candidate articles for reader fixture ${name}; ${current.survivors.toLocaleString('en-US')} remain after ${current.label}.`}
          className="sieve"
        >
          {data.deaths.map((death, i) => (
            <span key={i} className="sieve-cell" data-state={cellState(death, index, last)} data-b={i % BUCKETS} />
          ))}
        </div>
      </div>

      {/* The stages, as a scrubber. */}
      <div className="flex flex-col gap-3">
        <ol className="m-0 grid list-none grid-cols-5 gap-1 p-0 sm:grid-cols-10" aria-label="Pipeline stages">
          {data.stages.map((stage, s) => {
            const on = s === index
            const passed = s < index
            return (
              <li key={stage.stage} className="min-w-0">
                <button
                  type="button"
                  onClick={() => select(s)}
                  aria-current={on ? 'step' : undefined}
                  className="group flex w-full min-w-0 flex-col gap-1.5 rounded-md py-1 text-left"
                >
                  <span
                    className={`block h-1 w-full rounded-full transition-colors duration-300 ${
                      on ? 'bg-ink' : passed ? 'bg-ink-40' : 'bg-rule-strong group-hover:bg-control'
                    }`}
                  />
                  <span className={`line-clamp-2 min-h-[2.4em] text-[0.75rem] leading-[1.2] ${on ? 'text-ink' : 'text-ink-40 group-hover:text-ink-60'}`}>
                    {stage.label}
                  </span>
                  <span className={`data !text-[0.75rem] ${on ? 'text-ink' : 'text-ink-40'}`}>
                    {stage.survivors.toLocaleString('en-US')}
                  </span>
                </button>
              </li>
            )
          })}
        </ol>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="m-0 max-w-2xl text-[0.8125rem] text-ink-40">
            Reader fixture {name}, corpus {snapshot}. Counts are recorded per stage; which square a stage
            took is not, so the scatter is a fixed hash.
          </p>
          <button type="button" onClick={playing ? stop : play} className="chip">
            {playing ? 'Stop' : 'Replay'}
          </button>
        </div>
      </div>
    </div>
  )
}
