/**
 * Orchestration, made durable by the platform.
 *
 * `runstate.ts` already models a run as a fold over an append-only event log,
 * and `orchestrate.py` already implements replay-as-recovery. What neither
 * could provide is the part that matters: something outside the process that
 * notices the process died and resumes it. A Python loop that recovers from
 * an interruption only recovers if someone runs it again.
 *
 * The `"use workflow"` directive moves that job to Vercel Workflow. Every
 * `"use step"` boundary below is a journal entry, so a run that is interrupted
 * anywhere resumes from the last entry rather than from the beginning — and,
 * critically, resumes in a *different process*. `PROCESS_ID` is generated once
 * per module instantiation and recorded by every step, so the transcript shows
 * that directly rather than asserting it.
 *
 * What durability does NOT buy, stated because it is the easiest thing here to
 * overclaim: a journaled step that times out may well have completed its
 * external effect. Creating a microVM, calling a model and writing a blob are
 * not undone by the orchestrator forgetting them. So `unknown-outcome`
 * survives the port unchanged — it is the honest status for an attempt that
 * started and whose completion was never journaled, and no amount of platform
 * durability can turn it into a yes or a no.
 */

import { sleep } from 'workflow'

import { evaluate, type Evaluation } from './evaluator'
import { parseRecordBundle, type Case } from './records'
import type { RunEvent } from './runstate'
import { checkPatchScope } from './scope'
import { ALLOWED_PATCH_PATHS } from './spec'

/**
 * Identifies the process instance. Different values across two steps of one
 * run is the evidence that the run outlived a process.
 *
 * Global Web Crypto, not `node:crypto`. The workflow bundle is not Node --
 * the orchestrator body runs in a restricted runtime where a `require` of a
 * Node builtin is a `ReferenceError` at the first step boundary. The SDK
 * warns about exactly this at build time, and it was right.
 */
const PROCESS_ID = `${process.env.VERCEL_DEPLOYMENT_ID ?? 'local'}:${crypto.randomUUID().slice(0, 8)}`

export interface StepMark {
  readonly process_id: string
  readonly at: string
}

function mark(): StepMark {
  return { process_id: PROCESS_ID, at: new Date().toISOString() }
}

export interface WorkflowInput {
  readonly run_id: string
  readonly candidate_id: string
  readonly source: string
  readonly spec_hash: string
  /**
   * Seconds to suspend between execution and grading.
   *
   * Not a delay for its own sake: a `sleep` long enough to exceed the function
   * lifetime is the one way to demonstrate real durability without pretending
   * to crash. The platform tears the process down and brings the run back in
   * another one, which is exactly the failure being claimed survivable. Zero
   * skips it.
   */
  readonly suspend_seconds: number
}

export type WorkflowOutcome =
  | { readonly kind: 'rejected-by-scope'; readonly detail: string; readonly events: readonly RunEvent[] }
  | { readonly kind: 'graded'; readonly verdict: Evaluation['verdict']; readonly reason: string; readonly events: readonly RunEvent[] }
  | { readonly kind: 'incomplete'; readonly detail: string; readonly events: readonly RunEvent[] }

/* --------------------------------------------------------- the steps --- */

/**
 * The scope gate, as a journaled step.
 *
 * First on purpose. A patch that is out of scope must never reach a microVM,
 * so the gate runs before anything is created and its decision is journaled
 * before anything is created — the ordering in the log is the evidence.
 */
export async function scopeStep(input: WorkflowInput): Promise<{
  allowed: boolean
  detail: string
  mark: StepMark
}> {
  'use step'
  const path = ALLOWED_PATCH_PATHS[0] as string
  const result = checkPatchScope([{ path, content: input.source }])
  return {
    allowed: result.allowed,
    detail: result.allowed ? `${path} — within the allowed patch scope` : `${result.rejection}: ${result.detail}`,
    mark: mark(),
  }
}

/**
 * Execute the candidate in an isolated microVM.
 *
 * Imported inside the step rather than at module scope so the sandbox client
 * is not pulled into every build that merely references this workflow.
 */
export async function executeStep(input: WorkflowInput): Promise<{
  ok: boolean
  detail: string
  sandbox_id: string | null
  records_json: string | null
  mark: StepMark
}> {
  'use step'
  const { runInSandbox, sandboxCredentials } = await import('./sandbox')
  const { uploadSet } = await import('./upload-set')

  const credentials = sandboxCredentials()
  if ('missing' in credentials) {
    // Not a fallback to local execution. An unknown candidate running outside
    // the sandbox is the single outcome `selectRunner` exists to prevent, so
    // the correct result is an incomplete run.
    return {
      ok: false,
      detail: `the sandbox cannot run: missing ${credentials.missing.join(', ')}`,
      sandbox_id: null,
      records_json: null,
      mark: mark(),
    }
  }

  const execution = await runInSandbox({
    candidateSource: input.source,
    files: await uploadSet(),
    credentials,
  })
  const failed = execution.isolation.filter((p) => !p.held)
  if (failed.length > 0) {
    // A microVM that did not actually isolate produces evidence about nothing.
    return {
      ok: false,
      detail: `isolation probes failed: ${failed.map((p) => p.name).join(', ')}`,
      sandbox_id: execution.sandbox_id,
      records_json: null,
      mark: mark(),
    }
  }
  return {
    ok: execution.exit_code === 0 && execution.records_json !== null,
    detail:
      execution.exit_code === 0
        ? `sandbox ${execution.sandbox_id} in ${execution.region}, ${execution.egress_bytes ?? '?'} bytes egress`
        : `the harness exited ${execution.exit_code}`,
    sandbox_id: execution.sandbox_id,
    records_json: execution.records_json,
    mark: mark(),
  }
}

