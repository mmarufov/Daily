/**
 * The published experiment artifact.
 *
 * A sibling of `lib/artifact.ts`, deliberately built on the same three rules
 * that file establishes, because they were right there and this is the same
 * repository making the same kind of claim:
 *
 *  1. Revisions that mean different things get different fields. The revision
 *     that EXECUTED a run, the revision that BUILT the artifact and the
 *     revision the candidate was written against are three facts, not one.
 *  2. Importing is not executing — `execution_mode` records which happened.
 *  3. What cannot be established is written as the literal string `unknown`.
 *     Never null, never zero, never inferred from a neighbour.
 *
 * One rule is added here, because this artifact describes a judgement rather
 * than a measurement: **the criteria a run was judged against travel with the
 * run**, as `spec_hash`. Editing a threshold changes the hash, so a verdict can
 * never be silently re-interpreted under criteria it never faced.
 */

import { z } from 'zod'

import { PROTOCOLS } from './spec'

export const LAB_ARTIFACT_VERSION = 1 as const
export const UNKNOWN = 'unknown' as const

const unknownable = <T extends z.ZodTypeAny>(inner: T) => z.union([inner, z.literal(UNKNOWN)])

/** Where a candidate came from. Never inferred after the fact. */
export const CandidateKindSchema = z.enum([
  'preserved-version', // transcribed from a real revision of this repository
  'seeded-control', // deliberately defective, labelled as such everywhere
  'human-authored', // written by a person for this experiment
  'agent-authored', // produced by the investigator, with a stored trace
])
export type CandidateKind = z.infer<typeof CandidateKindSchema>

export const CandidateSchema = z.object({
  candidate_id: z.string(),
  kind: CandidateKindSchema,
  /** Human-readable note on what it does and, for controls, what is wrong. */
  description: z.string(),
  /** Protocol the candidate declares. Checked against the cases, not trusted. */
  declared_protocol: z.union([z.enum(PROTOCOLS), z.literal(UNKNOWN)]),
  source_path: z.string(),
  source_sha256: z.string(),
  source_bytes: z.number().int(),
  /** Revision of this repository the source was taken from, where it has one. */
  transcribed_from: unknownable(z.string()),
  /**
   * Unified diff against the historical parser, so "what changed" is reviewable
   * without leaving the page — and downloadable, so it can be applied.
   */
  patch: z.string(),
  patch_base: z.string(),
})

export const CaseSuiteRefSchema = z.object({
  group: z.enum(['observed', 'synthetic']),
  path: z.string(),
  sha256: z.string(),
  n_cases: z.number().int(),
  generated_from: z.string(),
})

export const UsageSchema = z.object({
  /** Inference calls this run made. Zero for every run in the committed set. */
  model_calls: z.number().int(),
  /** Actual provider spend for THIS run. */
  replay_spend_usd: z.number(),
  /** Cost of the recordings being replayed, when it is known. */
  recording_cost_usd: unknownable(z.number()),
  /** Provider-reported usage, distinct from any estimate. */
  provider_reported: z.union([z.record(z.string(), z.number()), z.literal(UNKNOWN)]),
  basis: z.string(),
})

export const AttemptSchema = z.object({
  attempt_id: z.string(),
  started_at: z.string(),
  ended_at: unknownable(z.string()),
  status: z.enum(['succeeded', 'failed', 'cancelled', 'superseded', 'unknown-outcome']),
  runner: z.enum(['local-known', 'vercel-sandbox']),
  note: z.string(),
})

/**
 * Evidence that a run crossed the isolation boundary.
 *
 * Present only for `vercel-sandbox` runs, and absent — not zeroed, not
 * defaulted — for local ones. Every field here is read back off the platform
 * after the fact rather than copied from the request: recording the
 * `networkPolicy` that was *asked for* would establish only that the ask was
 * made.
 *
 * `egress_bytes` is the platform's meter and is an upper bound, not a
 * measurement of candidate traffic: it includes the control-plane bytes this
 * run caused by reading the record bundle back, so it is non-zero on a run
 * where the candidate reached nothing. The direct evidence is `isolation`.
 */
