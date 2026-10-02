'use client'

import Link from 'next/link'
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import type { RunStoryData } from '@/lib/run-story'
import { clamp, storyFrame, storyStage, STORY_MEDIA, STORY_STOPS, STORY_TOP } from '@/lib/run-story-motion'
import { AnimatedDetails } from './AnimatedDetails'
import { CaseStatusMark, type CaseStatusTone } from './CaseStatusMark'
import { RunDiagram } from './RunDiagram'
import './run-story.css'
import './recorded-run-timeline.css'

const CHAPTERS = [
  { id: 'parser', name: 'Parser', title: 'Start with a parser.', copy: "Daily's parser matches AI scores to articles. This count guard checks the response length." },
  { id: 'sandbox', name: 'Sandbox', title: 'Give it a boundary.', copy: 'A fresh microVM. Networking denied. The grader stays outside.' },
  { id: 'tests', name: 'Tests', title: 'Put it through the cases.', copy: 'Recorded responses and injected failures exercise the parser. Four probes check isolation.' },
  { id: 'verdict', name: 'Verdict', title: 'Inspect the result.', copy: 'The microVM stops. An independent grader checks the parser output.' },
] as const

function Probes({ data }: { data: RunStoryData }) {
  return <ul className="run-probes" aria-label="Recorded isolation checks">{data.probes.map(probe => (
    <li key={probe.name} data-held={probe.held}><CaseStatusMark tone={probe.held ? 'correct' : 'wrong'} /><span>{probe.label}<span className="sr-only">: {probe.held ? 'passed' : 'failed'}</span></span></li>
  ))}</ul>
}

function Verdict({ data, identified }: { data: RunStoryData; identified: boolean }) {
  const { correct, failed, notApplicable, total } = data.counts
  const tone = (status: string): CaseStatusTone => status === 'correct' ? 'correct' : status === 'not-applicable' ? 'unscored' : 'wrong'
  return <div className="run-verdict">
    <p className="run-grader-label">Independent grader <span>Outside the microVM</span></p>
    <div className="run-verdict-heading"><strong>{failed}</strong><span>failed cases<b>Rejected</b></span></div>
    <div className="run-case-grid" data-testid={identified ? 'recorded-case-field' : undefined} role="img" aria-label={`${correct} correct, ${failed} failed, ${notApplicable} not applicable, out of ${total} cases`}>
      {data.cases.map(item => <span key={item.id} className="case-status-cell" data-tone={tone(item.status)} data-status={item.status} aria-hidden="true"><CaseStatusMark tone={tone(item.status)} /></span>)}
    </div>
    <ul className="case-status-legend">{([
      ['correct', correct, 'correct'], ['wrong', failed, 'failed'], ['unscored', notApplicable, 'not applicable'],
    ] as const).map(([mark, count, label]) => <li key={mark}><span className="case-status-cell" data-tone={mark}><CaseStatusMark tone={mark} /></span><span>{count} {label}</span></li>)}</ul>
    <div className="run-failure-example"><span>One injected case</span><p>{data.failure.summary}</p><code>{data.failure.id}</code></div>
  </div>
}

function RecordingDetails({ data }: { data: RunStoryData }) {
  return <AnimatedDetails className="run-inspect">
    <summary>Inspect this recorded run <span>Events, criteria and source</span></summary>
    <div className="run-inspect-content recorded-execution" data-testid="recorded-run-timeline" data-run-id={data.runId}>
      <ol className="recorded-timeline" aria-label="Recorded production execution timeline">{data.events.map(event => <li key={event.stage} className="recorded-timeline-row">
        <span className="recorded-timeline-time" aria-label={`${event.elapsed} seconds`}>{event.elapsed}</span><span className="recorded-timeline-dot" aria-hidden="true" />
        <div className="recorded-timeline-step">{event.stage}{event.stage === 'probing isolation' ? <Probes data={data} /> : null}</div>
      </li>)}<li className="recorded-timeline-row"><span /><span className="recorded-timeline-dot" aria-hidden="true" /><span>graded outside the microVM</span></li></ol>
      <div className="run-source"><p>Criteria generation {data.specVersion}<br /><code>{data.specHash}</code></p><p>Times are recorded elapsed seconds.</p><a className="text-link" href={data.sourceHref}>Inspect the source record <span aria-hidden="true">↗</span></a></div>
    </div>
  </AnimatedDetails>
}

