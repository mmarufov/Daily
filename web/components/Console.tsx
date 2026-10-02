'use client'

import Link from 'next/link'
import { useEffect, useMemo, useRef, useState } from 'react'

import type { RecordedRun } from '@/lib/home'
import {
  caughtByFault,
  type CatalogCase,
  type LiveCase,
  type LiveGrading,
  type LiveOutcome,
  type ProgressEvent,
  type RunStatusBody,
  type SandboxSummary,
} from '@/lib/lab/live'
import type { Refusal } from '@/lib/lab/public-limits'
import type { RunnerPreset } from '@/lib/lab/runner-presets'

import { RunDetail } from './RunDetail'

/**
 * The Lab's instrument panel: choose a parser, run it in a real microVM,
 * watch what actually happens, read the verdict.
 *
 * Two places use it. The homepage opens it on a recorded production run, so
 * the result is on screen before anyone clicks, and labels it as recorded.
 * `/lab` opens it empty, with an editor. Either way, pressing Run starts a
 * real run; nothing on this panel is animated to look like progress. The
 * timeline is the run's own event stream with the run's own timestamps, the
 * stopwatch is this browser's clock, and the 64 cells change only when a
 * graded result exists.
 *
 * The page polls the public status route rather than holding a stream open:
 * a poll is a short request that ends, so a visitor who closes the tab leaves
 * nothing running on their behalf. `?run=` brings a reload back to the run.
 */

type Watching = {
  readonly kind: 'watching'
  readonly runId: string
  /** When this page sent the request; null when resumed from a link. */
  readonly sentAt: number | null
  readonly endedAt: number | null
  readonly status: RunStatusBody['status'] | 'starting'
  readonly progress: readonly ProgressEvent[] | null
  readonly outcome: LiveOutcome | null
  readonly finished: boolean
  readonly lost: string | null
  /** Runs this address may still start this hour, as the server counted. */
  readonly left: number | null
}

type Phase =
  | { readonly kind: 'recorded' }
  | { readonly kind: 'idle' }
  | { readonly kind: 'starting' }
  | { readonly kind: 'refused'; readonly refusal: Refusal }
  | { readonly kind: 'unavailable'; readonly message: string }
  | Watching

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

/** The steps a run goes through, shown greyed before one has started. */
const PLAN = [
  'scope check: only candidate.py may change',
  'create a microVM, networking denied',
  'upload the harness, the cases and the parser',
  'run the harness',
  'probe isolation from inside',
  'stop the microVM',
  'grade outside it',
]

const PROBE_LABEL: Record<string, string> = {
  'egress-dns': 'DNS lookup fails',
  'egress-https': 'HTTPS request fails',
  'no-evaluator-present': 'Grader not on disk',
  'no-secrets-in-env': 'No credentials in env',
}

