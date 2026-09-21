/**
 * Runtime validation for the raw scorecards committed under
 * backend/evals/results/.
 *
 * This schema describes the harness's *internal* on-disk format. It is parsed
 * at the export boundary only; the web application consumes the versioned
 * public artifact in lib/artifact.ts instead. Keeping the two separate means a
 * change to the harness's private format cannot silently reshape the UI.
 *
 * Object shapes are loose rather than strict on purpose: the harness adds
 * per-runner keys (`meta.protocol`, `reader_preparation`, `global_pool_frozen`)
 * and dropping them on parse would discard provenance we want to record.
 */

import { z } from 'zod'

/** A metric the harness may legitimately report as absent. */
const nullableNumber = z.number().nullable()

export const FeedEntrySchema = z.looseObject({
  id: z.string(),
  rank: z.number().int(),
  title: z.string().optional(),
  source: z.string().nullable().optional(),
  label: z.string().nullable().optional(),
  score: z.number().nullable().optional(),
})

export const LossEntrySchema = z.looseObject({
  id: z.string(),
  title: z.string().optional(),
  dropped_at: z.string().nullable().optional(),
  reason: z.string().nullable().optional(),
  score: z.number().nullable().optional(),
})

export const NeverInFeedSchema = z.looseObject({
  id: z.string(),
  title: z.string().optional(),
  rank: z.number().int().optional(),
})

export const PersonaResultSchema = z.looseObject({
  n_must_see: z.number().optional(),
  n_need_to_know: z.number().optional(),
  n_labelled: z.number().optional(),

  recall_at_k: nullableNumber.optional(),
  raw_recall_at_k: nullableNumber.optional(),
  recall_at_retrieval: nullableNumber.optional(),
  need_to_know_recall: nullableNumber.optional(),
  followup_recall: nullableNumber.optional(),
  never_rate: nullableNumber.optional(),
  event_delivery: nullableNumber.optional(),
  major_delivery: nullableNumber.optional(),
  false_major_rate: nullableNumber.optional(),
  event_slot_contamination: nullableNumber.optional(),
  judge_precision: nullableNumber.optional(),
  judge_recall: nullableNumber.optional(),
  judge_n: nullableNumber.optional(),
  needle_recall: nullableNumber.optional(),
  lookalike_rate: nullableNumber.optional(),

  feed_size: z.number().optional(),
  feed_size_k: z.number().optional(),
  feed_size_flag: z.unknown().optional(),
  unlabelled_in_feed: z.number().optional(),
  distinct_sources: z.number().optional(),

  calls: z.number().optional(),
  cost_usd: nullableNumber.optional(),
  latency_s: nullableNumber.optional(),
  cache_hits: z.number().optional(),
  cache_misses: z.number().optional(),

  stage_counts: z.record(z.string(), z.number()).default({}),
  drop_counts: z.record(z.string(), z.number()).default({}),
  loss_by_stage: z.record(z.string(), z.number()).default({}),

  feed: z.array(FeedEntrySchema).default([]),
  losses: z.array(LossEntrySchema).default([]),
  never_in_feed: z.array(NeverInFeedSchema).default([]),

  meta: z.looseObject({}).default({}),
})

export const SummarySchema = z
  .record(z.string(), z.union([z.number(), z.null(), z.record(z.string(), z.number())]))

export const ScorecardSchema = z.looseObject({
  git_sha: z.string(),
  runner: z.string(),
  snapshot: z.string(),
  k: z.number().int(),
  created_at: z.string(),
  summary: SummarySchema,
  per_persona: z.record(z.string(), PersonaResultSchema),
  cache_keys: z.array(z.string()).default([]),
  meta: z.looseObject({}).default({}),

  // Baseline files only.
  baseline_created_at: z.string().optional(),
  snapshot_baselines: z.record(z.string(), SummarySchema).optional(),
})

export type FeedEntry = z.infer<typeof FeedEntrySchema>
export type LossEntry = z.infer<typeof LossEntrySchema>
export type PersonaResult = z.infer<typeof PersonaResultSchema>
export type Scorecard = z.infer<typeof ScorecardSchema>

export function isBaseline(card: Scorecard): boolean {
  return card.snapshot_baselines !== undefined || card.baseline_created_at !== undefined
}

/**
 * Parse a scorecard, returning either the validated value or the collected
 * issues. Callers must handle failure explicitly; the export command treats a
 * malformed scorecard as a hard error rather than skipping it silently.
 */
export type ParseResult<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly issues: readonly string[] }

export function parseScorecard(input: unknown): ParseResult<Scorecard> {
  const result = ScorecardSchema.safeParse(input)
  if (result.success) return { ok: true, value: result.data }
  return {
    ok: false,
    issues: result.error.issues.map(
      (issue) => `${issue.path.join('.') || '<root>'}: ${issue.message}`,
    ),
  }
}
