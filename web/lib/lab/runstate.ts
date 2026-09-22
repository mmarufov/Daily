/**
 * Durable run state, as an event log.
 *
 * Workflow durability makes *orchestration* recoverable. It does not make a
 * model call, a sandbox creation or a blob write happen exactly once — those
 * are external effects, and a step that times out may well have succeeded.
 * So the log records what was *attempted* as faithfully as what succeeded, and
 * `unknown-outcome` is a first-class attempt status rather than a failure.
 *
 * Three properties hold by construction, and `tests/unit/lab-runstate.test.ts`
 * asserts each:
 *
 *  1. **Replay is total.** State is a fold over the events; recovering after an
 *     interruption means reading the log and folding again. There is no state
 *     in process memory that the log does not contain.
 *  2. **Publication is idempotent.** The first `published` event for a run id
 *     wins; later ones are recorded as duplicates and cannot change the
 *     result. At-least-once delivery therefore cannot create two finals.
 *  3. **Cancellation is terminal.** Once cancelled, no event can move the run
 *     to a verdict — including a `finished` event from work already in flight
 *     when the cancel landed.
 */

import type { Verdict } from './evaluator'

export type RunPhase =
  | 'preparing'
  | 'running'
  | 'evaluating'
  | 'accepted-for-review'
  | 'rejected'
  | 'incomplete'
  | 'failed'
  | 'cancelled'

export type AttemptStatus = 'started' | 'succeeded' | 'failed' | 'cancelled' | 'unknown-outcome'

export interface Attempt {
  readonly attempt_id: string
  readonly runner: 'local-known' | 'vercel-sandbox'
  readonly started_at: string
  readonly ended_at: string | null
  readonly status: AttemptStatus
  readonly note: string
}

export type RunEvent =
  | { type: 'created'; run_id: string; candidate_id: string; at: string; spec_hash: string }
  | { type: 'scope-checked'; at: string; allowed: boolean; detail: string }
  | { type: 'attempt-started'; attempt_id: string; runner: Attempt['runner']; at: string }
  | { type: 'attempt-ended'; attempt_id: string; at: string; status: Exclude<AttemptStatus, 'started'>; note: string }
  | { type: 'records-received'; attempt_id: string; at: string; n_records: number }
  | { type: 'evaluated'; at: string; verdict: Verdict; reason: string }
  | { type: 'published'; at: string; artifact_sha256: string }
  | { type: 'cancelled'; at: string; by: string }
  | { type: 'failed'; at: string; error: string }

export interface RunState {
  readonly run_id: string | null
  readonly candidate_id: string | null
  readonly spec_hash: string | null
  readonly phase: RunPhase
  readonly attempts: readonly Attempt[]
  readonly verdict: Verdict | null
  readonly verdict_reason: string | null
  /** sha256 of the artifact as first published. Never overwritten. */
  readonly published_sha256: string | null
  /** Publication deliveries beyond the first, recorded rather than hidden. */
  readonly duplicate_publications: number
  readonly cancelled_by: string | null
  readonly error: string | null
  /** Events that arrived after a terminal state, kept for the timeline. */
  readonly ignored_after_terminal: number
}

export const INITIAL: RunState = {
  run_id: null,
  candidate_id: null,
  spec_hash: null,
  phase: 'preparing',
  attempts: [],
  verdict: null,
  verdict_reason: null,
  published_sha256: null,
  duplicate_publications: 0,
  cancelled_by: null,
  error: null,
  ignored_after_terminal: 0,
}

const TERMINAL: readonly RunPhase[] = [
  'accepted-for-review',
  'rejected',
  'incomplete',
  'failed',
  'cancelled',
]

export function isTerminal(phase: RunPhase): boolean {
  return TERMINAL.includes(phase)
}

/** True when a run may still start new work. */
export function acceptsNewWork(state: RunState): boolean {
  return !isTerminal(state.phase)
}