export const SandboxExecutionSchema = z.object({
  sandbox_id: z.string(),
  runtime: z.string(),
  region: z.string(),
  network_policy: z.string(),
  egress_bytes: unknownable(z.number().int()),
  active_cpu_ms: unknownable(z.number()),
  boot_ms: z.number(),
  wall_clock_ms: z.number(),
  exit_code: z.number().int(),
  /** Everything the candidate could see. The evaluator is not in this list. */
  uploaded: z.array(z.object({ path: z.string(), sha256: z.string(), bytes: z.number().int() })),
  /** Negative controls. `held: false` on any of these invalidates the run. */
  isolation: z.array(
    z.object({
      name: z.string(),
      command: z.string(),
      expectation: z.string(),
      held: z.boolean(),
      observed: z.string(),
    }),
  ),
})
export type SandboxExecutionRecord = z.infer<typeof SandboxExecutionSchema>

/**
 * The investigation that authored a candidate, when one did.
 *
 * The hypothesis is recorded and never graded. It is a pointer to evidence for
 * a human reader; letting it influence the verdict would be exactly the
 * self-assessment the whole boundary exists to prevent.
 */
export const InvestigationSchema = z.object({
  model: z.string(),
  gateway: z.string(),
  started_at: z.string(),
  wall_clock_ms: z.number(),
  finish_reason: z.string(),
  tool_calls_made: z.number().int(),
  max_tool_calls: z.number().int(),
  budget_ceiling_usd: z.number(),
  /** As metered by the gateway, not estimated here. */
  usage: z.object({
    input_tokens: unknownable(z.number().int()),
    output_tokens: unknownable(z.number().int()),
    total_tokens: unknownable(z.number().int()),
  }),
  hypothesis: z.string(),
  evidence: z.array(z.string()),
  scope_accepted: z.boolean(),
  scope_reason: z.string(),
  /** Path to the committed, sanitised trace. */
  trace_path: z.string(),
  n_trace_steps: z.number().int(),
})

export const LabProvenanceSchema = z.object({
  /**
   * The revision the harness ran at, recorded by the orchestrator at the
   * moment it ran rather than re-derived afterwards. Carries `+dirty` when the
   * tree was edited, because a run from an edited tree is not a run at that
   * commit.
   */
  executed_at_revision: unknownable(z.string()),
  /**
   * Content hash over every input this run was derived from. Replaces a git
   * revision on purpose: a committed export has to be a pure function of
   * committed bytes, and `git log --format=%h` is not one — `core.abbrev`
   * defaults to `auto` and varies with a clone's object count.
   */
  inputs_sha256: z.string(),
  executed_at: unknownable(z.string()),
  /** Content hash of the trusted code that computed the verdict. */
  evaluator_sha256: z.string(),
  spec_hash: z.string(),
  spec_version: z.number().int(),
  execution_mode: z.enum(['offline-replay', 'live', UNKNOWN]),
  execution_mode_basis: z.string(),
  python: unknownable(z.string()),
  /** Where the candidate executed, and the evidence for it. */
  runner: z.enum(['local-known', 'vercel-sandbox']),
  sandbox: SandboxExecutionSchema.nullable(),
  investigation: InvestigationSchema.nullable(),
  case_suites: z.array(CaseSuiteRefSchema),
  notes: z.array(
    z.object({
      severity: z.enum(['info', 'caution', 'warning']),
      message: z.string(),
      /** A repository path or command, so a reader can check rather than trust. */
      source: z.string(),
    }),
  ),
})

export const CounterexampleSchema = z.object({
  article_id: z.string(),
  article_title: z.string(),
  expected: z.object({ relevant: z.boolean(), score: z.number() }),
  actual: z
    .object({ relevant: z.boolean(), score: z.number().nullable(), reason: z.string() })
    .nullable(),
})

export const CaseOutcomeSchema = z.object({
  case_id: z.string(),
  group: z.enum(['observed', 'synthetic']),
  family: z.enum(['universal-refusal', 'protocol-association']),
  protocol: z.enum(PROTOCOLS),
  applicability: z.enum(['scored', 'not-applicable']),
  status: z.enum([
    'correct',
    'wrong-association',
    'should-have-refused',
    'should-have-parsed',
    'crashed',
    'timeout',
    'missing-record',
    'not-applicable',
  ]),
  detail: z.string(),
  counterexample: CounterexampleSchema.nullable(),
  observed_refusal_kind: z.string().nullable(),
  expected_refusal_kinds: z.array(z.string()),
  ms: z.number().nullable(),
})

