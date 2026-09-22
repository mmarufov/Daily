/**
 * Schemas for the two things that cross the trust boundary.
 *
 * Cases go in, prediction records come out. Both are validated here, in trusted
 * code, before anything reads them — a malformed record is a failed run, never
 * a quietly skipped case.
 */

import { z } from 'zod'

import { CASE_FAMILIES, PROTOCOLS } from './spec'

export const ArticleSchema = z.object({
  id: z.string().min(1),
  title: z.string(),
  source: z.string(),
})
export type Article = z.infer<typeof ArticleSchema>

export const RecordedResponseSchema = z.object({
  content: z.string().nullable(),
  finish_reason: z.string().nullable(),
  error: z.string().nullable(),
})

export const ExpectedVerdictSchema = z.object({
  relevant: z.boolean(),
  score: z.number(),
})

export const ExpectationSchema = z.object({
  expect: z.enum(['parse', 'refuse']),
  /** Present only for `parse`: the exact association every article must get. */
  association: z.record(z.string(), ExpectedVerdictSchema).nullable(),
  /** Acceptable refusal kinds. Diagnostic for universal-refusal families. */
  refusal_kinds: z.array(z.string()),
  why: z.string(),
})

export const CaseSchema = z.object({
  case_id: z.string().min(1),
  group: z.enum(['observed', 'synthetic']),
  origin: z.enum(['recorded-replay', 'fault-injection']),
  protocol: z.enum(PROTOCOLS),
  family: z.enum(CASE_FAMILIES),
  articles: z.array(ArticleSchema).min(1),
  response: RecordedResponseSchema,
  expectation: ExpectationSchema,
  snapshot: z.string().optional(),
  completion_tokens: z.number().int().nullable().optional(),
})
export type Case = z.infer<typeof CaseSchema>

export const CaseSuiteSchema = z.object({
  case_suite_version: z.literal(1),
  group: z.enum(['observed', 'synthetic']),
  generated_from: z.string(),
  n_cases: z.number().int(),
  cases: z.array(CaseSchema),
  snapshot: z.string().optional(),
})
export type CaseSuite = z.infer<typeof CaseSuiteSchema>

/**
 * What a candidate is allowed to say.
 *
 * Note what is absent: any field meaning "I passed". `outcome` describes what
 * the parser did, never whether it was right. Unknown keys are stripped by zod
 * rather than carried through, so a candidate cannot smuggle a self-assessment
 * into the artifact either.
 */
export const PredictionRecordSchema = z.object({
  case_id: z.string(),
  outcome: z.enum(['parsed', 'refused', 'crashed', 'timeout']),
  association: z
    .record(
      z.string(),
      z.object({
        relevant: z.boolean(),
        score: z.number().nullable(),
        reason: z.string(),
      }),
    )
    .nullable(),
  refusal_kind: z.string().nullable(),
  error: z.string().nullable(),
  ms: z.number(),
})
export type PredictionRecord = z.infer<typeof PredictionRecordSchema>

export const RecordBundleSchema = z.object({
  records_version: z.literal(1),
  /** Self-declared. Treated as a claim and checked, never trusted. */
  declared_version_id: z.string(),
  declared_protocol: z.string(),
  python: z.string(),
  n_cases: z.number().int(),
  elapsed_ms: z.number(),
  records: z.array(PredictionRecordSchema),
})
export type RecordBundle = z.infer<typeof RecordBundleSchema>

export type ParseResult<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly issues: readonly string[] }

function toIssues(error: z.ZodError): readonly string[] {
  return error.issues.map((i) => `${i.path.join('.') || '<root>'}: ${i.message}`)
}

export function parseCaseSuite(input: unknown): ParseResult<CaseSuite> {
  const r = CaseSuiteSchema.safeParse(input)
  return r.success ? { ok: true, value: r.data } : { ok: false, issues: toIssues(r.error) }
}

export function parseRecordBundle(input: unknown): ParseResult<RecordBundle> {
  const r = RecordBundleSchema.safeParse(input)
  return r.success ? { ok: true, value: r.data } : { ok: false, issues: toIssues(r.error) }
}
