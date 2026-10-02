'use client'

import { AnimatedDetails } from '@/components/AnimatedDetails'

import { useEffect, useRef, useState } from 'react'

import type { CatalogCase, LiveOutcome, ProgressEvent, RunStatusBody } from '@/lib/lab/live'
import type { Refusal } from '@/lib/lab/public-limits'
import type { RunnerPreset } from '@/lib/lab/runner-presets'

import { CaseGrid, LiveResult } from './LabLiveResult'

/**
 * Paste a parser, run it in a real microVM, watch it graded.
 *
 * The page polls the public status route rather than holding a stream open:
 * a poll is a short request that ends, so a visitor who closes the tab leaves
 * nothing running on their behalf. The run itself does not depend on the page
 * at all, and `?run=` brings a reload back to it.
 */

type Phase =
  | { readonly kind: 'idle' }
  | { readonly kind: 'starting' }
  | { readonly kind: 'refused'; readonly refusal: Refusal }
  | { readonly kind: 'unavailable'; readonly message: string }
  | {
      readonly kind: 'watching'
      readonly runId: string
      /** When this page sent the request; null when resumed from a link. */
      readonly sentAt: number | null
      readonly status: RunStatusBody['status'] | 'starting'
      readonly progress: readonly ProgressEvent[] | null
      readonly outcome: LiveOutcome | null
      readonly finished: boolean
      readonly lost: string | null
      /** Runs this address may still start this hour, as the server counted. */
      readonly left: number | null
    }

const RUN_ID = /^[A-Za-z0-9_-]{1,128}$/
const POLL_MS = 1500
/** Past this a run is not polled further; the microVM lives 120 s at most. */
const GIVE_UP_MS = 10 * 60 * 1000

const LIMIT_NAME: Record<Refusal['limit'], string> = {
  'per-address': 'the hourly limit for one address',
  concurrent: 'the limit on runs at once',
  'daily-runs': 'the daily run ceiling',
  'daily-cpu': 'the daily CPU allowance',
}