export const CriterionResultSchema = z.object({
  id: z.string(),
  question: z.string(),
  threshold: z.number(),
  applicable: z.number().int(),
  satisfied: z.number().int(),
  rate: z.number().nullable(),
  passed: z.boolean(),
})

/**
 * Measured, published, and never an input to the verdict.
 *
 * A criterion decides; a diagnostic reports. The distinction is load-bearing:
 * promoting one of these to a criterion changes the spec hash and re-decides
 * runs that never faced it, so a gap found after the fact is published as a
 * number rather than closed behind a reader's back.
 */
export const DiagnosticSchema = z.object({
  id: z.string(),
  question: z.string(),
  value: z.number().int(),
  of: z.number().int(),
  detail: z.string(),
  case_ids: z.array(z.string()),
})

export const LabRunSchema = z.object({
  lab_artifact_version: z.literal(LAB_ARTIFACT_VERSION),
  run_id: z.string(),
  experiment_id: z.string(),
  candidate: CandidateSchema,
  provenance: LabProvenanceSchema,
  verdict: z.enum(['accepted-for-review', 'rejected', 'incomplete', 'failed', 'cancelled']),
  verdict_reason: z.string(),
  /** What acceptance does and does not mean, carried with the verdict. */
  verdict_scope: z.string(),
  criteria: z.array(CriterionResultSchema),
  outcomes: z.array(CaseOutcomeSchema),
  counts: z.record(z.string(), z.number().int()),
  smallest_counterexample: CounterexampleSchema.nullable(),
  diagnostics: z.array(DiagnosticSchema),
  usage: UsageSchema,
  attempts: z.array(AttemptSchema),
})
export type LabRun = z.infer<typeof LabRunSchema>

export const LabManifestEntrySchema = z.object({
  run_id: z.string(),
  file: z.string().regex(/^[A-Za-z0-9][A-Za-z0-9._-]*\.json$/),
  candidate_id: z.string(),
  kind: CandidateKindSchema,
  verdict: z.enum(['accepted-for-review', 'rejected', 'incomplete', 'failed', 'cancelled']),
  spec_hash: z.string(),
  sha256: z.string(),
  bytes: z.number().int(),
})

export const LabManifestSchema = z.object({
  lab_manifest_version: z.literal(LAB_ARTIFACT_VERSION),
  experiment_id: z.string(),
  spec_hash: z.string(),
  inputs_sha256: z.string(),
  /** The newest run's own timestamp, never a clock reading at export time. */
  built_at: z.string(),
  /** Only set once every listed run has been written and validated. */
  complete: z.literal(true),
  entries: z.array(LabManifestEntrySchema),
  notes: z.array(z.object({ severity: z.enum(['info', 'caution', 'warning']), message: z.string(), source: z.string() })),
})
export type LabManifest = z.infer<typeof LabManifestSchema>

export type ParseResult<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly issues: readonly string[] }

function toIssues(error: z.ZodError): readonly string[] {
  return error.issues.map((i) => `${i.path.join('.') || '<root>'}: ${i.message}`)
}

export function parseLabRun(input: unknown): ParseResult<LabRun> {
  const r = LabRunSchema.safeParse(input)
  return r.success ? { ok: true, value: r.data } : { ok: false, issues: toIssues(r.error) }
}

export function parseLabManifest(input: unknown): ParseResult<LabManifest> {
  const r = LabManifestSchema.safeParse(input)
  return r.success ? { ok: true, value: r.data } : { ok: false, issues: toIssues(r.error) }
}

/** What "accepted" is allowed to mean, stated once and carried everywhere. */
export const VERDICT_SCOPE =
  'Accepted means eligible for human review under this spec hash, against a public case suite. ' +
  'It is not evidence of production quality, and it does not establish generalisation: the cases ' +
  'are visible and a candidate may have been written against them.'
