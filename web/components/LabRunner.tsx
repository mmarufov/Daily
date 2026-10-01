'use client'

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

  return (
    <div className="flex flex-col gap-10">
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
        <div className="flex min-w-0 flex-col gap-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <p className="label m-0 shrink-0 text-ink-40">Start from</p>
            <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
              {presets.map((p) => (
                <li key={p.id}>
                  <button
                    type="button"
                    onClick={() => choose(p)}
                    aria-pressed={p.id === presetId && !edited}
                    className={`chip ${p.id === presetId && !edited ? 'chip-on' : ''}`}
                  >
                    {p.id}
                    <span className="ml-1.5 opacity-60">{p.note}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
          <label htmlFor="candidate-source" className="flex items-baseline justify-between gap-3 text-xs text-ink-40">
            <span>
              <span className="font-mono text-ink-60">candidate.py</span>, the only file a candidate may write
              {edited ? <span className="text-signal"> · edited</span> : null}
            </span>
            <span className={bytes > maxBytes ? 'text-signal' : ''}>
              {bytes.toLocaleString('en-US')} of {maxBytes.toLocaleString('en-US')} bytes
            </span>
          </label>
          {/* `data-verbatim`: the editor opens on committed source, byte for
              byte, and then holds whatever the visitor types. Neither is the
              site's own copy, and rewriting a parser's docstring to suit the
              house style would change the thing under test. */}
          <textarea
            id="candidate-source"
            data-verbatim
            value={source}
            onChange={(e) => setSource(e.target.value)}
            onKeyDown={onKeyDown}
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            wrap="off"
            className="h-[26rem] w-full resize-y border border-rule bg-paper-secondary p-3 font-mono text-[12px] leading-relaxed text-ink outline-none focus-visible:border-ink"
          />
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
            <button
              type="button"
              onClick={() => void run()}
              disabled={busy || bytes === 0 || bytes > maxBytes}
              className="chip chip-on px-4 py-2.5 text-sm disabled:cursor-not-allowed disabled:opacity-50"
            >
              {phase.kind === 'starting' ? 'Starting' : busy ? 'Running' : 'Run it in a microVM'}
            </button>
            <p className="m-0 text-xs text-ink-40">Tab indents. Press Esc, then Tab, to leave the editor.</p>
          </div>
          <p className="m-0 max-w-2xl text-xs text-ink-40">{limits}</p>
        </div>

        <aside className="flex min-w-0 flex-col gap-4 border-t border-rule-strong pt-4 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-6" aria-live="polite">
          <Status phase={phase} />
        </aside>
      </div>

      {watching !== null && watching.outcome !== null ? (
        <LiveResult runId={watching.runId} outcome={watching.outcome} catalog={catalog} />
      ) : (
        <CaseGrid catalog={catalog} grading={null} />
      )}
    </div>
  )
}

function Status({ phase }: { phase: Phase }) {
  if (phase.kind === 'idle') {
    return (
      <>
        <p className="label m-0 text-ink">What happens when you press run</p>
        <ol className="m-0 flex list-decimal flex-col gap-2 pl-4 text-sm text-ink-60">
          <li>The scope gate checks that only candidate.py is written.</li>
          <li>
            A fresh microVM boots with networking denied and no credentials. It receives the harness,
            the 64 responses with their answers stripped out, and your file.
          </li>
          <li>The harness calls your parse() on every case and prints what it returned.</li>
          <li>
            Four probes, run inside the same microVM, check that DNS and HTTPS fail and that neither
            the evaluator nor a credential is present.
          </li>
          <li>The records are graded here, by code the microVM never held.</li>
        </ol>
      </>
    )
  }
  if (phase.kind === 'starting') return <p className="label m-0 text-ink">Starting</p>
  if (phase.kind === 'refused') return <Refused refusal={phase.refusal} />
  if (phase.kind === 'unavailable') {
    return (
      <>
        <p className="label m-0 text-unknown">Not started</p>
        <p className="m-0 text-sm text-ink-60">{phase.message}</p>
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
      <p className="label m-0 text-signal">Not started: {LIMIT_NAME[refusal.limit] ?? refusal.limit}</p>
      <p className="m-0 text-sm text-ink">{refusal.error}</p>
      <p className="m-0 text-xs text-ink-40">
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
      ? 'Not found'
      : phase.finished
        ? phase.status === 'completed'
          ? 'Finished'
          : `Ended ${phase.status}`
        : phase.status === 'running'
          ? 'Running'
          : 'Queued'

  return (
    <>
      <p className="label m-0 text-ink">
        {label}
        {elapsed !== null ? (
          <span className="ml-2 font-mono text-ink-40" aria-hidden="true">
            {elapsed.toFixed(1)} s
          </span>
        ) : null}
      </p>
      {phase.lost !== null ? <p className="m-0 text-sm text-ink-60">{phase.lost}</p> : null}
      {events.length > 0 ? (
        <ol className="m-0 flex list-none flex-col gap-1 p-0 text-xs">
          {events.map((e, i) => (
            <li key={`${e.at}-${i}`} className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-2">
              <span className="text-right font-mono text-ink-40">
                {origin === null ? '' : `${((Date.parse(e.at) - origin) / 1000).toFixed(1)} s`}
              </span>
              <span className="text-ink-60">{e.stage}</span>
            </li>
          ))}
        </ol>
      ) : phase.progress === null && !phase.finished ? (
        <p className="m-0 text-xs text-ink-40">Waiting for the first event from the run.</p>
      ) : null}
      {phase.finished && phase.status === 'completed' && phase.outcome === null ? (
        <p className="m-0 text-sm text-unknown">The run finished but its result could not be read.</p>
      ) : null}
      {phase.finished && phase.status !== 'completed' && phase.lost === null ? (
        <p className="m-0 text-sm text-unknown">The run ended without a verdict. Nothing about the parser was established.</p>
      ) : null}
      <p className="m-0 break-all text-[11px] text-ink-40">
        run {phase.runId}
        {phase.left !== null ? (
          <span className="block pt-0.5">
            This address can start {phase.left} more {phase.left === 1 ? 'run' : 'runs'} this hour.
          </span>
        ) : null}
      </p>
    </>
  )
}
