/**
 * Vercel Workflow journals each step for recovery. Steps load the staged case suite
 * locally to avoid copying it into every workflow journal. An unjournaled completion
 * remains unknown because its external effects may have finished.
 */

import { getWritable, sleep } from 'workflow'

import { evaluate, type Evaluation } from './evaluator'
import { PROGRESS_NAMESPACE, summariseGrading, summariseSandbox, type LiveGrading, type ProgressEvent, type SandboxSummary } from './live'
import { parseRecordBundle } from './records'
import type { RunEvent } from './runstate'
import { checkPatchScope } from './scope'
import { ALLOWED_PATCH_PATHS } from './spec'

/**
 * Use global Web Crypto: the workflow runtime cannot import Node builtins.
 * A module instance ID and per-step uptime identify process reuse across resumes.
 */
const PROCESS_ID = `${process.env.VERCEL_DEPLOYMENT_ID ?? 'local'}:${crypto.randomUUID().slice(0, 8)}`

export interface StepMark {
  readonly process_id: string
  readonly at: string
  /** Process uptime helps distinguish a warm resume from a new instance. */
  readonly uptime_s: number
}

function mark(): StepMark {
  return {
    process_id: PROCESS_ID,
    at: new Date().toISOString(),
    uptime_s: Math.round(process.uptime() * 10) / 10,
  }
}

export interface WorkflowInput {
  readonly run_id: string
  readonly candidate_id: string
  readonly source: string
  readonly spec_hash: string
  /** Optional durable suspension between execution and grading; zero skips it. */
  readonly suspend_seconds: number
  /** Admission slot and UTC billing day, returned to releaseStep when the run ends. */
  readonly slot: string
  readonly day: string
}

export interface ProcessTrace {
  readonly step: 'scope' | 'execute' | 'grade'
  readonly process_id: string
  readonly at: string
  readonly uptime_s: number
}

interface Base {
  readonly events: readonly RunEvent[]
  readonly processes: readonly ProcessTrace[]
  /** True when step IDs show multiple process instances. A suspension may resume on a warm instance. */
  readonly resumed: boolean
}

/**
 * Grading contains per-case results; sandbox contains platform measurements.
 * Either may be null if execution stopped before producing it.
 */
export type WorkflowOutcome =
  | ({ readonly kind: 'rejected-by-scope'; readonly detail: string } & Base)
  | ({
      readonly kind: 'graded'
      readonly verdict: Evaluation['verdict']
      readonly reason: string
      readonly grading: LiveGrading
      readonly sandbox: SandboxSummary | null
    } & Base)
  | ({
      readonly kind: 'incomplete'
      readonly detail: string
      readonly grading: LiveGrading | null
      readonly sandbox: SandboxSummary | null
    } & Base)

/** Progress writes are best-effort so a stream failure cannot fail the run. */
function progressWriter(): { say: (stage: string) => void; done: () => Promise<void> } {
  let writer: WritableStreamDefaultWriter<ProgressEvent> | null = null
  try {
    writer = getWritable<ProgressEvent>({ namespace: PROGRESS_NAMESPACE }).getWriter()
  } catch {
    writer = null
  }
  const pending: Promise<unknown>[] = []
  return {
    say(stage) {
      if (writer !== null) pending.push(writer.write({ at: new Date().toISOString(), stage }).catch(() => undefined))
    },
    async done() {
      await Promise.all(pending)
      writer?.releaseLock()
    },
  }
}

/** Journal the scope decision before allocating a microVM. */
export async function scopeStep(input: WorkflowInput): Promise<{
  allowed: boolean
  detail: string
  mark: StepMark
}> {
  'use step'
  const path = ALLOWED_PATCH_PATHS[0] as string
  const result = checkPatchScope([{ path, content: input.source }])
  const detail = result.allowed ? `${path} is within the allowed patch scope` : `${result.rejection}: ${result.detail}`
  const progress = progressWriter()
  progress.say(result.allowed ? 'scope checked: only candidate.py is written' : `refused by the scope gate: ${detail}`)
  await progress.done()
  return { allowed: result.allowed, detail, mark: mark() }
}