export function Console({
  presets,
  catalog,
  recorded,
  limitsLine,
  maxBytes,
  variant,
}: {
  presets: readonly RunnerPreset[]
  catalog: readonly CatalogCase[]
  recorded: RecordedRun | null
  limitsLine: string
  maxBytes: number
  variant: 'hero' | 'lab'
}) {
  const initialPreset =
    (recorded !== null && variant === 'hero' ? presets.find((p) => p.id === recorded.preset) : undefined) ?? presets[0]
  const [presetId, setPresetId] = useState(initialPreset?.id ?? '')
  const [source, setSource] = useState(initialPreset?.source ?? '')
  const [phase, setPhase] = useState<Phase>(
    recorded !== null && variant === 'hero' ? { kind: 'recorded' } : { kind: 'idle' },
  )
  const leavingEditor = useRef(false)

  const bytes = useMemo(() => new TextEncoder().encode(source).length, [source])
  const preset = presets.find((p) => p.id === presetId)
  const edited = preset?.source !== source
  const busy = phase.kind === 'starting' || (phase.kind === 'watching' && !phase.finished)

  // A link to a run brings the panel back to it.
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get('run')
    if (id !== null && RUN_ID.test(id)) {
      setPhase({
        kind: 'watching',
        runId: id,
        sentAt: null,
        endedAt: null,
        status: 'starting',
        progress: null,
        outcome: null,
        finished: false,
        lost: null,
        left: null,
      })
    }
  }, [])

  const runId = phase.kind === 'watching' ? phase.runId : null
  useEffect(() => {
    if (runId === null) return
    const controller = new AbortController()
    const began = Date.now()
    let timer: ReturnType<typeof setTimeout> | undefined

    const update = (patch: Partial<Watching>) =>
      setPhase((p) => (p.kind === 'watching' && p.runId === runId ? { ...p, ...patch } : p))

    const poll = async () => {
      try {
        const response = await fetch(`/api/lab/run/${runId}`, { signal: controller.signal, cache: 'no-store' })
        if (response.status === 404) {
          update({ finished: true, endedAt: Date.now(), lost: 'There is no run with that id.' })
          return
        }
        if (response.ok) {
          const body = (await response.json()) as RunStatusBody
          update({
            status: body.status,
            progress: body.progress,
            outcome: body.outcome,
            finished: body.finished,
            ...(body.finished ? { endedAt: Date.now() } : {}),
          })
          if (body.finished) return
        }
      } catch {
        if (controller.signal.aborted) return
        // A failed poll is a missed poll. The run does not depend on this page.
      }
      if (Date.now() - began > GIVE_UP_MS) {
        update({ finished: true, endedAt: Date.now(), lost: 'Stopped watching after ten minutes. Reload to check again.' })
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
        endedAt: null,
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
      message:
        typeof body.error === 'string' ? body.error : `The server answered ${response.status}. Nothing was started.`,
    })
  }

  function choose(next: RunnerPreset) {
    if (busy) return
    setPresetId(next.id)
    setSource(next.source)
    // The recorded result belongs to one parser. Choosing another clears it
    // rather than leaving a verdict on screen that this parser never got.
    if (phase.kind !== 'watching' || phase.finished) setPhase({ kind: 'idle' })
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
    setSource(`${source.slice(0, start)}    ${source.slice(end)}`)
    requestAnimationFrame(() => {
      el.selectionStart = start + 4
      el.selectionEnd = start + 4
    })
  }

  // What the panel is showing: the recorded run, a live one, or nothing yet.
  const shown =
    phase.kind === 'recorded' && recorded !== null
      ? {
          live: false,
          runId: recorded.body.run_id,
          events: recorded.body.progress ?? [],
          outcome: recorded.body.outcome,
          finished: true,
        }
      : phase.kind === 'watching'
        ? {
            live: true,
            runId: phase.runId,
            events: phase.progress ?? [],
            outcome: phase.outcome,
            finished: phase.finished,
          }
        : null

  const grading = shown?.outcome?.grading ?? null
  const sandbox = shown?.outcome?.sandbox ?? null
  const runLabel = variant === 'hero' ? 'Run it live' : 'Run it in a microVM'

  return (
    <div className="flex flex-col gap-4" id={variant === 'lab' ? undefined : 'run'}>
      <div className="panel console overflow-hidden">
        {/* Toolbar: which parser, and the one action. */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-rule px-3 py-2.5 sm:px-4">
          <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">
            <span className="data hidden items-center gap-1.5 text-ink-60 sm:inline-flex">
              <FileGlyph />
              candidate.py
            </span>
            <span className="hidden h-4 w-px bg-rule sm:block" aria-hidden="true" />
            <div role="group" aria-label="Start from" className="flex min-w-0 max-w-full gap-1 overflow-x-auto [scrollbar-width:none]">
              {presets.map((p) => {
                const on = p.id === presetId && !edited
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => choose(p)}
                    aria-pressed={on}
                    disabled={busy}
                    title={p.note}
                    className={`chip data !text-[0.75rem] ${on ? 'chip-on' : ''}`}
                  >
                    {p.id}
                  </button>
                )
              })}
            </div>
            <span className="hidden text-[0.8125rem] text-ink-40 lg:inline">
              {edited ? 'edited' : preset?.note}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {variant === 'hero' ? (
              <Link href="/lab#run" className="btn btn-secondary h-9 px-3 text-[0.8125rem]">
                Edit the code
              </Link>
            ) : null}
            <button
              type="button"
              onClick={() => void run()}
              disabled={busy || bytes === 0 || bytes > maxBytes}
              className="btn btn-primary h-9 px-3.5 text-[0.8125rem]"
            >
              {phase.kind === 'starting' ? 'Starting' : busy ? 'Running' : runLabel}
              {!busy ? <PlayGlyph /> : <Spinner />}
            </button>
          </div>
        </div>

        <StatusStrip phase={phase} recorded={recorded} />

        {variant === 'lab' ? (
          <div className="border-b border-rule">
            <label
              htmlFor="candidate-source"
              className="flex items-baseline justify-between gap-3 px-4 pt-3 text-[0.75rem] text-ink-40"
            >
              <span>
                <span className="data text-ink-60">candidate.py</span>, the only file a candidate may write
              </span>
              <span className={`data ${bytes > maxBytes ? 'text-signal' : ''}`}>
                {bytes.toLocaleString('en-US')} of {maxBytes.toLocaleString('en-US')} bytes
              </span>
            </label>
            {/* `data-verbatim`: the editor opens on committed source, byte for
                byte, and then holds whatever the visitor types. Neither is the
                site's own copy. */}
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
              className="block h-[22rem] w-full resize-y bg-transparent px-4 py-3 font-mono text-[12px] leading-relaxed text-ink outline-none"
            />
          </div>
        ) : null}

        <div className="grid lg:grid-cols-[minmax(0,19rem)_minmax(0,1fr)_minmax(0,19rem)]">
          <section aria-label="What the run did" className="min-w-0 border-b border-rule p-4 lg:border-r lg:border-b-0 sm:p-5">
            <PaneTitle>Run</PaneTitle>
            <Timeline shown={shown} sandbox={sandbox} />
          </section>

          <section aria-label="Cases" className="min-w-0 border-b border-rule p-4 lg:border-r lg:border-b-0 sm:p-5">
            <PaneTitle>{catalog.length} cases</PaneTitle>
            <CaseField catalog={catalog} grading={shown !== null && shown.finished ? grading : null} />
          </section>

          <section aria-label="Verdict" className="min-w-0 p-4 sm:p-5" aria-live="polite">
            <PaneTitle>Verdict</PaneTitle>
            <Verdict phase={phase} shown={shown} />
          </section>
        </div>

        {sandbox !== null && shown !== null && shown.finished ? <Meters sandbox={sandbox} /> : null}
      </div>

      <p className="m-0 max-w-3xl text-[0.8125rem] text-ink-40">{limitsLine}</p>

      {variant === 'lab' && phase.kind === 'watching' && phase.finished && phase.outcome !== null ? (
        <RunDetail runId={phase.runId} outcome={phase.outcome} />
      ) : null}
    </div>
  )
}

