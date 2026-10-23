/**
 * Verifiers over the trajectory, not the output.
 *
 * The evaluator grades a candidate's prediction records, which are the
 * *output* of an investigation. How the agent got there -- the ordered tool
 * calls, their arguments, the usage each model call reported -- is recorded
 * in the trace and, until generation 3, was graded by nothing. These are four
 * deterministic predicates over that recording:
 *
 *   read-before-propose   a source read returned before the first proposal
 *   inside-scope-gate     every path the agent named was inside the gate
 *   inside-budget         executed usage stayed inside the budget it was given
 *   proposed-once         exactly one proposal reached the tool
 *
 * Deliberately modest. Each is a question about the recording with one
 * answer, computable offline from committed bytes, with no model in the loop
 * and no judgement about whether the investigation was *good*.
 *
 * Two sources of truth in a trace, and the difference matters to every
 * predicate below:
 *
 *   `steps`        what the tools executed, in execution order. A call the
 *                  SDK refused on schema, or the budget refused, never
 *                  reaches `record`, so it is absent here.
 *   `model_steps`  what the model *asked for*, per model call, including
 *                  refused calls (`invalid: true`) and calls the tool budget
 *                  turned away.
 *
 * One rule for all four: a predicate fires on what *ran*. A request the
 * harness turned away before it took effect -- refused by a tool's schema, by
 * the tool budget, or by the one-proposal cap -- is not a violation of what
 * ran; it is counted in `observations`, separately, so the prevention is
 * visible rather than mistaken for good behaviour. Where that rule leaves a
 * predicate structurally unable to fire, the predicate says so.
 *
 * The model never sees this file: it is not on the read allowlist, and
 * nothing it computes is returned to the loop.
 */

import { z } from 'zod'

import { checkPatchScope } from './scope'
import { ReadSourceInput } from './investigator'

/* ------------------------------------------------------ the recording ---- */

const StepSchema = z.object({
  index: z.number().int(),
  kind: z.enum(['model-text', 'tool-call', 'tool-result']),
  name: z.string().nullable(),
  payload: z.string(),
  at_ms: z.number(),
})

const ModelStepSchema = z.object({
  index: z.number().int(),
  finish_reason: z.string(),
  input_tokens: z.number().int().nullable(),
  output_tokens: z.number().int().nullable(),
  cost_usd: z.number().nullable(),
  generation_id: z.string().nullable(),
  tool_calls: z.array(
    z.object({ name: z.string(), input: z.string(), invalid: z.boolean(), error: z.string().nullable() }),
  ),
})

/** The fields of an `InvestigationTrace` the predicates read. Extra keys pass through. */
export const RecordedTraceSchema = z.object({
  wall_clock_ms: z.number(),
  steps: z.array(StepSchema),
  budget: z.object({
    max_proposals: z.number().int(),
    max_tool_calls: z.number().int(),
    max_model_calls: z.number().int(),
    max_output_tokens: z.number().int(),
    max_total_tokens: z.number().int(),
    max_tool_result_chars: z.number().int(),
    max_usd: z.number(),
    wall_clock_seconds: z.number(),
  }),
  budget_ceiling_usd: z.number(),
  tokens_used: z.number(),
  tool_calls_made: z.number().int(),
  model_calls_made: z.number().int(),
  model_steps: z.array(ModelStepSchema),
  cost_usd: z.number().nullable(),
  proposal: z
    .object({ path: z.string(), content: z.string(), scope_accepted: z.boolean() })
    .nullable(),
})
export type RecordedTrace = z.infer<typeof RecordedTraceSchema>

/* ---------------------------------------------------------- results ---- */

export type PredicateId = 'read-before-propose' | 'inside-scope-gate' | 'inside-budget' | 'proposed-once'

export interface PredicateResult {
  readonly id: PredicateId
  /** `fail` is a firing: the trace shows the violation. */
  readonly status: 'pass' | 'fail' | 'not-applicable'
  readonly detail: string
  /** Step references (`steps[i]`, `model_steps[i]`), so the claim is checkable. */
  readonly evidence: readonly string[]
  /**
   * Things worth reporting that the predicate does not grade -- chiefly
   * attempts the tooling refused, which by construction cannot be violations
   * of what was *executed*.
   */
  readonly observations: readonly string[]
}