function withAttempt(
  attempts: readonly Attempt[],
  attemptId: string,
  patch: Partial<Attempt>,
): readonly Attempt[] {
  return attempts.map((a) => (a.attempt_id === attemptId ? { ...a, ...patch } : a))
}

export function reduce(state: RunState, event: RunEvent): RunState {
  // Cancellation and publication are the two places where "already decided"
  // has to beat "just arrived", because both can race with work in flight.
  if (isTerminal(state.phase)) {
    if (event.type === 'published') {
      if (state.published_sha256 === null) {
        return { ...state, published_sha256: event.artifact_sha256 }
      }
      // At-least-once delivery. The first artifact stands; a second delivery
      // is counted so the timeline can say it happened, and discarded so it
      // cannot produce a conflicting final.
      return { ...state, duplicate_publications: state.duplicate_publications + 1 }
    }
    if (event.type === 'attempt-ended') {
      // Work that was already running when the run ended still reports. Record
      // the attempt honestly; do not resurrect the run.
      return {
        ...state,
        attempts: withAttempt(state.attempts, event.attempt_id, {
          status: state.phase === 'cancelled' ? 'cancelled' : event.status,
          ended_at: event.at,
          note: event.note,
        }),
        ignored_after_terminal: state.ignored_after_terminal + 1,
      }
    }
    return { ...state, ignored_after_terminal: state.ignored_after_terminal + 1 }
  }

  switch (event.type) {
    case 'created':
      return {
        ...state,
        run_id: event.run_id,
        candidate_id: event.candidate_id,
        spec_hash: event.spec_hash,
        phase: 'preparing',
      }

    case 'scope-checked':
      return event.allowed
        ? state
        : { ...state, phase: 'rejected', verdict: 'rejected', verdict_reason: event.detail }

    case 'attempt-started':
      return {
        ...state,
        phase: 'running',
        attempts: [
          ...state.attempts,
          {
            attempt_id: event.attempt_id,
            runner: event.runner,
            started_at: event.at,
            ended_at: null,
            status: 'started',
            note: '',
          },
        ],
      }

    case 'attempt-ended':
      return {
        ...state,
        attempts: withAttempt(state.attempts, event.attempt_id, {
          status: event.status,
          ended_at: event.at,
          note: event.note,
        }),
      }

    case 'records-received':
      return { ...state, phase: 'evaluating' }

    case 'evaluated':
      return {
        ...state,
        phase: event.verdict,
        verdict: event.verdict,
        verdict_reason: event.reason,
      }

    case 'published':
      return state.published_sha256 === null
        ? { ...state, published_sha256: event.artifact_sha256 }
        : { ...state, duplicate_publications: state.duplicate_publications + 1 }

    case 'cancelled':
      return {
        ...state,
        phase: 'cancelled',
        verdict: 'cancelled',
        verdict_reason: `cancelled by ${event.by}`,
        cancelled_by: event.by,
        // Anything still running is marked cancelled rather than left 'started'
        // forever; whether it had already finished remotely is unknowable from
        // here, which is what `unknown-outcome` exists for elsewhere.
        attempts: state.attempts.map((a) =>
          a.status === 'started' ? { ...a, status: 'cancelled' as const, ended_at: event.at } : a,
        ),
      }

    case 'failed':
      return { ...state, phase: 'failed', verdict: 'failed', verdict_reason: event.error, error: event.error }
  }
}

/** Fold an event log into state. This is the whole of recovery. */
export function replay(events: readonly RunEvent[], from: RunState = INITIAL): RunState {
  return events.reduce(reduce, from)
}

/**
 * Deterministic ids.
 *
 * A run id is a function of what identifies the run, not of when it was
 * created, so a retry of the same work reconciles with the existing run
 * instead of forking a second one.
 */
export function runId(experimentId: string, candidateId: string, sourceSha256: string, specHash: string): string {
  return `${experimentId}__${candidateId}__${sourceSha256.slice(0, 12)}__${specHash.slice(0, 8)}`
}

export function attemptId(run: string, ordinal: number): string {
  return `${run}#${String(ordinal).padStart(2, '0')}`
}