/** Import the sandbox client inside the step to keep it out of the workflow bundle. */
export async function executeStep(input: WorkflowInput): Promise<{
  ok: boolean
  detail: string
  sandbox_id: string | null
  records_json: string | null
  sandbox: SandboxSummary | null
  /**
   * Metered CPU, zero if no microVM was created, or null for an unmetered attempt.
   * releaseStep charges null at the configured maximum.
   */
  charge_cpu_ms: number | null
  mark: StepMark
}> {
  'use step'
  const { runInSandbox, sandboxCredentials } = await import('./sandbox')
  const { uploadSet } = await import('./upload-set')

  const credentials = sandboxCredentials()
  if ('missing' in credentials) {

    return {
      ok: false,
      detail: `the sandbox cannot run: missing ${credentials.missing.join(', ')}`,
      sandbox_id: null,
      records_json: null,
      sandbox: null,
      charge_cpu_ms: 0,
      mark: mark(),
    }
  }

  const progress = progressWriter()
  let execution: Awaited<ReturnType<typeof runInSandbox>>
  try {
    execution = await runInSandbox({
      candidateSource: input.source,
      files: await uploadSet(),
      credentials,
      onProgress: progress.say,
      // The admission slot tag lets operators count microVMs per run.
      tags: { lab: 'public-run', slot: input.slot },
    })
  } catch (error) {
    // Return failures so Workflow cannot retry a billable sandbox execution.
    progress.say('the sandbox run failed')
    await progress.done()
    return {
      ok: false,
      detail: `the sandbox run failed: ${error instanceof Error ? error.message.split('\n')[0] : String(error)}`,
      sandbox_id: null,
      records_json: null,
      sandbox: null,
      charge_cpu_ms: null,
      mark: mark(),
    }
  }
  progress.say('microVM stopped')
  await progress.done()

  const sandbox = summariseSandbox(execution)
  const failed = execution.isolation.filter((p) => !p.held)
  if (failed.length > 0) {

    return {
      ok: false,
      detail: `isolation probes failed: ${failed.map((p) => p.name).join(', ')}`,
      sandbox_id: execution.sandbox_id,
      records_json: null,
      sandbox,
      charge_cpu_ms: execution.active_cpu_ms,
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
    sandbox,
    charge_cpu_ms: execution.active_cpu_ms,
    mark: mark(),
  }
}
// Disable retries after unhandled failures, including process termination.
executeStep.maxRetries = 0

/** Grade the journaled record bundle after execution, outside the microVM. */
export async function gradeStep(
  recordsJson: string | null,
  failure: string | null,
): Promise<{ verdict: Evaluation['verdict']; reason: string; grading: LiveGrading; mark: StepMark }> {
  'use step'
  const { loadCasesForRun } = await import('./case-loader')
  const cases = await loadCasesForRun()

  // Execution failure takes precedence even when records were produced.
  const graded = (result: Evaluation) => ({
    verdict: result.verdict,
    reason: result.reason,
    grading: summariseGrading(result, cases),
    mark: mark(),
  })
  if (failure !== null) return graded(evaluate(cases, null, { failure }))
  if (recordsJson === null) return graded(evaluate(cases, null, { failure: 'no records were produced' }))
  const parsed = parseRecordBundle(JSON.parse(recordsJson))
  return graded(
    parsed.ok
      ? evaluate(cases, parsed.value)
      : evaluate(cases, null, { failure: `record bundle did not validate: ${parsed.issues.join('; ')}` }),
  )
}

/**
 * Cleanup errors must preserve the verdict. If the store is unavailable, the slot
 * expires by lease and this run's CPU charge is lost.
 */
export async function releaseStep(slot: string, day: string, cpuMs: number | null): Promise<{ released: boolean }> {
  'use step'
  const { releaseRun, upstashStore } = await import('./public-limits')
  const store = upstashStore()
  if (store === null) return { released: false }
  try {
    await releaseRun(store, { slot, day, cpu_ms: cpuMs })
    return { released: true }
  } catch {
    return { released: false }
  }
}

/** Returns the event format shared with the Python orchestrator and runstate.ts. */
export async function runCandidateWorkflow(input: WorkflowInput): Promise<WorkflowOutcome> {
  'use workflow'

  // Charge starts at zero until a microVM may have run.
  let chargeCpuMs: number | null = 0
  try {
    const events: RunEvent[] = []
    const processes: ProcessTrace[] = []
    const attemptId = `${input.run_id}#01`
    const summarise = (): { processes: ProcessTrace[]; resumed: boolean } => ({
      processes,
      resumed: new Set(processes.map((p) => p.process_id)).size > 1,
    })

    const scope = await scopeStep(input)
    processes.push({ step: 'scope', ...scope.mark })
    events.push({
      type: 'created',
      run_id: input.run_id,
      candidate_id: input.candidate_id,
      at: scope.mark.at,
      spec_hash: input.spec_hash,
    })
    events.push({ type: 'scope-checked', at: scope.mark.at, allowed: scope.allowed, detail: scope.detail })
    if (!scope.allowed) {
      return { kind: 'rejected-by-scope', detail: scope.detail, events, ...summarise() }
    }

    // The workflow runtime provides replay-stable Date but lacks process.uptime.
    events.push({ type: 'attempt-started', attempt_id: attemptId, runner: 'vercel-sandbox', at: new Date().toISOString() })
    chargeCpuMs = null
    const execution = await executeStep(input)
    chargeCpuMs = execution.charge_cpu_ms
    processes.push({ step: 'execute', ...execution.mark })
    events.push({
      type: 'attempt-ended',
      attempt_id: attemptId,
      at: execution.mark.at,
      // A returned step has a known outcome. recoverAttempts handles missing completions.
      status: execution.ok ? 'succeeded' : 'failed',
      note: execution.detail,
    })

    if (input.suspend_seconds > 0) {
      // Durable sleep releases the worker while suspended.
      await sleep(`${input.suspend_seconds}s`)
    }

    const graded = await gradeStep(execution.records_json, execution.ok ? null : execution.detail)
    processes.push({ step: 'grade', ...graded.mark })
    events.push({ type: 'evaluated', at: graded.mark.at, verdict: graded.verdict, reason: graded.reason })

    if (graded.verdict === 'incomplete' || graded.verdict === 'failed') {
      return {
        kind: 'incomplete',
        detail: graded.reason,
        grading: graded.grading,
        sandbox: execution.sandbox,
        events,
        ...summarise(),
      }
    }
    return {
      kind: 'graded',
      verdict: graded.verdict,
      reason: graded.reason,
      grading: graded.grading,
      sandbox: execution.sandbox,
      events,
      ...summarise(),
    }
  } finally {
    await releaseStep(input.slot, input.day, chargeCpuMs)
  }
}

/** A start without a journaled completion remains unknown: external work may have finished. */
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

/**
 * Owner-triggered investigations run on the deployment where AI_GATEWAY_API_KEY
 * is available. Proposed candidates use the same scope gate, sandbox, and external grader.
 */
export interface InvestigationWorkflowInput {
  readonly run_id: string
  readonly candidate_id: string
  readonly spec_hash: string
  readonly suspend_seconds: number
}

export type InvestigationWorkflowOutcome = {
  readonly kind: 'investigated' | 'refused'
  readonly detail: string
  /** The sanitised trace, null when the investigation never started. */
  readonly trace: unknown | null
  /** Sandbox evidence for the candidate the agent proposed. */
  readonly sandbox: unknown | null
  /** The record bundle the harness produced, as bytes. */
  readonly records_json: string | null
  readonly candidate_source: string | null
  readonly verdict: Evaluation['verdict'] | null
  readonly verdict_reason: string | null
  readonly processes: readonly ProcessTrace[]
  readonly resumed: boolean
  /** Revision supplied by the deployment that executed the code. */
  readonly executed_at_revision: string
  readonly deployment: string
}

/** Keep model proposals and their tool executions in one journaled step. */
export async function investigateStep(input: InvestigationWorkflowInput): Promise<{
  ok: boolean
  detail: string
  trace: unknown | null
  sandbox: unknown | null
  records_json: string | null
  candidate_source: string | null
  mark: StepMark
}> {
  'use step'
  const { investigate } = await import('./agent')
  const { runInSandbox, sandboxCredentials } = await import('./sandbox')
  const { uploadSet } = await import('./upload-set')
  const { parseRecordBundle } = await import('./records')
  const { readSourceExcerpt } = await import('./source-excerpt')
  const { loadCasesForRun } = await import('./case-loader')
  const cases = await loadCasesForRun()

  let sandbox: unknown | null = null
  let recordsJson: string | null = null
  let candidateSource: string | null = null
  /** Set when a probe did not hold. Propagated so the run cannot be graded. */
  let isolationFailure: string | null = null

  const result = await investigate({
    cases,
    readSource: readSourceExcerpt,
    evaluateCandidate: async (_candidateId, source) => {
      candidateSource = source
      const credentials = sandboxCredentials()
      if ('missing' in credentials) {
        return { summary: `the sandbox is unavailable: missing ${credentials.missing.join(', ')}`, evaluation: null }
      }
      const execution = await runInSandbox({
        candidateSource: source,
        files: await uploadSet(),
        credentials,
      })
      const { stdout, stderr, records_json: records, candidate_sha256, ...evidence } = execution
      void stdout
      void stderr
      void candidate_sha256
      sandbox = evidence

      // Check isolation before retaining records in the closure used by the grading step.
      const breached = execution.isolation.filter((probe) => !probe.held)
      if (breached.length > 0) {
        recordsJson = null
        isolationFailure = `isolation probes failed: ${breached.map((p) => p.name).join(', ')}`
        return { summary: 'the sandbox did not isolate; this run produces evidence about nothing', evaluation: null }
      }
      if (records === null) {
        return { summary: `the harness exited ${execution.exit_code} and produced no records`, evaluation: null }
      }
      recordsJson = records
      const parsed = parseRecordBundle(JSON.parse(records))
      if (!parsed.ok) return { summary: `the record bundle did not validate: ${parsed.issues.join('; ')}`, evaluation: null }

      // Return outcome counts only, keeping grader feedback out of the proposal loop.
      const tally = parsed.value.records.reduce<Record<string, number>>((acc, r) => {
        acc[r.outcome] = (acc[r.outcome] ?? 0) + 1
        return acc
      }, {})
      return {
        summary: `${parsed.value.records.length} records: ${Object.entries(tally).map(([k, v]) => `${v} ${k}`).join(', ')}.`,
        evaluation: null,
      }
    },
  })

  if (!result.ok) {
    return {
      ok: false,
      detail: `${result.reason}: ${result.needs.join('; ')}`,
      // Preserve traces from failed calls because earlier tool calls may have incurred cost.
      trace: result.reason === 'call-failed' ? result.trace : null,
      sandbox,
      records_json: recordsJson,
      candidate_source: candidateSource,
      mark: mark(),
    }
  }
  if (isolationFailure !== null) {
    return {
      ok: false,
      detail: isolationFailure,
      trace: result.trace,
      sandbox,
      records_json: null,
      candidate_source: candidateSource,
      mark: mark(),
    }
  }
  return {
    ok: true,
    detail: `${result.trace.tool_calls_made} tool calls, finish ${result.trace.finish_reason}`,
    trace: result.trace,
    sandbox,
    records_json: recordsJson,
    candidate_source: candidateSource,
    mark: mark(),
  }
}

export async function investigationWorkflow(
  input: InvestigationWorkflowInput,
): Promise<InvestigationWorkflowOutcome> {
  'use workflow'

  const processes: ProcessTrace[] = []
  const investigation = await investigateStep(input)
  processes.push({ step: 'execute', ...investigation.mark })

  if (input.suspend_seconds > 0) {

    await sleep(`${input.suspend_seconds}s`)
  }

  const graded = await gradeStep(investigation.records_json, investigation.ok ? null : investigation.detail)
  processes.push({ step: 'grade', ...graded.mark })

  return {
    kind: investigation.ok ? 'investigated' : 'refused',
    detail: investigation.detail,
    trace: investigation.trace,
    sandbox: investigation.sandbox,
    records_json: investigation.records_json,
    candidate_source: investigation.candidate_source,
    verdict: investigation.records_json === null ? null : graded.verdict,
    verdict_reason: investigation.records_json === null ? null : graded.reason,
    processes,
    resumed: new Set(processes.map((p) => p.process_id)).size > 1,
    executed_at_revision: await revisionStep(),
    deployment: process.env.VERCEL_URL ?? 'local',
  }
}

/** Read deployment environment inside a Node step. */
async function revisionStep(): Promise<string> {
  'use step'
  return process.env.VERCEL_GIT_COMMIT_SHA ?? 'unknown'
}