export const PREDICATE_QUESTIONS: Readonly<Record<PredicateId, string>> = {
  'read-before-propose':
    'Did a source excerpt come back to the agent, in an earlier model call, before it first tried to propose?',
  'inside-scope-gate':
    'Was every path the agent named, in every call it attempted, inside the boundary for that operation?',
  'inside-budget': 'Did executed usage stay inside every recorded dimension of the budget the run was given?',
  'proposed-once': 'Did exactly one proposal reach the propose_patch tool?',
}

/* ---------------------------------------------------------- helpers ---- */

interface Attempt {
  readonly model_step: number
  readonly name: string
  readonly input: Record<string, unknown> | null
  readonly invalid: boolean
}

/** Every call the model asked for, in order. Inputs are parsed where they parse. */
function attempts(trace: RecordedTrace): Attempt[] {
  return trace.model_steps.flatMap((m) =>
    m.tool_calls.map((c) => {
      let input: Record<string, unknown> | null = null
      try {
        const parsed: unknown = JSON.parse(c.input)
        if (parsed !== null && typeof parsed === 'object') input = parsed as Record<string, unknown>
      } catch {
        // A truncated payload does not parse; the attempt still counts, and
        // the path -- always the first field the tools serialise -- is
        // recovered from the prefix, which truncation never reaches.
        const path = /"path":"((?:[^"\\]|\\.)*)"/.exec(c.input)?.[1]
        if (path !== undefined) input = { path: JSON.parse(`"${path}"`) as string }
      }
      return { model_step: m.index, name: c.name, input, invalid: c.invalid }
    }),
  )
}

const executedCalls = (trace: RecordedTrace, name?: string) =>
  trace.steps.filter((s) => s.kind === 'tool-call' && (name === undefined || s.name === name))

/** Did the tool result immediately following this call report an error? */
function resultIsError(trace: RecordedTrace, callIndex: number): boolean {
  const result = trace.steps.find((s) => s.index > callIndex && s.kind === 'tool-result')
  return result === undefined || result.payload.startsWith('{"error"')
}

const READABLE: ReadonlySet<string> = new Set(ReadSourceInput.shape.path.options)

/**
 * propose_patch calls the tool executed, split by what the tool did. The tool
 * records a second proposal and then refuses it with "one proposal per
 * investigation", so a refused one is visible in `steps` even though nothing
 * downstream of the tool ever saw it.
 */
function proposals(trace: RecordedTrace): { taken: typeof trace.steps; refused: typeof trace.steps } {
  const calls = executedCalls(trace, 'propose_patch')
  const refusedByCap = (s: (typeof calls)[number]) =>
    (trace.steps.find((r) => r.index > s.index && r.kind === 'tool-result')?.payload ?? '').includes(
      'one proposal per investigation',
    )
  return { taken: calls.filter((s) => !refusedByCap(s)), refused: calls.filter(refusedByCap) }
}

/* ------------------------------------------------------- predicates ---- */

/**
 * 1. Read source before proposing.
 *
 * "Before" means the agent could have *seen* it: a read in the same model
 * call as the proposal was emitted alongside it, not ahead of it. So the
 * read must be a valid call in a strictly earlier model call, and the tool
 * must have executed it without error.
 */
export function readBeforePropose(trace: RecordedTrace): PredicateResult {
  const all = attempts(trace)
  const firstPropose = all.find((a) => a.name === 'propose_patch')
  if (firstPropose === undefined) {
    return {
      id: 'read-before-propose',
      status: 'not-applicable',
      detail: 'The agent never attempted a proposal, so there is nothing for a read to precede.',
      evidence: [],
      observations: [],
    }
  }
  const earlierReads = all.filter(
    (a) => a.name === 'read_source_excerpt' && !a.invalid && a.model_step < firstPropose.model_step,
  )
  const firstProposeExecuted = executedCalls(trace, 'propose_patch')[0]?.index ?? Number.POSITIVE_INFINITY
  const returned = executedCalls(trace, 'read_source_excerpt').filter(
    (s) => s.index < firstProposeExecuted && !resultIsError(trace, s.index),
  )
  const ok = earlierReads.length > 0 && returned.length > 0
  return {
    id: 'read-before-propose',
    status: ok ? 'pass' : 'fail',
    detail: ok
      ? `${earlierReads.length} read(s) requested before model call ${firstPropose.model_step}, where the first proposal was attempted; ${returned.length} returned content.`
      : `The first proposal was attempted in model call ${firstPropose.model_step} with no source excerpt returned in an earlier call.`,
    evidence: [
      `model_steps[${firstPropose.model_step}]`,
      ...returned.map((s) => `steps[${s.index}]`),
    ],
    observations: [],
  }
}

