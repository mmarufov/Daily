/**
 * A public summary of the September 21 working-tree experiment.
 * This is a separate artifact from a Lab parser execution and from current CI.
 */
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

import { z } from 'zod'

import { ProvenanceNoteSchema, type ParseResult } from './artifact'

export const GUARD_EXPERIMENT_HREF = '/experiments/batch-alignment.json' as const

const sha256 = z.string().regex(/^[a-f0-9]{64}$/)
const rate = z.number().min(0).max(1)
const count = z.number().int().nonnegative()
const SourceSchema = z.object({
  path: z.string(),
  sha256,
  recorded_git_sha: z.string(),
  recorded_created_at: z.string(),
})

const SummarySchema = z.object({
  recall_at_k_mean: rate,
  raw_recall_at_k_mean: rate,
  recall_at_retrieval_mean: rate,
  never_rate_mean: rate,
  need_to_know_recall_mean: rate,
  needle_recall_mean: rate,
  lookalike_rate_mean: rate,
  event_delivery_mean: rate,
  judge_recall_mean: rate,
  calls_total: count,
  cache_misses_total: count,
  cost_usd_total: z.number().nonnegative(),
}).catchall(z.number().nullable())

export const GuardExperimentSchema = z.object({
  artifact_version: z.literal(1),
  experiment_id: z.literal('batch-alignment-guard'),
  scope: z.literal('historical-working-tree-experiment'),
  recorded_on: z.literal('2026-09-21'),
  runner: z.literal('prod-llm'),
  snapshot: z.literal('2026-09-02'),
  k: z.literal(12),
  fixtures: z.literal(10),
  original: z.object({
    source: SourceSchema,
    execution_mode: z.literal('unknown'),
    summary: SummarySchema,
  }),
  guard: z.object({
    source: SourceSchema,
    execution_mode: z.literal('offline-replay-reported'),
    revision_is_guard_commit: z.literal(false),
    implementation_sha256: z.null(),
    summary: SummarySchema,
  }),
  input_provenance: z.object({
    equivalence: z.literal('reported-by-historical-note'),
    finding: z.object({ path: z.string(), sha256 }),
    reference_revision: z.string(),
    reference_files: z.array(z.object({ path: z.string(), sha256 })).min(1),
    recorded_cache_keys: z.object({
      original_count: count,
      guard_count: count,
      original_sha256: sha256,
      guard_sha256: sha256,
      hash_encoding: z.literal('sorted keys joined by newline, no trailing newline'),
    }),
    needles: z.literal(true),
    quiet_corpus: z.literal(false),
  }),
  observations: z.object({
    guard_fires: count,
    largest_reported_mismatch: z.object({ returned: count, sent: count }),
  }),
  historical_test_result: z.object({
    failed: count,
    passed: count,
    skipped: count,
    subtests_passed: count,
    baseline_re_recorded: z.literal(false),
    failures: z.array(z.object({ metric: z.string(), snapshot: z.string() })),
  }),
  notes: z.array(ProvenanceNoteSchema).min(1),
}).superRefine((value, context) => {
  if (value.historical_test_result.failures.length !== value.historical_test_result.failed) {
    context.addIssue({
      code: 'custom',
      path: ['historical_test_result', 'failed'],
      message: 'The failure total must match the named historical gate failures.',
    })
  }
})

export type GuardExperiment = z.infer<typeof GuardExperimentSchema>

export function parseGuardExperiment(input: unknown): ParseResult<GuardExperiment> {
  const parsed = GuardExperimentSchema.safeParse(input)
  return parsed.success
    ? { ok: true, value: parsed.data }
    : {
        ok: false,
        issues: parsed.error.issues.map((issue) => `${issue.path.join('.')}: ${issue.message}`),
      }
}

export async function loadGuardExperimentResult(): Promise<ParseResult<GuardExperiment>> {
  try {
    const raw = await readFile(join(process.cwd(), 'public', GUARD_EXPERIMENT_HREF), 'utf8')
    return parseGuardExperiment(JSON.parse(raw) as unknown)
  } catch (error) {
    return { ok: false, issues: [error instanceof Error ? error.message : String(error)] }
  }
}

export async function loadGuardExperiment(): Promise<GuardExperiment | null> {
  const result = await loadGuardExperimentResult()
  return result.ok ? result.value : null
}