/**
 * Grade the records with the trusted evaluator.
 *
 * A separate step from execution, and the separation is the point: grading
 * reads only the bundle the previous step journaled. It cannot reach the
 * microVM, and the microVM never held this code.
 */
export async function gradeStep(
  recordsJson: string | null,
  failure: string | null,
  cases: readonly Case[],
): Promise<{ verdict: Evaluation['verdict']; reason: string; mark: StepMark }> {
  'use step'
  if (recordsJson === null) {
    const result = evaluate(cases as Case[], null, { failure: failure ?? 'no records were produced' })
    return { verdict: result.verdict, reason: result.reason, mark: mark() }
  }
  const parsed = parseRecordBundle(JSON.parse(recordsJson))
  const result = parsed.ok
    ? evaluate(cases as Case[], parsed.value)
    : evaluate(cases as Case[], null, { failure: `record bundle did not validate: ${parsed.issues.join('; ')}` })
  return { verdict: result.verdict, reason: result.reason, mark: mark() }
}

/* ------------------------------------------------------ the workflow --- */

/**
 * One candidate, from scope gate to verdict, durably.
 *
 * The event log this returns is the same shape `runstate.ts` folds, so the
 * public view of a workflow-driven run and of a Python-driven one are the
 * same view. Replacing the orchestrator did not replace the evidence format,
 * which is what makes the two comparable.
 */
export async function runCandidateWorkflow(
  input: WorkflowInput,
  cases: readonly Case[],
): Promise<WorkflowOutcome> {
  'use workflow'

  const events: RunEvent[] = []
  const attemptId = `${input.run_id}#01`

  const scope = await scopeStep(input)
  events.push({
    type: 'created',
    run_id: input.run_id,
    candidate_id: input.candidate_id,
    at: scope.mark.at,
    spec_hash: input.spec_hash,
  })
  events.push({ type: 'scope-checked', at: scope.mark.at, allowed: scope.allowed, detail: scope.detail })
  if (!scope.allowed) {
    return { kind: 'rejected-by-scope', detail: scope.detail, events }
  }

  events.push({ type: 'attempt-started', attempt_id: attemptId, runner: 'vercel-sandbox', at: mark().at })
  const execution = await executeStep(input)
  events.push({
    type: 'attempt-ended',
    attempt_id: attemptId,
    at: execution.mark.at,
    // `failed`, not `unknown-outcome`: this step returned, so its outcome is
    // known. `unknown-outcome` is reserved for an attempt whose completion was
    // never journaled at all, which is reconstructed on replay rather than
    // written here — see `recoverAttempts`.
    status: execution.ok ? 'succeeded' : 'failed',
    note: execution.detail,
  })

  if (input.suspend_seconds > 0) {
    // A real suspension, and the SDK's rather than a `setTimeout`. The
    // difference is the whole claim: `setTimeout` holds a process open for
    // the duration, which demonstrates nothing. This releases it. The process
    // that resumes is not the process that slept, and `PROCESS_ID` on the
    // next step is where a reader can see that rather than take it.
    await sleep(`${input.suspend_seconds}s`)
  }

  const graded = await gradeStep(execution.records_json, execution.ok ? null : execution.detail, cases)
  events.push({ type: 'evaluated', at: graded.mark.at, verdict: graded.verdict, reason: graded.reason })

  if (graded.verdict === 'incomplete' || graded.verdict === 'failed') {
    return { kind: 'incomplete', detail: graded.reason, events }
  }
  return { kind: 'graded', verdict: graded.verdict, reason: graded.reason, events }
}

/**
 * Reconstruct attempt statuses from a log that may be missing endings.
 *
 * This is the whole reason `unknown-outcome` exists, and it is deliberately
 * *not* something the workflow writes. An attempt with a start and no end is
 * one nothing observed finishing: the microVM may have run the candidate to
 * completion a millisecond before the orchestrator died. Calling that
 * `failed` would be a claim nobody is in a position to make.
 */
export function recoverAttempts(events: readonly RunEvent[]): readonly {
  attempt_id: string
  status: 'succeeded' | 'failed' | 'cancelled' | 'unknown-outcome'
  note: string
}[] {
  const started = events.filter((e) => e.type === 'attempt-started')
  return started.map((start) => {
    const end = events.find(
      (e) => e.type === 'attempt-ended' && e.attempt_id === start.attempt_id,
    )
    if (end === undefined || end.type !== 'attempt-ended') {
      return {
        attempt_id: start.attempt_id,
        status: 'unknown-outcome' as const,
        note: 'no completion was journaled for this attempt; whether the work finished is not knowable from the log',
      }
    }
    return { attempt_id: start.attempt_id, status: end.status, note: end.note }
  })
}