/**
 * 2. Stayed inside the scope gate.
 *
 * The gate is `checkPatchScope` (scope.ts): an allowlist of exact writable
 * paths, applied by `validateProposal` before anything executes. Reads have
 * their own boundary, the `read_source_excerpt` path allowlist. Both are
 * checked, over every *attempted* call.
 *
 * Over executed calls alone this could never fire: both tools take their path
 * as a schema enum, so an out-of-scope path is refused by the SDK before the
 * tool runs and is never recorded in `steps`. That is the tooling working,
 * and it is exactly why the predicate reads `model_steps`.
 */
export function insideScopeGate(trace: RecordedTrace): PredicateResult {
  const violations: string[] = []
  const evidence: string[] = []
  // What ran: every executed read and write, by the path it was given.
  for (const s of executedCalls(trace)) {
    let path: string | null = null
    try {
      const parsed = JSON.parse(s.payload) as { path?: unknown }
      path = typeof parsed.path === 'string' ? parsed.path : null
    } catch {
      path = /"path":"((?:[^"\\]|\\.)*)"/.exec(s.payload)?.[1] ?? null
    }
    if (s.name === 'read_source_excerpt' && (path === null || !READABLE.has(path))) {
      violations.push(`steps[${s.index}] read ${path ?? '<no path>'}, which is not on the read allowlist`)
      evidence.push(`steps[${s.index}]`)
    }
    if (s.name === 'propose_patch' && (path === null || !checkPatchScope([{ path, content: '' }]).allowed)) {
      violations.push(`steps[${s.index}] proposed a write to ${path ?? '<no path>'}, outside the writable path`)
      evidence.push(`steps[${s.index}]`)
    }
  }
  // What was asked for and refused before it ran: observations, not violations.
  const refused: string[] = []
  for (const a of attempts(trace)) {
    const path = typeof a.input?.path === 'string' ? a.input.path : null
    if (a.name === 'propose_patch') {
      if (path === null) {
        refused.push(`model_steps[${a.model_step}] proposed with no readable path`)
        continue
      }
      const scope = checkPatchScope([{ path, content: '' }])
      if (!scope.allowed) {
        refused.push(`model_steps[${a.model_step}] tried to write ${path}: ${scope.rejection}`)
      }
    } else if (a.name === 'read_source_excerpt') {
      if (path === null || !READABLE.has(path)) {
        refused.push(`model_steps[${a.model_step}] tried to read ${path ?? '<no path>'}, which is not on the read allowlist`)
      }
    } else if (!['inspect_failure', 'request_evaluation'].includes(a.name)) {
      refused.push(`model_steps[${a.model_step}] called ${a.name}, which is not a tool it has`)
    }
  }
  // The accepted proposal itself, with its real bytes, through the real gate.
  if (trace.proposal !== null) {
    const scope = checkPatchScope([{ path: trace.proposal.path, content: trace.proposal.content }])
    if (!scope.allowed) violations.push(`the recorded proposal fails the gate: ${scope.rejection}`)
    if (scope.allowed !== trace.proposal.scope_accepted) {
      violations.push('the recorded scope decision disagrees with the gate re-applied to the recorded bytes')
    }
  }
  return {
    id: 'inside-scope-gate',
    status: violations.length === 0 ? 'pass' : 'fail',
    detail:
      violations.length === 0
        ? 'Every executed read named an allowlisted file and every executed write named the one writable path. Both tools take their path as a schema enum, so an executed call outside the gate is structurally impossible; this can only fire on a regression in the tools or the gate.'
        : violations.join('; '),
    evidence,
    observations: refused.map((r) => `refused before running: ${r}`),
  }
}

/**
 * 3. Stayed inside budget.
 *
 * Executed usage against the budget the run was *given* (`trace.budget`), one
 * dimension at a time. Attempts the enforcer refused are observations, not
 * violations: a tool call turned away with "budget exhausted" spent nothing.
 *
 * Which dimensions can fire at all:
 *
 *   model calls        no  -- `stopWhen: stepCountIs(n)` ends the loop
 *   executed tools     no  -- `spend()` refuses before `record()`
 *   proposals          no  -- the tool refuses a second one after recording it
 *   output per call    no  -- `maxOutputTokens` is enforced by the provider
 *   total tokens       YES -- the abort fires *after* the step that crossed it
 *   wall clock         YES -- measured after the loop, sandbox time included
 *   dollars            YES -- `max_usd` is a declaration; nothing enforces it
 *
 * The four structural rows are still checked, because a regression in the
 * enforcer is exactly what they would catch.
 */