/* ------------------------------------------------------------ strip --- */

function StatusStrip({ phase, recorded }: { phase: Phase; recorded: RecordedRun | null }) {
  const now = useClock(phase.kind === 'watching' && !phase.finished && phase.sentAt !== null)

  let left: React.ReactNode
  let right: React.ReactNode = null

  if (phase.kind === 'recorded' && recorded !== null) {
    const first = recorded.body.progress?.[0]?.at
    left = (
      <>
        <Pill tone="quiet">Recorded</Pill>
        <span className="text-ink-60">
          A real run on production{first !== undefined ? `, ${utc(first)}` : ''}
        </span>
      </>
    )
    right = (
      <a href={`/runs/${recorded.body.run_id}.json`} className="data link min-w-0 truncate text-ink-40">
        {recorded.body.run_id}
      </a>
    )
  } else if (phase.kind === 'idle') {
    left = (
      <>
        <Pill tone="quiet">Ready</Pill>
        <span className="text-ink-60">Each run gets a fresh microVM with networking denied.</span>
      </>
    )
  } else if (phase.kind === 'starting') {
    left = (
      <>
        <Pill tone="live">Live</Pill>
        <span className="text-ink-60">Starting</span>
      </>
    )
  } else if (phase.kind === 'refused') {
    const r = phase.refusal
    const minutes = Math.max(1, Math.round(r.retry_after_seconds / 60))
    left = (
      <div className="flex flex-col gap-0.5">
        <p className="m-0 font-medium text-ink">Not started: {LIMIT_NAME[r.limit] ?? r.limit}</p>
        <p className="m-0 text-ink-60">{r.error}</p>
        <p className="m-0 text-ink-40">
          Resets at {new Date(r.resets_at).toISOString().slice(11, 16)} UTC, in about {minutes} minute
          {minutes === 1 ? '' : 's'}. A refused request is not counted against you.
        </p>
      </div>
    )
  } else if (phase.kind === 'unavailable') {
    left = (
      <div className="flex flex-col gap-0.5">
        <p className="m-0 font-medium text-ink">Not started</p>
        <p className="m-0 text-ink-60">{phase.message}</p>
      </div>
    )
  } else if (phase.kind === 'watching') {
    const elapsed =
      phase.sentAt === null ? null : ((phase.finished ? (phase.endedAt ?? now) : now) - phase.sentAt) / 1000
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
    left = (
      <>
        <Pill tone={phase.finished ? 'quiet' : 'live'}>Live</Pill>
        <span className="text-ink">{label}</span>
        {elapsed !== null ? (
          <span className="data text-ink-40" aria-hidden={!phase.finished}>
            {elapsed.toFixed(1)} s{phase.finished ? ' from the click to the verdict, on this browser’s clock' : ''}
          </span>
        ) : null}
        {phase.lost !== null ? <span className="text-ink-60">{phase.lost}</span> : null}
      </>
    )
    right = (
      <span className="data hidden text-ink-40 sm:inline">
        run {phase.runId}
        {phase.left !== null ? (
          <span className="ml-3 font-sans">
            {phase.left} more {phase.left === 1 ? 'run' : 'runs'} this hour from this address
          </span>
        ) : null}
      </span>
    )
  }

  return (
    <div className="flex min-h-11 flex-wrap items-center justify-between gap-x-4 gap-y-1 border-b border-rule bg-paper-secondary px-3 py-2 text-[0.8125rem] sm:px-4">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">{left}</div>
      {right}
    </div>
  )
}