export function LabRunner({
  presets,
  catalog,
  limits,
  maxBytes,
}: {
  presets: readonly RunnerPreset[]
  catalog: readonly CatalogCase[]
  limits: string
  maxBytes: number
}) {
  const [presetId, setPresetId] = useState(presets[0]?.id ?? '')
  const [source, setSource] = useState(presets[0]?.source ?? '')
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })
  const leavingEditor = useRef(false)

  const bytes = new TextEncoder().encode(source).length
  const edited = presets.find((p) => p.id === presetId)?.source !== source
  const busy = phase.kind === 'starting' || (phase.kind === 'watching' && !phase.finished)

  // A link to a run brings the page back to it.
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get('run')
    if (id !== null && RUN_ID.test(id)) {
      setPhase({ kind: 'watching', runId: id, sentAt: null, status: 'starting', progress: null, outcome: null, finished: false, lost: null, left: null })
    }
  }, [])

  const runId = phase.kind === 'watching' ? phase.runId : null
  useEffect(() => {
    if (runId === null) return
    const controller = new AbortController()
    const began = Date.now()
    let timer: ReturnType<typeof setTimeout> | undefined

    const update = (patch: Partial<Extract<Phase, { kind: 'watching' }>>) =>
      setPhase((p) => (p.kind === 'watching' && p.runId === runId ? { ...p, ...patch } : p))

    const poll = async () => {
      try {
        const response = await fetch(`/api/lab/run/${runId}`, { signal: controller.signal, cache: 'no-store' })
        if (response.status === 404) {
          update({ finished: true, lost: 'There is no run with that id.' })
          return
        }
        if (response.ok) {
          const body = (await response.json()) as RunStatusBody
          update({
            status: body.status,
            progress: body.progress,
            outcome: body.outcome,
            finished: body.finished,
          })
          if (body.finished) return
        }
      } catch {
        if (controller.signal.aborted) return
        // A failed poll is a missed poll. The run does not depend on this page.
      }
      if (Date.now() - began > GIVE_UP_MS) {
        update({ finished: true, lost: 'Stopped watching after ten minutes. Reload to check again.' })
        return
      }
      timer = setTimeout(poll, POLL_MS)
    }
    void poll()
    return () => {
      controller.abort()
      if (timer !== undefined) clearTimeout(timer)
    }
  }, [runId])

  async function run() {
    setPhase({ kind: 'starting' })
    let response: Response
    try {
      response = await fetch('/api/lab/run', {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ candidate_id: 'visitor', source }),
      })
    } catch {
      setPhase({ kind: 'unavailable', message: 'The request did not reach the server. Nothing was started.' })
      return
    }
    const body = (await response.json().catch(() => ({}))) as Record<string, unknown>
    if (response.status === 202 && typeof body.run_id === 'string') {
      window.history.replaceState(null, '', `?run=${body.run_id}#run`)
      setPhase({
        kind: 'watching',
        runId: body.run_id,
        sentAt: Date.now(),
        status: 'starting',
        progress: null,
        outcome: null,
        finished: false,
        lost: null,
        left: typeof body.address_runs_left === 'number' ? body.address_runs_left : null,
      })
      return
    }
    if (response.status === 429 && typeof body.limit === 'string') {
      setPhase({ kind: 'refused', refusal: body as unknown as Refusal })
      return
    }
    setPhase({
      kind: 'unavailable',
      message: typeof body.error === 'string' ? body.error : `The server answered ${response.status}. Nothing was started.`,
    })
  }

  function choose(preset: RunnerPreset) {
    setPresetId(preset.id)
    setSource(preset.source)
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Tab indents, because this is Python. Escape then Tab leaves the editor,
    // so a keyboard user is never trapped in it.
    if (event.key === 'Escape') {
      leavingEditor.current = true
      return
    }
    if (event.key !== 'Tab' || event.shiftKey || leavingEditor.current) {
      leavingEditor.current = false
      return
    }
    event.preventDefault()
    const el = event.currentTarget
    const { selectionStart: start, selectionEnd: end } = el
    const next = `${source.slice(0, start)}    ${source.slice(end)}`
    setSource(next)
    requestAnimationFrame(() => {
      el.selectionStart = start + 4
      el.selectionEnd = start + 4
    })
  }

  const watching = phase.kind === 'watching' ? phase : null
  const complete = watching?.finished === true && watching.status === 'completed'

  return (
    <div className="lab-runner">
      <div className="lab-workspace">
        <div className="lab-workspace-toolbar">
          <div className="lab-presets">
            <p className="eyebrow">Start from a parser</p>
            <ul className="lab-preset-list">
              {presets.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    onClick={() => choose(p)}
                    aria-pressed={p.id === presetId && !edited}
                    className="lab-preset"
                  >
                    <span>{p.id}</span>
                    <span className="lab-preset-note">{p.note}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <button
            type="button"
            onClick={() => void run()}
            disabled={busy || bytes === 0 || bytes > maxBytes}
            className="button-primary lab-run-button"
          >
            <span aria-hidden="true">{busy ? '◌' : '↗'}</span>
            {phase.kind === 'starting' ? 'Starting' : busy ? 'Running' : 'Run in Sandbox'}
          </button>
        </div>

        <div className="lab-workspace-panels">
          <div className="lab-editor-panel">
            <label htmlFor="candidate-source" className="lab-panel-heading">
              <span>
                <span className="lab-filename">candidate.py</span>
                {edited ? <span className="lab-edited"> · edited</span> : null}
              </span>
              <span id="source-byte-count" className={`lab-byte-count ${bytes > maxBytes ? 'lab-byte-limit' : ''}`}>
                {bytes.toLocaleString('en-US')} / {maxBytes.toLocaleString('en-US')} bytes
              </span>
            </label>
            {/* The editor holds committed source or the visitor's own bytes. */}
            <textarea
              id="candidate-source"
              aria-label="Python parser source"
              aria-describedby="source-byte-count source-keyboard-help"
              data-verbatim
              value={source}
              onChange={(e) => setSource(e.target.value)}
              onKeyDown={onKeyDown}
              spellCheck={false}
              autoCapitalize="off"
              autoCorrect="off"
              wrap="off"
              className="lab-source-editor"
            />
            <p id="source-keyboard-help" className="lab-editor-help">
              Python · Tab indents. Press Esc, then Tab, to leave the editor.
            </p>
          </div>

          <aside
            className="lab-console"
            aria-label="Run event console"
            aria-live="polite"
            aria-atomic="false"
            data-run-state={phase.kind === 'watching' ? phase.status : phase.kind}
          >
            <div className="lab-panel-heading">
              <h2>Event console</h2>
              <span className="lab-console-source">From the backend</span>
            </div>
            <div className="lab-console-body">
              <Status phase={phase} />
            </div>
            <p className="lab-console-footnote">Case grades appear after the run completes.</p>
          </aside>
        </div>
      </div>

      <div className="lab-runner-meta">
        <p>{limits}</p>
        <AnimatedDetails className="lab-run-explainer">
          <summary className="disclosure">How a run works</summary>
          <ol>
            <li>The scope gate checks that only candidate.py is written.</li>
            <li>
              A fresh microVM boots with networking denied and no credentials. It receives the
              harness, the {catalog.length} responses with their answers stripped out, and your file.
            </li>
            <li>The harness calls your parse() on every case and records what it returns.</li>
            <li>
              Four probes check that DNS and HTTPS fail and that neither the evaluator nor a
              credential is present.
            </li>
            <li>The records are graded outside the microVM by the independent evaluator.</li>
          </ol>
        </AnimatedDetails>
      </div>

      {complete && watching.outcome !== null ? (
        <div className="lab-completed-result" aria-label="Completed run result">
          <LiveResult runId={watching.runId} outcome={watching.outcome} catalog={catalog} />
        </div>
      ) : (
        <div className="lab-case-preview">
          <div className="lab-case-preview-heading">
            <h3>The case suite</h3>
            <p>{busy ? 'Awaiting completed grading' : 'Ready to test'} · {catalog.length} cases</p>
          </div>
          <CaseGrid catalog={catalog} grading={null} />
        </div>
      )}
    </div>
  )
}