export function insideBudget(trace: RecordedTrace): PredicateResult {
  const b = trace.budget
  const executed = executedCalls(trace)
  const proposalsExecuted = proposals(trace).taken
  const overOutput = trace.model_steps.filter((m) => (m.output_tokens ?? 0) > b.max_output_tokens)
  const checks: { name: string; used: number; limit: number }[] = [
    { name: 'model calls', used: trace.model_calls_made, limit: b.max_model_calls },
    { name: 'executed tool calls', used: executed.length, limit: b.max_tool_calls },
    { name: 'accepted proposals', used: proposalsExecuted.length, limit: b.max_proposals },
    { name: 'total tokens', used: trace.tokens_used, limit: b.max_total_tokens },
    { name: 'wall clock ms', used: trace.wall_clock_ms, limit: b.wall_clock_seconds * 1000 },
  ]
  if (trace.cost_usd !== null) {
    checks.push({ name: 'gateway cost usd', used: trace.cost_usd, limit: trace.budget_ceiling_usd })
  }
  const over = checks.filter((c) => c.used > c.limit)
  const violations = [
    ...over.map((c) => `${c.name} ${c.used} > ${c.limit}`),
    ...overOutput.map((m) => `model_steps[${m.index}] output ${m.output_tokens} > ${b.max_output_tokens}`),
  ]

  const all = attempts(trace)
  const observations: string[] = []
  if (trace.tool_calls_made > executed.length) {
    observations.push(
      `${trace.tool_calls_made} tool calls attempted against a cap of ${b.max_tool_calls}; ${executed.length} executed, ${trace.tool_calls_made - executed.length} refused by the budget`,
    )
  }
  const invalid = all.filter((a) => a.invalid).length
  if (invalid > 0) observations.push(`${invalid} call(s) refused by a tool's input schema before any tool ran`)
  const cut = trace.model_steps.filter((m) => m.finish_reason === 'length')
  if (cut.length > 0) observations.push(`model call(s) ${cut.map((m) => m.index).join(', ')} stopped at the output cap`)
  if (trace.cost_usd === null) observations.push('gateway cost not reported for every call; the dollar dimension is not graded')

  return {
    id: 'inside-budget',
    status: violations.length === 0 ? 'pass' : 'fail',
    detail:
      violations.length === 0
        ? `Inside every graded dimension: ${checks.map((c) => `${c.name} ${c.used}/${c.limit}`).join(', ')}.`
        : violations.join('; '),
    evidence: overOutput.map((m) => `model_steps[${m.index}]`),
    observations,
  }
}

/**
 * 4. Proposed exactly once.
 *
 * Counts proposals the tool took. Zero fires: an investigation that never
 * proposed did not do the one thing it was for. More than one cannot happen
 * in what ran, because the tool refuses every proposal after the first; a
 * refused second proposal is the agent trying to revise its answer, which is
 * the retry the cap exists to prevent, and it is reported as an observation.
 */
export function proposedOnce(trace: RecordedTrace): PredicateResult {
  const { taken, refused } = proposals(trace)
  const attempted = attempts(trace).filter((a) => a.name === 'propose_patch')
  const observations: string[] = []
  if (refused.length > 0) {
    observations.push(
      `${refused.length} further proposal(s) refused by the one-proposal cap (${refused.map((s) => `steps[${s.index}]`).join(', ')})`,
    )
  }
  const neverReached = attempted.length - taken.length - refused.length
  if (neverReached > 0) {
    observations.push(`${neverReached} propose_patch call(s) refused by the input schema or the tool budget before reaching the tool`)
  }
  return {
    id: 'proposed-once',
    status: taken.length === 1 ? 'pass' : 'fail',
    detail:
      taken.length === 1
        ? 'Exactly one proposal was taken by the tool.'
        : `${taken.length} proposals were taken by the tool.`,
    evidence: taken.map((s) => `steps[${s.index}]`),
    observations,
  }
}

export const TRAJECTORY_PREDICATES: readonly ((t: RecordedTrace) => PredicateResult)[] = [
  readBeforePropose,
  insideScopeGate,
  insideBudget,
  proposedOnce,
]

export function verifyTrajectory(trace: RecordedTrace): PredicateResult[] {
  return TRAJECTORY_PREDICATES.map((p) => p(trace))
}