function Pill({ children, tone }: { children: React.ReactNode; tone: 'live' | 'quiet' }) {
  return (
    <span
      className={`inline-flex h-5 items-center gap-1.5 rounded-full px-2 text-[0.6875rem] font-medium ${
        tone === 'live' ? 'bg-ink text-paper' : 'border border-rule-strong bg-sheet text-ink-60'
      }`}
    >
      {tone === 'live' ? <span className="size-1.5 animate-[blink_1.2s_ease-in-out_infinite] rounded-full bg-paper" /> : null}
      {children}
    </span>
  )
}

/* --------------------------------------------------------- timeline --- */

interface Shown {
  readonly live: boolean
  readonly runId: string
  readonly events: readonly ProgressEvent[]
  readonly outcome: LiveOutcome | null
  readonly finished: boolean
}

function Timeline({ shown, sandbox }: { shown: Shown | null; sandbox: SandboxSummary | null }) {
  if (shown === null) {
    return (
      <ol className="timeline m-0 list-none p-0" aria-label="What a run does">
        {PLAN.map((step) => (
          <li key={step} className="timeline-row" data-state="planned">
            <span className="timeline-t" />
            <span className="timeline-dot" aria-hidden="true" />
            <span className="text-ink-40">{step}</span>
          </li>
        ))}
      </ol>
    )
  }

  const origin = shown.events[0] !== undefined ? Date.parse(shown.events[0].at) : null
  const waiting = shown.live && !shown.finished
  return (
    <ol className="timeline m-0 list-none p-0">
      {shown.events.map((e, i) => {
        const probing = e.stage === 'probing isolation'
        return (
          <li key={`${e.at}-${i}`} className={`timeline-row ${shown.live ? 'rise' : ''}`} data-state="done">
            <span className="timeline-t data">
              {origin === null ? '' : `${((Date.parse(e.at) - origin) / 1000).toFixed(2)}`}
            </span>
            <span className="timeline-dot" aria-hidden="true" />
            <span className="min-w-0 text-ink">
              {e.stage}
              {probing && sandbox !== null && shown.finished ? <Probes sandbox={sandbox} /> : null}
            </span>
          </li>
        )
      })}
      {waiting ? (
        <li className="timeline-row" data-state="waiting">
          <span className="timeline-t" />
          <span className="timeline-dot" aria-hidden="true" />
          <span className="text-ink-40">{shown.events.length === 0 ? 'waiting for the first event' : 'waiting'}</span>
        </li>
      ) : null}
      {shown.finished && shown.outcome !== null ? (
        <li className="timeline-row" data-state="done">
          <span className="timeline-t" />
          <span className="timeline-dot" aria-hidden="true" />
          <span className="text-ink">graded outside the microVM</span>
        </li>
      ) : null}
      {shown.finished && shown.outcome === null ? (
        <li className="timeline-row" data-state="done">
          <span className="timeline-t" />
          <span className="timeline-dot" aria-hidden="true" />
          <span className="text-unknown">ended without a result</span>
        </li>
      ) : null}
    </ol>
  )
}

