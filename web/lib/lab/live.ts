/**
 * What a live run reports back to the visitor who started it.
 *
 * The evaluator's `Evaluation` is the whole truth and is not trimmed here for
 * convenience. What this adds is the join a reader needs and the evaluator has
 * no reason to make: each case's origin (recorded or fault-injected) and the
 * sentence saying what was wrong with the response. Without that join a run
 * can say *that* a case failed and not *which fault* caught it, and the fault
 * is the point.
 *
 * Type-only imports, so client components can use this file without pulling
 * the evaluator, zod or `node:crypto` into the browser.
 */

import type { CaseStatus, CriterionResult, Evaluation } from './evaluator'
import type { Case } from './records'
import type { SandboxExecution } from './sandbox'

/**
 * Strings a candidate controls, cut to a length that can be shown.
 *
 * A refusal kind and the first line of a crash are the parser's own words.
 * They are shown, because they are the parser's account of itself, and
 * labelled as such wherever they appear.
 */
const CANDIDATE_TEXT_MAX = 160

function clip(text: string | null, max = CANDIDATE_TEXT_MAX): string | null {
  if (text === null) return null
  return text.length > max ? `${text.slice(0, max)}…` : text
}

export interface LiveCase {
  readonly case_id: string
  readonly group: Case['group']
  readonly origin: Case['origin']
  readonly family: Case['family']
  readonly protocol: Case['protocol']
  readonly applicability: 'scored' | 'not-applicable'
  readonly status: CaseStatus
  /** The evaluator's sentence; for a crash, the first line of the parser's error. */
  readonly detail: string
  /** What is wrong with this response, from the frozen case suite. */
  readonly why: string
  readonly expected_refusal_kinds: readonly string[]
  /** What the parser called its refusal. The parser's words, not ours. */
  readonly observed_refusal_kind: string | null
}

export interface LiveGrading {
  readonly verdict: Evaluation['verdict']
  readonly reason: string
  readonly spec_version: number
  readonly spec_hash: string
  /** Self-declared by the candidate, and checked rather than believed. */
  readonly declared_protocol: string
  readonly criteria: readonly Pick<CriterionResult, 'id' | 'question' | 'applicable' | 'satisfied' | 'passed'>[]
  readonly counts: Evaluation['counts']
  /** Cases outside its declared protocol on which it associated anyway. */
  readonly out_of_protocol_case_ids: readonly string[]
  readonly cases: readonly LiveCase[]
}

export function summariseGrading(evaluation: Evaluation, cases: readonly Case[]): LiveGrading {
  const byId = new Map(cases.map((c) => [c.case_id, c]))
  return {
    verdict: evaluation.verdict,
    reason: evaluation.reason,
    spec_version: evaluation.spec_version,
    spec_hash: evaluation.spec_hash,
    declared_protocol: clip(evaluation.declared_protocol, 40) ?? 'unknown',
    criteria: evaluation.criteria.map((c) => ({
      id: c.id,
      question: c.question,
      applicable: c.applicable,
      satisfied: c.satisfied,
      passed: c.passed,
    })),
    counts: evaluation.counts,
    out_of_protocol_case_ids:
      evaluation.diagnostics.find((d) => d.id === 'out-of-protocol-association')?.case_ids ?? [],
    cases: evaluation.outcomes.map((o) => {
      const kase = byId.get(o.case_id)
      return {
        case_id: o.case_id,
        group: o.group,
        origin: kase?.origin ?? (o.group === 'synthetic' ? 'fault-injection' : 'recorded-replay'),
        family: o.family,
        protocol: o.protocol,
        applicability: o.applicability,
        status: o.status,
        detail: clip(o.detail, 240) ?? '',
        why: kase?.expectation.why ?? '',
        expected_refusal_kinds: o.expected_refusal_kinds,
        observed_refusal_kind: clip(o.observed_refusal_kind, 60),
      }
    }),
  }
}

/** A fault-injected case that was scored against this parser and not passed. */
export function caughtByFault(grading: LiveGrading): readonly LiveCase[] {
  return grading.cases.filter(
    (c) => c.origin === 'fault-injection' && c.applicability === 'scored' && c.status !== 'correct',
  )
}

/** A recorded case that was scored against this parser and not passed. */
export function wrongOnRecorded(grading: LiveGrading): readonly LiveCase[] {
  return grading.cases.filter(
    (c) => c.origin === 'recorded-replay' && c.applicability === 'scored' && c.status !== 'correct',
  )
}

/* --------------------------------------------------------- sandbox --- */

/**
 * The microVM's own account of the run, every value read back off the
 * platform. A field the platform did not report is null, and renders as
 * "not measured" rather than as a zero.
 */
export interface SandboxSummary {
  readonly sandbox_id: string
  readonly region: string
  readonly runtime: string
  readonly network_policy: string
  readonly boot_ms: number
  readonly wall_clock_ms: number
  readonly active_cpu_ms: number | null
  readonly egress_bytes: number | null
  readonly exit_code: number
  readonly isolation: readonly { readonly name: string; readonly expectation: string; readonly held: boolean }[]
}

export function summariseSandbox(execution: SandboxExecution): SandboxSummary {
  return {
    sandbox_id: execution.sandbox_id,
    region: execution.region,
    runtime: execution.runtime,
    network_policy: execution.network_policy,
    boot_ms: execution.boot_ms,
    wall_clock_ms: execution.wall_clock_ms,
    active_cpu_ms: execution.active_cpu_ms,
    egress_bytes: execution.egress_bytes,
    exit_code: execution.exit_code,
    isolation: execution.isolation.map((p) => ({ name: p.name, expectation: p.expectation, held: p.held })),
  }
}

/* -------------------------------------------------------- progress --- */

/** One thing that happened, written to the run's stream as it happened. */
export interface ProgressEvent {
  readonly at: string
  readonly stage: string
}

export function isProgressEvent(value: unknown): value is ProgressEvent {
  const v = value as { at?: unknown; stage?: unknown } | null
  return typeof v?.at === 'string' && typeof v?.stage === 'string'
}

/** The stream namespace progress is written to and read from. */
export const PROGRESS_NAMESPACE = 'progress'

/* ---------------------------------------------------- what the page reads --- */

/**
 * The outcome as the page reads it off `GET /api/lab/run/[runId]`.
 *
 * Structural rather than imported from `orchestration.ts`, which is workflow
 * code. Every field is optional where a run that ended early would not have
 * it, so the page cannot render a value a run never produced.
 */
export interface LiveOutcome {
  readonly kind: 'graded' | 'incomplete' | 'rejected-by-scope' | (string & {})
  readonly verdict?: Evaluation['verdict'] | null
  readonly reason?: string
  readonly detail?: string
  readonly grading?: LiveGrading | null
  readonly sandbox?: SandboxSummary | null
}

export interface RunStatusBody {
  readonly run_id: string
  readonly status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  readonly finished: boolean
  readonly outcome: LiveOutcome | null
  readonly progress: readonly ProgressEvent[] | null
}

/** A case as the page lists it before any run: the suite, without answers. */
export interface CatalogCase {
  readonly case_id: string
  readonly origin: Case['origin']
  readonly protocol: Case['protocol']
  readonly why: string
}
