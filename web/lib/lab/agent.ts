/**
 * The investigation loop, actually wired to a model.
 *
 * `investigator.ts` defines the tools, the budget and the scope rules and has
 * been tested since the day it was written. What it never had was a model on
 * the other end, and the site said so. This is that half.
 *
 * The property worth protecting is narrow and easy to lose: **an
 * agent-authored candidate takes exactly the same path as a human-authored
 * one.** It is written to `backend/lab/contract/candidate.py`, the scope gate
 * accepts or refuses it, the sandbox runs it because its bytes match no
 * committed implementation, and the trusted evaluator grades the records. No
 * branch below asks the model whether its own patch looks correct, and the
 * model never sees the evaluator, the criteria, or its own verdict.
 *
 * The agent can therefore fail, and the honest outcome of a failure is a
 * rejected candidate — not a retry loop that keeps going until something
 * passes, which would make the accept rate a property of the budget.
 */

import { generateText, stepCountIs, tool } from 'ai'
import { z } from 'zod'

import {
  BUDGET,
  InspectFailureInput,
  ProposePatchInput,
  ReadSourceInput,
  RequestEvaluationInput,
  readiness,
  validateProposal,
} from './investigator'
import type { Case } from './records'
import type { Evaluation } from './evaluator'

/**
 * Default model, overridable by `LAB_MODEL`.
 *
 * A `provider/model` string routed through the AI Gateway rather than a
 * provider SDK: the gateway is what meters the spend this budget is measured
 * against, so going direct would make the recorded cost unverifiable.
 */
export const DEFAULT_MODEL = 'anthropic/claude-sonnet-4.5'

const SYSTEM = `You are investigating a defect in a news-ranking pipeline.

A batch scorer sends N articles to a language model and receives a JSON array
of verdicts. The current parser associates results[i] with articles[i] and pads
the tail with zeros when the counts differ. When the model returns verdicts in
a different order, or returns a different number of them, every article after
the first divergence receives another article's verdict, and nothing refuses.

Your task: write ONE self-contained Python file implementing a parser that does
not have this defect.

Hard constraints on the file you submit:
- It defines parse(articles, response) -> dict.
- It is standard-library only. No project imports, no third-party packages.
- It inlines the contract prelude: ok(), refuse(), verdict(), finite_unit_score().
  Copy them exactly as they appear in the files you can read.
- It sets VERSION_ID and PROTOCOL module constants.
- Return ok(verdicts) for a complete unambiguous association, or
  refuse(kind, detail) with a kind from the closed vocabulary.

Investigate before you propose. You have one proposal and it is graded by code
you cannot see, read, or influence. A refusal is a correct answer when the
response cannot be associated; inventing an association to avoid refusing is
the defect you are here to remove.`

/* ----------------------------------------------------------- tracing ---- */

export interface TraceStep {
  readonly index: number
  readonly kind: 'model-text' | 'tool-call' | 'tool-result'
  readonly name: string | null
  /** Arguments or result, JSON, truncated. Never a credential: none is in scope. */
  readonly payload: string
  readonly at_ms: number
}

export interface InvestigationTrace {
  readonly model: string
  readonly gateway: string
  readonly started_at: string
  readonly wall_clock_ms: number
  readonly steps: readonly TraceStep[]
  /** As reported by the gateway, not estimated here. */
  readonly usage: {
    readonly input_tokens: number | null
    readonly output_tokens: number | null
    readonly total_tokens: number | null
  }
  readonly finish_reason: string
  /**
   * Set when the call itself failed rather than finishing.
   *
   * A trace is still returned in that case, and that is the point: tool calls
   * made before the failure were paid for, and spend that produced no record
   * of itself is the worst outcome available here. `finish_reason` reads
   * `error` so nothing downstream mistakes it for a completed loop.
   */
  readonly error: string | null
  readonly budget: typeof BUDGET
  /** The effective limit: the lower of the authorisation and the code ceiling. */
  readonly budget_ceiling_usd: number
  /** What the operator authorised, recorded so the clamp is visible. */
  readonly budget_authorised_usd: number
  readonly tool_calls_made: number
  readonly proposal: ProposalRecord | null
}