function Probes({ sandbox }: { sandbox: SandboxSummary }) {
  return (
    <ul className="m-0 mt-1.5 mb-0.5 grid list-none grid-cols-1 gap-x-3 gap-y-0.5 p-0 text-[0.75rem] sm:grid-cols-2 lg:grid-cols-1">
      {sandbox.isolation.map((p) => (
        <li key={p.name} className="flex items-center gap-1.5" title={p.expectation}>
          {p.held ? <Check /> : <Cross />}
          <span className={p.held ? 'text-ink-60' : 'text-signal'}>{PROBE_LABEL[p.name] ?? p.name}</span>
        </li>
      ))}
    </ul>
  )
}

/* ------------------------------------------------------------ cases --- */

type CellTone = 'pending' | 'correct' | 'wrong' | 'unscored' | 'outside'

const TONE_LABEL: Record<CellTone, string> = {
  pending: 'not run yet',
  correct: 'correct',
  wrong: 'wrong',
  unscored: 'not scored, another protocol',
  outside: 'associated outside its declared protocol',
}

function tone(c: LiveCase | undefined, outside: ReadonlySet<string>): CellTone {
  if (c === undefined) return 'pending'
  if (c.applicability === 'not-applicable') return outside.has(c.case_id) ? 'outside' : 'unscored'
  return c.status === 'correct' ? 'correct' : 'wrong'
}

/**
 * All 64 cases, split the way the suite is: recorded batches and fault
 * injections. The field is the same object before and after a run, so what
 * changes is the result and nothing else.
 */