function Status({ phase }: { phase: Phase }) {
  if (phase.kind === 'idle') {
    return (
      <div className="lab-console-idle">
        <span className="lab-console-prompt" aria-hidden="true">&gt;_</span>
        <p className="lab-status-title">Ready when you are.</p>
        <p>Choose a parser or write your own, then press Run in Sandbox.</p>
        <p className="lab-console-muted">This console will show the actual stages reported by your run.</p>
      </div>
    )
  }
  if (phase.kind === 'starting') {
    return (
      <>
        <p className="lab-status-title">Starting</p>
        <p className="lab-console-muted">Waiting for the server to accept this request.</p>
      </>
    )
  }
  if (phase.kind === 'refused') return <Refused refusal={phase.refusal} />
  if (phase.kind === 'unavailable') {
    return (
      <>
        <p className="lab-status-title lab-console-warning">Not started</p>
        <p>{phase.message}</p>
      </>
    )
  }
  return <Watching phase={phase} />
}

function Refused({ refusal }: { refusal: Refusal }) {
  const resets = new Date(refusal.resets_at)
  const minutes = Math.max(1, Math.round(refusal.retry_after_seconds / 60))
  return (
    <>
      <p className="lab-status-title lab-console-warning">Not started: {LIMIT_NAME[refusal.limit] ?? refusal.limit}</p>
      <p>{refusal.error}</p>
      <p className="lab-console-muted">
        Resets at {resets.toISOString().slice(11, 16)} UTC, in about {minutes} minute{minutes === 1 ? '' : 's'}.
        A refused request is not counted against you.
      </p>
    </>
  )
}

function Watching({ phase }: { phase: Extract<Phase, { kind: 'watching' }> }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (phase.finished) return
    const id = setInterval(() => setNow(Date.now()), 250)
    return () => clearInterval(id)
  }, [phase.finished])

  const events = phase.progress ?? []
  const origin = events[0] !== undefined ? Date.parse(events[0].at) : null
  const elapsed = phase.sentAt !== null && !phase.finished ? (now - phase.sentAt) / 1000 : null
  const label =
    phase.lost !== null
      ? phase.lost.startsWith('Stopped watching') ? 'Watching paused' : 'Not found'
      : phase.finished
        ? phase.status === 'completed'
          ? 'Finished'
          : `Ended ${phase.status}`
        : phase.status === 'running'
          ? 'Running'
          : 'Queued'

  return (
    <>
      <p className="lab-status-title">
        {label}
        {elapsed !== null ? (
          <span className="lab-elapsed" aria-hidden="true">
            {elapsed.toFixed(1)} s
          </span>
        ) : null}
      </p>
      {phase.lost !== null ? <p className="lab-console-warning">{phase.lost}</p> : null}
      {events.length > 0 ? (
        <ol className="lab-event-list" aria-label="Events from this run">
          {events.map((e, i) => (
            <li key={`${e.at}-${i}`} data-run-stage={e.stage}>
              <span className="lab-event-time">
                {origin === null ? '' : `${((Date.parse(e.at) - origin) / 1000).toFixed(1)} s`}
              </span>
              <span>{e.stage}</span>
            </li>
          ))}
        </ol>
      ) : !phase.finished ? (
        <p className="lab-console-muted">
          {phase.progress === null ? 'Waiting for the first event from the run.' : 'No stage events reported yet.'}
        </p>
      ) : null}
      {phase.finished && phase.status === 'completed' && phase.outcome === null ? (
        <p className="lab-console-warning">The run finished but its result could not be read.</p>
      ) : null}
      {phase.finished && phase.status !== 'completed' && phase.lost === null ? (
        <p className="lab-console-warning">The run ended without a verdict. Nothing about the parser was established.</p>
      ) : null}
      <p className="lab-run-reference">
        <a href={`?run=${phase.runId}#run`} className="lab-run-link">run {phase.runId}</a>
        {phase.left !== null ? (
          <span>
            This address can start {phase.left} more {phase.left === 1 ? 'run' : 'runs'} this hour.
          </span>
        ) : null}
      </p>
    </>
  )
}
