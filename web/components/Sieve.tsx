'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { buildSieve, cellState } from '@/lib/sieve'

export interface SieveStep {
  readonly stage: string
  readonly label: string
  readonly explanation: string | null
  readonly survivors: number
  readonly lost_entering_stage: number
  readonly pass_rate: number | null
  readonly absent: boolean
}

export interface SieveFixture {
  readonly key: string
  readonly steps: readonly SieveStep[]
}

interface SieveProps {
  readonly fixtures: readonly SieveFixture[]
  readonly initialFixture: string
  readonly snapshot: string
  /**
   * The explorer drives fixture selection from the URL so the whole page stays
   * in sync; the home page owns it locally so switching is instant.
   */
  readonly showFixturePicker?: boolean
}

/** Sweep buckets, matched by `.sieve-cell[data-b]` rules in globals.css. */
const BUCKETS = 16

/** Per-stage dwell during autoplay. See the comment at its use. */
const DWELL_MS = 620

export function Sieve({
  fixtures,
  initialFixture,
  snapshot,
  showFixturePicker = true,
}: SieveProps) {
  const [fixtureKey, setFixtureKey] = useState(initialFixture)

  const fixture = useMemo(
    () => fixtures.find((f) => f.key === fixtureKey) ?? fixtures[0],
    [fixtures, fixtureKey],
  )
  const data = useMemo(() => buildSieve(fixture?.steps ?? []), [fixture])
  const last = data.stages.length - 1

  const [index, setIndex] = useState(0)
  // Autoplay is a one-shot demonstration, not a loop. It runs once per
  // fixture, stops at the delivered feed, and any interaction cancels it — a
  // hero that keeps moving while you are reading it is a hero you scroll past.
  const [playing, setPlaying] = useState(false)
  const cancelled = useRef(false)

  useEffect(() => {
    cancelled.current = false
    setIndex(0)

    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      // Reduced motion gets the answer instead of the performance.
      setIndex(last)
      return
    }

    setPlaying(true)
    const timers: ReturnType<typeof setTimeout>[] = []
    for (let s = 1; s <= last; s += 1) {
      timers.push(
        setTimeout(
          () => {
            if (cancelled.current) return
            setIndex(s)
            if (s === last) setPlaying(false)
          },
          // Dwell must exceed the sweep (300ms transition + 150ms of bucket
          // delay, see globals.css) so a stage has finished settling before the
          // next begins. Otherwise the previous stage's losses are still fading
          // red under a caption that says nothing was removed.
          650 + s * DWELL_MS,
        ),
      )
    }
    return () => {
      for (const t of timers) clearTimeout(t)
    }
  }, [last, fixtureKey])

  const stop = useCallback(() => {
    cancelled.current = true
    setPlaying(false)
  }, [])

  const select = useCallback(
    (next: number) => {
      stop()
      setIndex(next)
    },
    [stop],
  )

  const current = data.stages[index]
  const first = data.stages[0]
  if (fixture === undefined || current === undefined || first === undefined) return null

  const atEnd = index >= last
  const share = first.survivors === 0 ? 0 : current.survivors / first.survivors

  return (
    <div className="flex flex-col gap-6">
      {showFixturePicker ? (
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <p className="label m-0 shrink-0 text-ink-40">Reader fixture</p>
        <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
          {fixtures.map((f) => (
            <li key={f.key}>
              <button
                type="button"
                onClick={() => setFixtureKey(f.key)}
                aria-pressed={f.key === fixtureKey}
                className={`chip ${f.key === fixtureKey ? 'chip-on' : ''}`}
              >
                {f.key}
              </button>
            </li>
          ))}
        </ul>
      </div>
      ) : null}

      <div className="flex flex-wrap items-end justify-between gap-x-10 gap-y-5">
        <div className="flex items-end gap-4">
          <div>
            <p className="label m-0 text-ink-40">
              {atEnd ? 'Delivered to the reader' : 'Still in the pipeline'}
            </p>
            <p className="readout m-0">{current.survivors.toLocaleString()}</p>
          </div>
          <p className="m-0 pb-1.5 text-xs text-ink-40">
            of {first.survivors.toLocaleString()}
            <span className="block">{(share * 100).toFixed(1)}%</span>
          </p>
        </div>

        <div className="max-w-sm">
          <p className="label m-0 text-ink-40">
            Stage {String(index + 1).padStart(2, '0')} / {String(last + 1).padStart(2, '0')} ·{' '}
            {current.stage}
          </p>
          <p className="headline m-0 mt-1 text-lg">{current.label}</p>
          {current.lost > 0 ? (
            <p className="m-0 mt-1.5 text-xs text-ink-60">
              <span className="text-signal">−{current.lost.toLocaleString()}</span> removed
              entering this stage
              {current.passRate !== null ? <> · {(current.passRate * 100).toFixed(1)}% passed</> : null}
            </p>
          ) : (
            <p className="m-0 mt-1.5 text-xs text-ink-40">
              {index === 0 ? 'Nothing removed yet.' : 'Nothing was removed here.'}
            </p>
          )}
        </div>
      </div>

      <div
        role="img"
        aria-label={`${first.survivors.toLocaleString()} candidate articles for reader fixture ${fixture.key}; ${current.survivors.toLocaleString()} remain after ${current.label}.`}
        className="sieve"
      >
        {data.deaths.map((death, i) => (
          <span
            key={i}
            className="sieve-cell"
            data-state={cellState(death, index, last)}
            data-b={i % BUCKETS}
          />
        ))}
      </div>

      <div className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-3">
        <p className="m-0 max-w-xl text-xs text-ink-60">
          {current.explanation ??
            'Every article in the frozen snapshot, plus the needles planted for this fixture.'}
          {current.reconstructed ? (
            <span className="text-unknown">
              {' '}
              This scorecard recorded no tally here, so the count is reconstructed from the stages
              around it.
            </span>
          ) : null}
        </p>
        <div className="flex shrink-0 gap-2">
          {playing ? (
            <button type="button" onClick={stop} className="chip">
              Stop
            </button>
          ) : (
            <>
              <button
                type="button"
                onClick={() => select(Math.max(index - 1, 0))}
                disabled={index === 0}
                className="chip disabled:opacity-35 disabled:hover:border-control disabled:hover:text-ink"
              >
                Back
              </button>
              <button
                type="button"
                onClick={() => select(atEnd ? 0 : index + 1)}
                className="chip chip-on"
              >
                {atEnd ? 'Replay' : 'Next stage'}
              </button>
            </>
          )}
        </div>
      </div>

      <ol className="m-0 grid list-none grid-cols-2 gap-px border border-rule bg-rule p-0 sm:grid-cols-5">
        {data.stages.map((stage, s) => {
          const on = s === index
          return (
            <li key={stage.stage}>
              <button
                type="button"
                onClick={() => select(s)}
                aria-current={on ? 'step' : undefined}
                className={[
                  'flex w-full flex-col items-start gap-0.5 px-2.5 py-2 text-left transition-colors duration-150',
                  on ? 'bg-ink text-paper' : 'bg-paper text-ink hover:bg-paper-secondary',
                ].join(' ')}
              >
                <span className={`label ${on ? 'text-paper' : 'text-ink-40'}`}>
                  {String(s + 1).padStart(2, '0')}
                </span>
                <span className="w-full truncate text-xs">{stage.label}</span>
                <span className={`text-xs ${on ? 'text-paper' : 'text-ink-60'}`}>
                  {stage.survivors.toLocaleString()}
                </span>
              </button>
            </li>
          )
        })}
      </ol>

      <p className="m-0 max-w-3xl text-xs text-ink-40">
        One cell is one candidate article. Counts are the recorded survivorship for fixture{' '}
        <span className="text-ink-60">{fixture.key}</span> against corpus{' '}
        <span className="text-ink-60">{snapshot}</span>, reconstructed from the scorecard&rsquo;s
        stage tallies and asserted against three independently recorded facts in{' '}
        <span className="text-ink-60">funnel.test.ts</span>. Which particular cell a stage took is
        not recorded anywhere, so cells are scattered by a fixed hash: the quantities are evidence,
        the positions are not.
      </p>
    </div>
  )
}