function CaseField({ catalog, grading }: { catalog: readonly CatalogCase[]; grading: LiveGrading | null }) {
  const byId = useMemo(() => new Map((grading?.cases ?? []).map((c) => [c.case_id, c])), [grading])
  const outside = useMemo(() => new Set(grading?.out_of_protocol_case_ids ?? []), [grading])
  const caught = useMemo(() => new Set(grading === null ? [] : caughtByFault(grading).map((c) => c.case_id)), [grading])
  const [hover, setHover] = useState<{ id: string; x: number; y: number } | null>(null)
  const box = useRef<HTMLDivElement>(null)

  const groups = [
    { title: 'Recorded', note: 'real model responses, replayed', cases: catalog.filter((c) => c.origin === 'recorded-replay') },
    { title: 'Fault-injected', note: 'each built to catch one mistake', cases: catalog.filter((c) => c.origin === 'fault-injection') },
  ]
  const counts = new Map<CellTone, number>()
  for (const c of catalog) {
    const t = tone(byId.get(c.case_id), outside)
    counts.set(t, (counts.get(t) ?? 0) + 1)
  }

  const hovered = hover === null ? undefined : catalog.find((c) => c.case_id === hover.id)
  const hoveredCase = hover === null ? undefined : byId.get(hover.id)
  let index = 0

  return (
    <div
      ref={box}
      className="relative flex flex-col gap-5"
      onPointerLeave={() => setHover(null)}
      onPointerMove={(e) => {
        const target = (e.target as HTMLElement).closest<HTMLElement>('[data-case]')
        const rect = box.current?.getBoundingClientRect()
        if (target === null || rect === undefined) {
          setHover(null)
          return
        }
        const cell = target.getBoundingClientRect()
        setHover({ id: target.dataset.case ?? '', x: cell.left - rect.left + cell.width / 2, y: cell.top - rect.top })
      }}
    >
      <section className="flex flex-col gap-5" aria-label={`All ${catalog.length} cases`}>
        {groups.map((g) => (
          <div key={g.title} className="flex flex-col gap-2">
            <p className="m-0 flex flex-wrap items-baseline gap-x-2 text-[0.8125rem]">
              <span className="font-medium text-ink">
                {g.title} · {g.cases.length}
              </span>
              <span className="text-ink-40">{g.note}</span>
            </p>
            <ol className="case-field m-0 list-none p-0">
              {g.cases.map((c) => {
                const t = tone(byId.get(c.case_id), outside)
                const i = index++
                return (
                  <li
                    key={c.case_id}
                    data-case={c.case_id}
                    data-tone={t}
                    data-caught={caught.has(c.case_id) ? '' : undefined}
                    style={{ transitionDelay: grading === null ? '0ms' : `${i * 7}ms` }}
                    className="case-cell"
                  >
                    <span className="sr-only">
                      {c.case_id}: {TONE_LABEL[t]}
                    </span>
                  </li>
                )
              })}
            </ol>
          </div>
        ))}
      </section>

      <ul className="m-0 flex list-none flex-wrap gap-x-4 gap-y-1.5 p-0 text-[0.75rem] text-ink-40" aria-hidden="true">
        {(Object.keys(TONE_LABEL) as CellTone[])
          .filter((t) => (counts.get(t) ?? 0) > 0)
          .map((t) => (
            <li key={t} className="flex items-center gap-1.5">
              <span className="case-cell !size-2.5" data-legend={t} />
              {TONE_LABEL[t]}
              {grading !== null ? <span className="data text-ink-60">{counts.get(t)}</span> : null}
            </li>
          ))}
      </ul>

      {hover !== null && hovered !== undefined ? (
        <div
          role="tooltip"
          className="pointer-events-none absolute z-10 w-64 -translate-x-1/2 -translate-y-full rounded-md border border-rule bg-sheet p-2.5 text-[0.75rem] shadow-[var(--shadow-2)]"
          style={{ left: Math.min(Math.max(hover.x, 128), (box.current?.clientWidth ?? 256) - 128), top: hover.y - 8 }}
        >
          <p className="data m-0 text-ink">{hovered.case_id}</p>
          <p className="m-0 mt-1 text-ink-60" data-verbatim>
            {hovered.why}
          </p>
          <p className={`m-0 mt-1 ${hoveredCase !== undefined && tone(hoveredCase, outside) === 'wrong' ? 'text-signal' : 'text-ink-40'}`}>
            {hoveredCase === undefined
              ? TONE_LABEL.pending
              : `${TONE_LABEL[tone(hoveredCase, outside)]}${hoveredCase.detail !== '' && hoveredCase.detail !== hoveredCase.why ? `: ${hoveredCase.detail}` : ''}`}
          </p>
        </div>
      ) : null}
    </div>
  )
}

