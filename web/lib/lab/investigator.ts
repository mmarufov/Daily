/**
 * The investigator: four narrow tools and a hard budget.
 *
 * Built after the evaluator, on purpose. An agent that proposes patches is
 * only interesting if something trustworthy grades them, and the order the
 * pieces were built in is the order they have to be trusted in.
 *
 * **Nothing here has been executed.** There is no `AI_GATEWAY_API_KEY` in this
 * environment and no spending limit configured, so `readiness()` reports
 * `missing-credentials` and `/lab` says no agent has run. The tool schemas,
 * the scope enforcement and the budget are real code with real tests; the
 * model call is not, and no trace is depicted anywhere. Fabricating one would
 * make every other number on this site worth less.
 *
 * The important property is that an agent-authored candidate takes exactly the
 * same path as a human-authored one: `propose_patch` returns a patch, the scope
 * gate accepts or refuses it, the sandbox runs it, and the trusted evaluator
 * decides. There is no branch anywhere that asks a model whether a patch looks
 * correct.
 */

import { z } from 'zod'

import { checkPatchScope, type PatchFile } from './scope'
import { ALLOWED_PATCH_PATHS } from './spec'

/** One proposal per investigation, and a ceiling on everything it may spend. */
export interface InvestigationBudget {
  readonly max_proposals: number
  readonly max_tool_calls: number
  readonly max_model_calls: number
  readonly max_output_tokens: number
  readonly max_usd: number
  readonly wall_clock_seconds: number
}

export const BUDGET: InvestigationBudget = {
  max_proposals: 1,
  max_tool_calls: 12,
  max_model_calls: 6,
  max_output_tokens: 4096,
  max_usd: 0.5,
  wall_clock_seconds: 180,
}

/* ------------------------------------------------------------- tools ---- */

export const InspectFailureInput = z.object({
  /** A case id from the published suite. Free-form strings are refused. */
  case_id: z.string().regex(/^(observed-\d{4}-\d{2}-\d{2}-\d{3}|syn-[a-z0-9-]+)$/),
})

export const ReadSourceInput = z.object({
  path: z.enum([
    'backend/lab/contract/versions/positional_v0.py',
    'backend/lab/contract/versions/count_guard_v1.py',
    'backend/app/services/openai_service.py',
    'backend/app/services/ranking_contract.py',
  ]),
  /** Bounded excerpt: the agent reads lines, never the repository. */
  start_line: z.number().int().min(1).max(5000),
  line_count: z.number().int().min(1).max(120),
})

export const ProposePatchInput = z.object({
  path: z.enum(ALLOWED_PATCH_PATHS as unknown as [string, ...string[]]),
  content: z.string().min(1).max(64 * 1024),
  /** One sentence, with a case id or file:line it is grounded in. */
  hypothesis: z.string().min(20).max(600),
  evidence: z.array(z.string()).min(1).max(8),
})

export const RequestEvaluationInput = z.object({
  candidate_id: z.string().regex(/^agent-[a-z0-9-]{1,40}$/),
})

export const TOOLS = [
  {
    name: 'inspect_failure',
    description:
      'Read one recorded case: the articles that were sent, the response that came back, and what the expectation is. Returns no more than one case.',
    input: InspectFailureInput,
  },
  {
    name: 'read_source_excerpt',
    description:
      'Read a bounded excerpt of one allowlisted file. Cannot enumerate the repository and cannot read the evaluator, the cases or the labels.',
    input: ReadSourceInput,
  },
  {
    name: 'propose_patch',
    description:
      'Submit one candidate parser, with a hypothesis grounded in specific evidence. Subject to the patch scope gate.',
    input: ProposePatchInput,
  },
  {
    name: 'request_evaluation',
    description:
      'Run the proposed candidate against the frozen case suite in the sandbox. Returns prediction records only; the verdict is computed by trusted code.',
    input: RequestEvaluationInput,
  },
] as const

export type ToolName = (typeof TOOLS)[number]['name']

/* --------------------------------------------------------- readiness ---- */

export type Readiness =
  | { readonly ready: true; readonly gateway: string }
  | { readonly ready: false; readonly reason: 'missing-credentials' | 'missing-budget'; readonly needs: readonly string[] }

/**
 * Whether the investigator can actually run.
 *
 * Deliberately not a boolean with a fallback. There is no mock model and no
 * "demo mode" — if the credential is absent the investigation does not happen,
 * and the site reports that instead of showing something that looks like it
 * did.
 */
export function readiness(env: Readonly<Record<string, string | undefined>> = process.env): Readiness {
  const key = env.AI_GATEWAY_API_KEY ?? env.OPENAI_API_KEY
  const needs: string[] = []
  if (key === undefined || key.trim() === '') {
    needs.push('AI_GATEWAY_API_KEY (or OPENAI_API_KEY) for the investigator')
  }
  if (needs.length > 0) return { ready: false, reason: 'missing-credentials', needs }
  if ((env.LAB_MAX_USD ?? '').trim() === '') {
    return {
      ready: false,
      reason: 'missing-budget',
      needs: ['LAB_MAX_USD — an explicit per-investigation spending limit'],
    }
  }
  return { ready: true, gateway: env.AI_GATEWAY_API_KEY !== undefined ? 'vercel-ai-gateway' : 'openai-direct' }
}

/* -------------------------------------------------------- proposals ---- */

export interface ProposalOutcome {
  readonly accepted: boolean
  readonly reason: string
  readonly files: readonly PatchFile[]
}

/**
 * Validate a proposal before anything executes.
 *
 * The agent's own justification is recorded and never graded: a hypothesis is
 * a pointer to evidence for a human, not an input to the verdict.
 */
export function validateProposal(
  input: unknown,
  realpaths: ReadonlyMap<string, string> = new Map(),
): ProposalOutcome {
  const parsed = ProposePatchInput.safeParse(input)
  if (!parsed.success) {
    return {
      accepted: false,
      reason: `the proposal does not match the tool schema: ${parsed.error.issues
        .map((i) => `${i.path.join('.') || '<root>'}: ${i.message}`)
        .join('; ')}`,
      files: [],
    }
  }
  const files: PatchFile[] = [{ path: parsed.data.path, content: parsed.data.content }]
  const scope = checkPatchScope(files, realpaths)
  if (!scope.allowed) {
    return { accepted: false, reason: `${scope.rejection}: ${scope.detail}`, files: [] }
  }
  return { accepted: true, reason: 'within scope; queued for sandboxed evaluation', files }
}
