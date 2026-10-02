'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Link from 'next/link'

import type { SieveFixture } from './Sieve'
import { personaName } from '@/lib/personas'
import { buildSieve, cellState } from '@/lib/sieve'
import { explorerHref } from '@/lib/url-state'

/** A short recorded sequence. The lookback loss gets time to register. */
const STAGE_DWELL = [700, 1400, 350, 350, 350, 350, 350, 350, 350, 350]

export function HeroSieve({ fixtures, runId, snapshot }: {
  readonly fixtures: readonly SieveFixture[]
  readonly runId: string
  readonly snapshot: string
}) {
  const [fixtureKey, setFixtureKey] = useState('ray')
  const fixture = fixtures.find((item) => item.key === fixtureKey) ?? fixtures[0]
  const data = useMemo(() => buildSieve(fixture?.steps ?? []), [fixture])
  const last = data.stages.length - 1
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [reducedMotion, setReducedMotion] = useState(false)
  const frame = useRef<HTMLDivElement>(null)
  const started = useRef(false)
  const manual = useRef(false)
  const visible = useRef(false)

  const pause = useCallback(() => {
    manual.current = true
    setPlaying(false)
  }, [])

  useEffect(() => {
    const element = frame.current
    if (!element || last < 0) return
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)')
    const applyPreference = () => {
      setReducedMotion(preference.matches)
      if (preference.matches) {
        started.current = true
        setPlaying(false)
        setIndex(last)
      }
    }
    applyPreference()
    preference.addEventListener('change', applyPreference)
    const observer = new IntersectionObserver(([entry]) => {
      visible.current = entry?.isIntersecting === true
      if (!visible.current) setPlaying(false)
      else if (!started.current && !manual.current && !preference.matches && !document.hidden) {
        started.current = true
        setPlaying(true)
      }
    }, { threshold: 0.15 })
    observer.observe(element)
    const onVisibility = () => { if (document.hidden) setPlaying(false) }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      observer.disconnect()
      preference.removeEventListener('change', applyPreference)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [last])

  useEffect(() => {
    if (!playing || reducedMotion || index >= last) return
    const timer = window.setTimeout(() => {
      setIndex((current) => Math.min(current + 1, last))
      if (index + 1 >= last) setPlaying(false)
    }, STAGE_DWELL[index] ?? 350)
    return () => window.clearTimeout(timer)
  }, [index, last, playing, reducedMotion])

  const selectStage = (value: number) => {
    pause()
    setIndex(Math.max(0, Math.min(value, last)))
  }

  const play = () => {
    manual.current = true
    if (reducedMotion) { setIndex(last); return }
    if (index >= last) setIndex(0)
    setPlaying(visible.current && !document.hidden)
  }

  const current = data.stages[index]
  if (!fixture || !current) return (
    <div className="instrument instrument-empty">
      <p>The recorded pipeline is unavailable.</p>
      <Link href="/evidence" className="text-link">Open the evidence explorer</Link>
    </div>
  )

  const atEnd = index === last
  return (
    <div ref={frame} className="instrument" data-testid="hero-sieve" data-stage={index} data-playing={playing}>
      <div className="instrument-topline">
        <span className="instrument-caption"><span className="record-mark" aria-hidden="true" /> Recorded pipeline replay</span>
        <span className="instrument-version" aria-hidden="true">01 / SIEVE</span>
      </div>

      <div className="instrument-readout">
        <div>
          <span className="instrument-number">{current.survivors.toLocaleString('en-US')}</span>
          <span className="instrument-total"> / {data.total.toLocaleString('en-US')}</span>
          <p>{atEnd ? 'Delivered to the reader' : 'Candidates remaining'}</p>
        </div>
        <label className="fixture-control">
          <span>Reader fixture</span>
          <select onPointerDown={pause} onFocus={pause} aria-label="Reader fixture" value={fixture.key} onChange={(event) => {
            pause()
            const next = fixtures.find((item) => item.key === event.target.value)
            setFixtureKey(event.target.value)
            setIndex(Math.max(0, (next?.steps.length ?? 1) - 1))
          }}>
            {fixtures.map((item) => <option key={item.key} value={item.key}>{personaName(item.key)}</option>)}
          </select>
        </label>
      </div>

      <div className="instrument-field" role="img" aria-label={`${data.total.toLocaleString('en-US')} candidate articles for reader fixture ${personaName(fixture.key)}; ${current.survivors.toLocaleString('en-US')} remain after ${current.label}.`}>
        {data.deaths.map((death, cell) => (
          <span key={cell} className="sieve-cell" aria-hidden="true" data-state={cellState(death, index, last)} data-b={cell % 12} />
        ))}
      </div>

      <div className="instrument-stage">
        <div>
          <p className="stage-overline">STAGE {String(index + 1).padStart(2, '0')} <span>/ {String(last + 1).padStart(2, '0')}</span></p>
          <p className="stage-name">{current.label}</p>
        </div>
        <p className="stage-loss">{current.lost > 0 ? <><span>−{current.lost.toLocaleString('en-US')}</span> removed here</> : atEnd ? 'The recorded outcome' : 'All candidates present'}</p>
      </div>

      <div className="instrument-transport">
        <button type="button" className="playback-button" onClick={playing ? pause : play}>
          <span aria-hidden="true" className={playing ? 'pause-symbol' : 'play-symbol'} />
          {playing ? 'Pause' : atEnd ? 'Replay' : 'Play'}
        </button>
        <div className="stage-slider">
          <input aria-label="Pipeline stage" aria-valuetext={`${index + 1} of ${last + 1}: ${current.label}, ${current.survivors} remaining`} type="range" min={0} max={last} step={1} value={index} onPointerDown={pause} onChange={(event) => selectStage(Number(event.target.value))} />
          <div className="stage-ticks" aria-hidden="true">{data.stages.map((stage, step) => <i key={stage.stage} data-active={step <= index} />)}</div>
        </div>
      </div>

      <div className="instrument-bottomline">
        <details className="instrument-provenance">
          <summary onClick={pause}>About this recording</summary>
          <p>Corpus {snapshot}, fixture {personaName(fixture.key)}. The pool includes injected test stories. Each cell represents one candidate count; positions do not identify articles. {current.reconstructed ? 'This stage count is reconstructed from recorded surrounding stages.' : current.explanation}</p>
        </details>
        <Link href={explorerHref({ run: runId, view: 'funnel' }, { persona: fixture.key })} className="instrument-link">Inspect <span aria-hidden="true">↗</span></Link>
      </div>
      <span className="sr-only" aria-live={playing ? 'off' : 'polite'}>{personaName(fixture.key)}: {current.survivors} of {data.total} candidates remain at {current.label}.</span>
    </div>
  )
}