/* ---------------------------------------------------------- verdict --- */

/** What the parser did, in words, for each way a case can go wrong. */
const DID: Record<LiveCase['status'], string> = {
  correct: 'handled it correctly',
  'wrong-association': 'produced an association the evaluator could not accept',
  'should-have-refused': 'produced verdicts where none could be recovered, instead of refusing',
  'should-have-parsed': 'refused a response it should have read',
  crashed: 'crashed',
  timeout: 'ran out of time',
  'missing-record': 'produced no record at all',
  'not-applicable': 'was not scored here',
}

const VERDICT_WORD: Record<string, string> = {
  'accepted-for-review': 'Accepted for review',
  rejected: 'Rejected',
  incomplete: 'Incomplete',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

function Verdict({ phase, shown }: { phase: Phase; shown: Shown | null }) {
  if (shown === null || !shown.finished || shown.outcome === null) {
    const running = phase.kind === 'starting' || (phase.kind === 'watching' && !phase.finished)
    return (
      <div className="flex flex-col gap-2">
        <p className={`m-0 text-[1.375rem] font-semibold tracking-[-0.03em] ${running ? 'text-ink-40' : 'text-ink-40'}`}>
          {running ? 'Waiting' : 'No verdict yet'}
        </p>
        <p className="m-0 text-[0.8125rem] text-ink-60">
          Graded by code the microVM never holds, against criteria hashed before any parser ran.
        </p>
      </div>
    )
  }

  const outcome = shown.outcome
  if (outcome.kind === 'rejected-by-scope') {
    return (
      <div className="flex flex-col gap-2 rise">
        <p className="m-0 text-[1.375rem] font-semibold tracking-[-0.03em] text-signal">Refused by the scope gate</p>
        <p className="m-0 text-[0.8125rem] text-ink-60">{outcome.detail}</p>
      </div>
    )
  }
  if (outcome.kind !== 'graded' && outcome.kind !== 'incomplete') {
    return (
      <p className="m-0 text-[0.8125rem] text-unknown">
        This run is not a candidate run started from this page, so there is no grading to show here.
      </p>
    )
  }

  const grading = outcome.grading ?? null
  const verdict = outcome.verdict ?? (outcome.kind === 'incomplete' ? 'incomplete' : null)
  const caught = grading === null ? [] : caughtByFault(grading)
  const faults = grading?.cases.filter((c) => c.origin === 'fault-injection') ?? []
  const scored = faults.filter((c) => c.applicability === 'scored')
  const unscored = faults.length - scored.length

  return (
    <div className="flex flex-col gap-4 rise" key={`${shown.runId}-${verdict}`}>
      <div>
        <p
          className={`m-0 text-[1.625rem] leading-tight font-semibold tracking-[-0.035em] ${
            verdict === 'accepted-for-review' ? 'text-ink' : verdict === 'rejected' ? 'text-signal' : 'text-unknown'
          }`}
        >
          {verdict === null ? 'No verdict' : (VERDICT_WORD[verdict] ?? verdict)}
        </p>
        <p className="m-0 mt-1 text-[0.8125rem] text-ink-60">{outcome.reason ?? outcome.detail}</p>
      </div>

      {grading !== null && caught.length > 0 ? (
        <section className="flex flex-col gap-2.5">
          <h3 className="m-0 text-[0.8125rem] font-medium text-ink">
            Caught by {caught.length === 1 ? 'a fault-injected case' : `${caught.length} fault-injected cases`}
          </h3>
          <ol className="m-0 flex list-none flex-col gap-3 p-0">
            {caught.slice(0, 2).map((c) => (
              <li key={c.case_id} className="flex flex-col gap-1 rounded-md bg-signal-wash p-3">
                <span className="data break-all text-ink">{c.case_id}</span>
                <span className="text-[0.8125rem] text-ink" data-verbatim>
                  {c.why}
                </span>
                <span className="text-[0.8125rem] text-signal">It {DID[c.status]}.</span>
              </li>
            ))}
          </ol>
          {caught.length > 2 ? <p className="m-0 text-[0.75rem] text-ink-40">And {caught.length - 2} more.</p> : null}
        </section>
      ) : grading !== null ? (
        <section className="flex flex-col gap-1.5">
          <h3 className="m-0 text-[0.8125rem] font-medium text-ink">No fault-injected case caught this parser</h3>
          <p className="m-0 text-[0.8125rem] text-ink-60">
            {scored.length} of the {faults.length} faults apply to the protocol it declared, and it handled every one.
            {unscored > 0
              ? ` The other ${unscored} ${unscored === 1 ? 'is an association rule' : 'are association rules'} of another protocol and ${unscored === 1 ? 'was' : 'were'} not scored. Not scored is not passed.`
              : null}
          </p>
        </section>
      ) : null}

      {grading !== null ? (
        <p className="m-0 text-[0.75rem] text-ink-40">
          Criteria generation {grading.spec_version}, spec <span className="data">{grading.spec_hash}</span>. The parser
          declared <span className="data text-ink-60">{grading.declared_protocol}</span>; that is checked, not believed.
        </p>
      ) : null}

      {shown.live ? null : (
        <Link href="/lab" className="go">
          Every published run
        </Link>
      )}
    </div>
  )
}

/* ----------------------------------------------------------- meters --- */

function ms(value: number | null): string {
  if (value === null) return 'not measured'
  return value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${value} ms`
}

function Meters({ sandbox }: { sandbox: SandboxSummary }) {
  const rows: [string, string][] = [
    ['Region', sandbox.region],
    ['Runtime', sandbox.runtime],
    ['Network', sandbox.network_policy],
    ['Boot', ms(sandbox.boot_ms)],
    ['Harness', ms(sandbox.wall_clock_ms)],
    ['Active CPU', ms(sandbox.active_cpu_ms)],
  ]
  return (
    <dl className="m-0 grid grid-cols-3 gap-x-4 gap-y-2 border-t border-rule bg-paper-secondary px-4 py-3 sm:grid-cols-6 sm:px-5">
      {rows.map(([term, value]) => (
        <div key={term} className="min-w-0">
          <dt className="text-[0.6875rem] text-ink-40">{term}</dt>
          <dd className={`data m-0 truncate !text-[0.75rem] ${value === 'not measured' ? 'text-unknown' : 'text-ink'}`}>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

/* ------------------------------------------------------------- bits --- */

function PaneTitle({ children }: { children: React.ReactNode }) {
  return <h3 className="m-0 mb-3.5 text-[0.8125rem] font-medium text-ink">{children}</h3>
}

function useClock(running: boolean): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => setNow(Date.now()), 100)
    return () => clearInterval(id)
  }, [running])
  return now
}

/** `2026-10-01 23:48 UTC`, identical on the server and in the browser. */
function utc(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : `${d.toISOString().slice(0, 10)} ${d.toISOString().slice(11, 16)} UTC`
}

function FileGlyph() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.2">
      <path d="M3 1.5h4l2.5 2.5v6.5h-6.5z" />
      <path d="M7 1.5v2.5h2.5" />
    </svg>
  )
}

function PlayGlyph() {
  return (
    <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" fill="currentColor">
      <path d="M2.5 1.5v7l6-3.5z" />
    </svg>
  )
}

function Spinner() {
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" className="animate-spin">
      <circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeOpacity="0.3" strokeWidth="1.5" />
      <path d="M6 1.5a4.5 4.5 0 0 1 4.5 4.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function Check() {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" aria-label="held" role="img" className="shrink-0 text-ink">
      <path d="M2.5 6.5l2.2 2.2 4.8-5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Cross() {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" aria-label="failed" role="img" className="shrink-0 text-signal">
      <path d="M3 3l6 6M9 3l-6 6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}