export function RunStory({ data }: { readonly data: RunStoryData | null }) {
  const root = useRef<HTMLElement>(null)
  const track = useRef<HTMLDivElement>(null)
  const sticky = useRef<HTMLDivElement>(null)
  const [stage, setStage] = useState(0)
  const [enhanced, setEnhanced] = useState(false)
  const [active, setActive] = useState(false)

  useEffect(() => {
    const element = root.current, area = track.current, panel = sticky.current
    if (!element || !area || !panel || !data) return
    const media = window.matchMedia(STORY_MEDIA)
    let visible = false
    let frame = 0
    let lastStage = -1
    let observingScroll = false
    const update = () => {
      frame = 0
      if (!media.matches || !visible || document.hidden) return
      const travel = Math.max(1, area.offsetHeight - panel.offsetHeight)
      const progress = clamp((STORY_TOP - area.getBoundingClientRect().top) / travel)
      for (const [key, value] of Object.entries(storyFrame(progress))) element.style.setProperty(key, value)
      element.dataset.progress = progress.toFixed(3)
      const next = storyStage(progress)
      if (next !== lastStage) { lastStage = next; setStage(next) }
    }
    const schedule = () => { if (!frame) frame = window.requestAnimationFrame(update) }
    const sync = () => {
      const running = visible && media.matches && !document.hidden
      setActive(running)
      setEnhanced(media.matches)
      if (running && !observingScroll) {
        window.addEventListener('scroll', schedule, { passive: true })
        observingScroll = true
      } else if (!running && observingScroll) {
        window.removeEventListener('scroll', schedule)
        observingScroll = false
      }
      if (running) schedule()
      else { window.cancelAnimationFrame(frame); frame = 0 }
    }
    const observer = new IntersectionObserver(([entry]) => { visible = entry?.isIntersecting === true; sync() })
    observer.observe(area)
    const resize = new ResizeObserver(sync)
    resize.observe(area)
    resize.observe(panel)
    media.addEventListener('change', sync)
    document.addEventListener('visibilitychange', sync)
    sync()
    return () => {
      window.cancelAnimationFrame(frame)
      window.removeEventListener('scroll', schedule)
      document.removeEventListener('visibilitychange', sync)
      media.removeEventListener('change', sync)
      observer.disconnect()
      resize.disconnect()
    }
  }, [data])

  const select = (index: number) => {
    const area = track.current, panel = sticky.current
    if (!area || !panel) return
    const top = window.scrollY + area.getBoundingClientRect().top - STORY_TOP
    window.scrollTo({ top: top + (STORY_STOPS[index] ?? 0) * Math.max(0, area.offsetHeight - panel.offsetHeight), behavior: 'smooth' })
  }

  const date = data ? new Intl.DateTimeFormat('en-US', { month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(data.date)) : ''
  const timestamp = data ? [data.events[0]!.elapsed, data.events[1]!.elapsed, data.events[3]!.elapsed, data.events[6]!.elapsed][stage] : ''
  const chapter = CHAPTERS[stage] ?? CHAPTERS[0]
  return <section className="frame run-story" id="daily-lab" ref={root} data-testid="run-story" data-mode={enhanced ? 'scroll' : 'static'} data-stage={stage} data-active={active} data-run-id={data?.runId} style={storyFrame(0) as CSSProperties} aria-labelledby="run-story-title">
    {data ? <p className="sr-only">Recorded parser: {data.preset}. Suite: {data.counts.total} cases, including {data.counts.faultInjected} fault-injected cases.</p> : null}
    <div className="run-story-track" data-testid="run-story-track" ref={track}>
      <div className="run-story-sticky" data-testid="run-story-sticky" ref={sticky}>
        <header className="run-story-heading"><div><p className="eyebrow">01 / Inside Daily Lab</p><h2 id="run-story-title">Follow a parser run.</h2></div><Link href="/lab#run" className="button-primary">Run the default parser <span aria-hidden="true">↗</span></Link></header>
        {data ? <div className="run-story-animation">
          <nav className="run-rail" aria-label="Recorded run stages"><span className="run-rail-line" aria-hidden="true"><i /></span>{CHAPTERS.map((chapter, i) => <button key={chapter.id} type="button" aria-current={stage === i ? 'step' : undefined} onClick={() => select(i)}><span className="run-rail-number" aria-hidden="true">0{i + 1}</span><span>{chapter.name}</span><i aria-hidden="true" /></button>)}<span className="run-scroll-hint">Scroll to follow <span aria-hidden="true">↓</span></span></nav>
          <div className="run-story-scene">
            <div className="run-recording-label"><span><i aria-hidden="true" /> Recorded run</span><time dateTime={data.date}>{date}</time></div>
            <div className="run-scene-canvas">
              <RunDiagram data={data} />
              <div className="run-scene-checks" aria-hidden={stage !== 2}><p>Isolation checks <span>{data.events[4]!.elapsed}s</span></p><Probes data={data} /></div>
              <div className="run-scene-result" aria-hidden={stage !== 3}><Verdict data={data} identified={enhanced} /></div>
            </div>
            <div className="run-scene-caption"><div key={stage}><span className="run-chapter-index">0{stage + 1} / {chapter.name}</span><h3>{chapter.title}</h3><p>{chapter.copy}</p></div><div className="run-event-time"><span>{timestamp}<small>s</small></span><p>{stage === 3 ? 'microVM stopped' : stage === 2 ? 'harness started' : stage === 1 ? 'creating microVM' : 'scope checked'}</p></div></div>
          </div>
        </div> : <div className="run-story-unavailable" role="status"><p>The recorded run is unavailable.</p><p>Open the Lab to inspect or run a parser.</p></div>}
      </div>
      {data ? <div className="run-story-chapters"><p className="run-static-recording">Recorded run · {date}</p>{CHAPTERS.map((chapter, i) => <article key={chapter.id} className="run-story-chapter" data-chapter={chapter.id} data-testid="run-story-stage" data-index={i}>
        <div className="run-chapter-copy"><span className="run-chapter-index">0{i + 1} / {chapter.name}</span><h3>{chapter.title}</h3><p>{chapter.copy}</p></div>
        <div className="run-static-visual">{i < 3 ? <><RunDiagram data={data} chapter={i} /><p className="run-static-caption">{i === 0 ? <><code>candidate.py</code><span>{data.preset}</span></> : i === 1 ? <><span>Vercel Sandbox</span><span>Networking denied</span></> : <><span>{data.counts.total} cases</span><span>{data.counts.faultInjected} fault-injected</span></>}</p></> : <Verdict data={data} identified={!enhanced} />}{i === 2 ? <Probes data={data} /> : null}{i === 3 ? <Link className="text-link run-static-action" href="/lab#run">Try your parser <span aria-hidden="true">↗</span></Link> : null}</div>
      </article>)}</div> : null}
    </div>
    {data ? <RecordingDetails data={data} /> : null}
    <noscript><style>{'.run-story-track{height:auto!important}.run-story-sticky{position:static!important}.run-story-animation{display:none!important}.run-story-chapters{display:block!important}'}</style></noscript>
  </section>
}