export interface ProposalRecord {
  readonly candidate_id: string
  readonly path: string
  readonly content: string
  readonly hypothesis: string
  readonly evidence: readonly string[]
  readonly scope_accepted: boolean
  readonly scope_reason: string
}

const MAX_PAYLOAD = 4_000

/**
 * Strip terminal control sequences.
 *
 * The AI Gateway's errors are written for a terminal and arrive wrapped in
 * ANSI colour codes. Left alone they end up in a committed artifact as
 * `\u001b[1m\u001b[31m…`, which is noise in a file whose purpose is to be
 * read by a person and diffed by a reviewer.
 */
function plain(text: string): string {
  // eslint-disable-next-line no-control-regex
  return text.replace(/\u001b\[[0-9;]*m/g, '')
}

function truncate(value: unknown): string {
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text.length > MAX_PAYLOAD ? `${text.slice(0, MAX_PAYLOAD)}\n… [${text.length} chars total]` : text
}

/* ---------------------------------------------------------- budget ---- */

export type BudgetResolution =
  | { readonly ok: true; readonly ceiling: number; readonly authorised: number }
  | { readonly ok: false; readonly needs: readonly string[] }

/**
 * Two ceilings, and the tighter one wins.
 *
 *   LAB_MAX_USD     what the operator authorised on this deployment
 *   BUDGET.max_usd  what this experiment was reviewed as needing
 *
 * This used to *refuse* an authorisation above the reviewed ceiling, which
 * had the asymmetry backwards. Being allowed more than the code will spend is
 * not a hazard; the code spending more than it was allowed is. A refusal also
 * had the perverse property that it could be satisfied by raising the code
 * ceiling, which is the opposite of what a ceiling is for.
 *
 * Pure, and exported, so the arithmetic can be tested without a dry-run mode
 * in the production path. A "skip the model call" branch is a mock with a
 * respectable name, and the one thing this repository must not have is a code
 * path that produces an investigation nobody paid for.
 */
export function resolveBudget(
  env: Readonly<Record<string, string | undefined>>,
  reviewed: number = BUDGET.max_usd,
): BudgetResolution {
  const authorised = Number(env.LAB_MAX_USD)
  if (!Number.isFinite(authorised) || authorised <= 0) {
    return { ok: false, needs: ['LAB_MAX_USD must be a positive number of dollars'] }
  }
  return { ok: true, ceiling: Math.min(authorised, reviewed), authorised }
}

/* --------------------------------------------------------- the loop ---- */

export interface InvestigationDeps {
  /** The frozen case suite the agent may inspect. */
  readonly cases: readonly Case[]
  /** Bounded reader for the allowlisted source paths. */
  readonly readSource: (path: string, startLine: number, lineCount: number) => string
  /**
   * Runs a proposed candidate in the sandbox and grades it with the trusted
   * evaluator. Injected so the loop cannot reach either one directly.
   */
  readonly evaluateCandidate: (
    candidateId: string,
    source: string,
  ) => Promise<{ summary: string; evaluation: Evaluation | null }>
  readonly onProgress?: (step: string) => void
  /**
   * Fired the moment the scope gate rules, so an orchestration log records
   * the decision at the time it was made rather than reconstructing it from
   * the trace afterwards — the ordering is the evidence that the gate ran
   * before the sandbox did.
   */
  readonly onScopeDecision?: (decision: { accepted: boolean; path: string; reason: string }) => void
}

export type InvestigationResult =
  | { readonly ok: true; readonly trace: InvestigationTrace }
  /** Refused before anything was spent. There is no trace because nothing ran. */
  | { readonly ok: false; readonly reason: 'missing-credentials' | 'missing-budget'; readonly needs: readonly string[] }
  /** The call failed partway. A trace is returned, because spend happened. */
  | {
      readonly ok: false
      readonly reason: 'call-failed'
      readonly needs: readonly string[]
      readonly trace: InvestigationTrace
    }

/**
 * Run one investigation.
 *
 * Refuses before spending anything if the credential or the explicit spending
 * ceiling is absent. `readiness()` is checked here rather than at the call
 * site so there is no path that reaches the model without passing it.
 */
export async function investigate(
  deps: InvestigationDeps,
  env: Readonly<Record<string, string | undefined>> = process.env,
): Promise<InvestigationResult> {
  const ready = readiness(env)
  if (!ready.ready) {
    return { ok: false, reason: ready.reason, needs: ready.needs }
  }

  const budget = resolveBudget(env)
  if (!budget.ok) return { ok: false, reason: 'missing-budget', needs: budget.needs }
  const { ceiling, authorised } = budget

  const model = env.LAB_MODEL ?? DEFAULT_MODEL
  const onProgress = deps.onProgress ?? (() => {})
  const steps: TraceStep[] = []
  const startedAt = Date.now()
  let toolCalls = 0
  let proposal: ProposalRecord | null = null
  let proposedSource: string | null = null

  const record = (kind: TraceStep['kind'], name: string | null, payload: unknown): void => {
    steps.push({
      index: steps.length,
      kind,
      name,
      payload: truncate(payload),
      at_ms: Date.now() - startedAt,
    })
  }

  /** Every tool shares one ceiling; exceeding it ends the tool, not the run. */
  const spend = (name: string): string | null => {
    toolCalls += 1
    if (toolCalls > BUDGET.max_tool_calls) {
      return `budget exhausted: ${BUDGET.max_tool_calls} tool calls is the ceiling. Submit your proposal now or stop.`
    }
    onProgress(`tool ${toolCalls}/${BUDGET.max_tool_calls}: ${name}`)
    return null
  }

  const tools = {
    inspect_failure: tool({
      description:
        'Read one recorded case: the articles that were sent, the response that came back, and what a correct parser is expected to do. Returns one case.',
      inputSchema: InspectFailureInput,
      execute: async ({ case_id }) => {
        const over = spend('inspect_failure')
        if (over !== null) return over
        record('tool-call', 'inspect_failure', { case_id })
        const kase = deps.cases.find((c) => c.case_id === case_id)
        if (kase === undefined) {
          const result = {
            error: 'no such case',
            available_sample: deps.cases.slice(0, 8).map((c) => c.case_id),
          }
          record('tool-result', 'inspect_failure', result)
          return result
        }
        const result = {
          case_id: kase.case_id,
          group: kase.group,
          family: kase.family,
          protocol: kase.protocol,
          articles: kase.articles.map((a) => ({ id: a.id, title: a.title })),
          response: kase.response,
          expectation: kase.expectation,
        }
        record('tool-result', 'inspect_failure', result)
        return result
      },
    }),

    read_source_excerpt: tool({
      description:
        'Read a bounded excerpt of one allowlisted file. Cannot enumerate the repository and cannot read the evaluator, the criteria or the labels.',
      inputSchema: ReadSourceInput,
      execute: async ({ path, start_line, line_count }) => {
        const over = spend('read_source_excerpt')
        if (over !== null) return over
        record('tool-call', 'read_source_excerpt', { path, start_line, line_count })
        try {
          const excerpt = deps.readSource(path, start_line, line_count)
          record('tool-result', 'read_source_excerpt', excerpt)
          return { path, start_line, excerpt }
        } catch (error) {
          const result = { error: error instanceof Error ? error.message : String(error) }
          record('tool-result', 'read_source_excerpt', result)
          return result
        }
      },
    }),

    propose_patch: tool({
      description:
        'Submit your one candidate parser, with a hypothesis grounded in specific evidence. Subject to the patch scope gate. You may call this once.',
      inputSchema: ProposePatchInput,
      execute: async (input) => {
        const over = spend('propose_patch')
        if (over !== null) return over
        record('tool-call', 'propose_patch', {
          path: input.path,
          hypothesis: input.hypothesis,
          evidence: input.evidence,
          content_bytes: input.content.length,
        })
        if (proposal !== null) {
          const result = { accepted: false, reason: 'one proposal per investigation; you have used it' }
          record('tool-result', 'propose_patch', result)
          return result
        }
        const outcome = validateProposal(input)
        proposal = {
          candidate_id: 'agent-001',
          path: input.path,
          content: input.content,
          hypothesis: input.hypothesis,
          evidence: input.evidence,
          scope_accepted: outcome.accepted,
          scope_reason: outcome.reason,
        }
        if (outcome.accepted) proposedSource = input.content
        deps.onScopeDecision?.({
          accepted: outcome.accepted,
          path: input.path,
          reason: outcome.reason,
        })
        const result = { accepted: outcome.accepted, reason: outcome.reason }
        record('tool-result', 'propose_patch', result)
        return result
      },
    }),

    request_evaluation: tool({
      description:
        'Run your accepted proposal against the frozen case suite in the sandbox. Returns a summary of what the records showed. The verdict is computed by trusted code and is not returned to you.',
      inputSchema: RequestEvaluationInput,
      execute: async ({ candidate_id }) => {
        const over = spend('request_evaluation')
        if (over !== null) return over
        record('tool-call', 'request_evaluation', { candidate_id })
        if (proposedSource === null) {
          const result = { error: 'no accepted proposal to evaluate' }
          record('tool-result', 'request_evaluation', result)
          return result
        }
        const { summary } = await deps.evaluateCandidate(candidate_id, proposedSource)
        record('tool-result', 'request_evaluation', summary)
        return { summary }
      },
    }),
  }

  onProgress(`calling ${model} through the AI Gateway`)

  const assemble = (
    usage: { input: number | null; output: number | null; total: number | null },
    finishReason: string,
    error: string | null,
  ): InvestigationTrace => ({
    model,
    gateway: ready.gateway,
    started_at: new Date(startedAt).toISOString(),
    wall_clock_ms: Date.now() - startedAt,
    steps,
    usage: { input_tokens: usage.input, output_tokens: usage.output, total_tokens: usage.total },
    finish_reason: finishReason,
    error,
    budget: BUDGET,
    budget_ceiling_usd: ceiling,
    budget_authorised_usd: authorised,
    tool_calls_made: toolCalls,
    proposal,
  })

  try {
    const result = await generateText({
      model,
      system: SYSTEM,
      prompt:
        'Investigate the association defect and submit one candidate parser. Start by reading the current implementation and at least two recorded cases.',
      tools,
      stopWhen: stepCountIs(BUDGET.max_model_calls),
      maxOutputTokens: BUDGET.max_output_tokens,
      abortSignal: AbortSignal.timeout(BUDGET.wall_clock_seconds * 1000),
    })

    for (const step of result.steps) {
      if (step.text.trim() !== '') record('model-text', null, step.text)
    }

    return {
      ok: true,
      trace: assemble(
        {
          input: result.totalUsage.inputTokens ?? null,
          output: result.totalUsage.outputTokens ?? null,
          total: result.totalUsage.totalTokens ?? null,
        },
        result.finishReason,
        null,
      ),
    }
  } catch (cause) {
    // Still a trace. Whatever tool calls happened before this were paid for,
    // and the usage totals are unavailable because the call that would have
    // reported them is the one that failed -- so they are null rather than
    // zero, which would read as "this cost nothing".
    const message = plain(cause instanceof Error ? `${cause.name}: ${cause.message}` : String(cause))
    onProgress(`the call failed after ${toolCalls} tool calls: ${message.slice(0, 120)}`)
    return {
      ok: false,
      reason: 'call-failed',
      needs: [message.slice(0, 600)],
      trace: assemble({ input: null, output: null, total: null }, 'error', message.slice(0, 2000)),
    }
  }
}

export const TraceSchema = z.object({
  model: z.string(),
  gateway: z.string(),
  started_at: z.string(),
  wall_clock_ms: z.number(),
  steps: z.array(
    z.object({
      index: z.number(),
      kind: z.enum(['model-text', 'tool-call', 'tool-result']),
      name: z.string().nullable(),
      payload: z.string(),
      at_ms: z.number(),
    }),
  ),
})
