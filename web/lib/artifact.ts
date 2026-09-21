/**
 * The versioned public artifact the web application consumes.
 *
 * This is deliberately a different shape from the harness's on-disk scorecard
 * (lib/scorecard.ts). The export step reads a scorecard, establishes what can
 * actually be known about its provenance, and emits this. Anything that cannot
 * be established is recorded as the literal string 'unknown' rather than
 * guessed, inferred from a sibling field, or filled with today's value.
 *
 * Three provenance rules are enforced by construction here:
 *
 *  1. The revision that EXECUTED an evaluation is not the revision that STORED
 *     it, and neither is the revision that built this artifact. All three get
 *     their own field.
 *  2. Importing a historical scorecard is not the same act as executing a run.
 *     `origin` distinguishes them and can never be inferred later.
 *  3. Embedded timestamps are evidence, not truth. When a file's metadata
 *     contradicts its content, `timestamps_trustworthy` goes false and a note
 *     records why, with a citation.
 */

import { z } from 'zod'

export const ARTIFACT_VERSION = 1 as const

/** Explicit sentinel. Never substitute null, 0, '', or a nearby value. */
export const UNKNOWN = 'unknown' as const
export type Unknown = typeof UNKNOWN

const unknownable = <T extends z.ZodTypeAny>(inner: T) =>
  z.union([inner, z.literal(UNKNOWN)])

/**
 * A provenance caveat. Every note carries a citation so a reader can check it
 * against the repository rather than taking the UI's word for it.
 */
export const ProvenanceNoteSchema = z.object({
  severity: z.enum(['info', 'caution', 'warning']),
  message: z.string(),
  /** Repository path, optionally with a line reference, or a command. */
  source: z.string(),
})
export type ProvenanceNote = z.infer<typeof ProvenanceNoteSchema>

export const SnapshotProvenanceSchema = z.object({
  name: z.string(),
  sha256: unknownable(z.string()),
  n_articles: z.number().int().nullable(),
  built_at: unknownable(z.string()),
  frozen_now: unknownable(z.string()),
  derived_from: z.string().nullable(),
  removed_clusters: z.array(z.string()),
  note: z.string().nullable(),
})

export const LabelProvenanceSchema = z.object({
  snapshot: z.string(),
  /** Persona/article label rows, NOT unique articles. */
  rows: z.number().int(),
  /** Distinct article ids appearing in any persona's label file. */
  unique_articles: z.number().int(),
  personas: z.number().int(),
  /** Counts keyed by the label file's own `source` field. */
  by_source: z.record(z.string(), z.number().int()),
  models: z.array(z.string()),
  contested: z.number().int(),
  /**
   * Label review status. The harness records `source=model` or `source=agent`;
   * product-owner human review is outstanding, so no artifact may claim human
   * ground truth.
   */
  status: z.enum(['provisional-model-and-agent', 'human-reviewed', UNKNOWN]),
})

export const ProvenanceSchema = z.object({
  /** Revision recorded inside the scorecard: what executed the evaluation. */
  eval_revision: unknownable(z.string()),
  /**
   * Whether `eval_revision` is reachable from the repository's default branch.
   * `47edb50` is not — it is a side branch off b48f244, and everything under
   * backend/evals/ reached main in a single squash commit. A dashboard that
   * links "revision -> result" has to say so, or the link is a lie.
   */
  eval_revision_reachable: z.union([z.boolean(), z.literal(UNKNOWN)]),
  /** Revision that produced THIS artifact. */
  artifact_revision: unknownable(z.string()),
  artifact_built_at: z.string(),
  /** Revision whose tree contains the scorecard file. */
  storage_revision: unknownable(z.string()),

  /** Embedded `created_at` from the scorecard. */
  run_created_at: unknownable(z.string()),
  /** False when file metadata or content contradicts the embedded timestamps. */
  timestamps_trustworthy: z.boolean(),

  runner: z.string(),
  /** The `--runner` value that produces this output name, when determinable. */
  runner_cli_arg: unknownable(z.string()),
  protocol: unknownable(z.string()),
  protocol_source: z.enum(['recorded', 'absent-in-source']),
  k: z.number().int(),

  execution_mode: z.enum(['offline-replay', 'live', UNKNOWN]),
  /** Why `execution_mode` has the value it does. */
  execution_mode_basis: z.string(),

  needles: z.union([z.boolean(), z.literal(UNKNOWN)]),
  quiet: z.union([z.boolean(), z.literal(UNKNOWN)]),
  /** Model identifiers observed in per-persona meta, deduplicated. */
  models: z.array(z.string()),
  /** Number of response-cache keys the run touched. */
  cache_keys: z.number().int().nullable(),

  snapshot: SnapshotProvenanceSchema,
  labels: LabelProvenanceSchema.nullable(),
  notes: z.array(ProvenanceNoteSchema),
})
export type Provenance = z.infer<typeof ProvenanceSchema>

export const StoryOutcomeSchema = z.enum([
  'delivered-wanted',
  'delivered-unwanted',
  'delivered-unlabelled',
  'lost-before-scorer',
  'lost-at-or-after-scorer',
])
export type StoryOutcome = z.infer<typeof StoryOutcomeSchema>

export const StorySchema = z.object({
  id: z.string(),
  title: z.string().nullable(),
  source: z.string().nullable(),
  /** Ground-truth label where one exists. */
  label: z.string().nullable(),
  /** Final position in the delivered feed, 1-indexed, null when not delivered. */
  rank: z.number().int().nullable(),
  score: z.number().nullable(),
  /** Stage at which the story left the pipeline, null when delivered. */
  dropped_at: z.string().nullable(),
  /**
   * Text the harness recorded alongside the drop. Diagnostic only: for some
   * stages it is a model rationale, for others a mechanical label such as
   * "Matched your profile". It is never proof the explanation is correct.
   */
  reason: z.string().nullable(),
  /** True when `reason` was stored already truncated; preserved as-is. */
  reason_truncated: z.boolean(),
  outcome: StoryOutcomeSchema,
})
export type Story = z.infer<typeof StorySchema>

export const FunnelStepArtifactSchema = z.object({
  stage: z.string(),
  label: z.string(),
  explanation: z.string().nullable(),
  terminal: z.number().int(),
  survivors: z.number().int(),
  lost_entering_stage: z.number().int(),
  pass_rate: z.number().nullable(),
  absent: z.boolean(),
})

export const DropReasonArtifactSchema = z.object({
  key: z.string(),
  group: z.string(),
  detail: z.string().nullable(),
  count: z.number().int(),
  maps_to_stage: z.boolean(),
})

export const PersonaArtifactSchema = z.object({
  key: z.string(),
  metrics: z.record(z.string(), z.number().nullable()),
  counts: z.object({
    must_see: z.number().int().nullable(),
    need_to_know: z.number().int().nullable(),
    labelled: z.number().int().nullable(),
    feed_size: z.number().int().nullable(),
    feed_size_at_k: z.number().int().nullable(),
    unlabelled_in_feed: z.number().int().nullable(),
    distinct_sources: z.number().int().nullable(),
  }),
  funnel: z.array(FunnelStepArtifactSchema),
  /** Stage tallies present in the source but absent from the declared order. */
  unrecognised_stages: z.array(z.string()),
  drop_reasons: z.array(DropReasonArtifactSchema),
  /** Must-see attribution: which stage lost a story the reader needed. */
  loss_by_stage: z.record(z.string(), z.number().int()),
  stories: z.array(StorySchema),
  /** True when the source scorecard carried no per-story trace at all. */
  trace_available: z.boolean(),
  meta: z.record(z.string(), z.unknown()),
})
export type PersonaArtifact = z.infer<typeof PersonaArtifactSchema>

export const BaselineIntegritySchema = z.object({
  is_baseline: z.boolean(),
  /** Snapshots for which this file carries gate thresholds. */
  snapshot_baseline_keys: z.array(z.string()),
  /**
   * Snapshots where the baseline's stored thresholds disagree with the
   * committed run scorecard for the same runner and snapshot.
   */
  disagrees_with_run: z.array(z.string()),
})

export const ArtifactSchema = z.object({
  artifact_version: z.literal(ARTIFACT_VERSION),
  /** Stable identity: runner + snapshot + eval revision. */
  run_id: z.string(),
  origin: z.enum(['imported-historical', 'executed']),
  provenance: ProvenanceSchema,
  summary: z.record(z.string(), z.number().nullable()),
  /** Run-level must-see attribution, summed over personas. */
  summary_loss_by_stage: z.record(z.string(), z.number().int()),
  personas: z.array(PersonaArtifactSchema),
  baseline: BaselineIntegritySchema,
})
export type Artifact = z.infer<typeof ArtifactSchema>

export const ManifestEntrySchema = z.object({
  run_id: z.string(),
  file: z.string(),
  runner: z.string(),
  snapshot: z.string(),
  protocol: unknownable(z.string()),
  k: z.number().int(),
  origin: z.enum(['imported-historical', 'executed']),
  eval_revision: unknownable(z.string()),
  is_baseline: z.boolean(),
  personas: z.number().int(),
  /** sha256 of the emitted artifact file, for integrity checking. */
  sha256: z.string(),
  bytes: z.number().int(),
})
export type ManifestEntry = z.infer<typeof ManifestEntrySchema>

export const ManifestSchema = z.object({
  manifest_version: z.literal(ARTIFACT_VERSION),
  /** Revision that produced every artifact listed. */
  artifact_revision: unknownable(z.string()),
  built_at: z.string(),
  /** Set only once every listed artifact has been written and validated. */
  complete: z.literal(true),
  entries: z.array(ManifestEntrySchema),
  snapshots: z.array(SnapshotProvenanceSchema),
  notes: z.array(ProvenanceNoteSchema),
})
export type Manifest = z.infer<typeof ManifestSchema>

export type ParseResult<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly issues: readonly string[] }

function toIssues(error: z.ZodError): readonly string[] {
  return error.issues.map((i) => `${i.path.join('.') || '<root>'}: ${i.message}`)
}

export function parseArtifact(input: unknown): ParseResult<Artifact> {
  const r = ArtifactSchema.safeParse(input)
  return r.success ? { ok: true, value: r.data } : { ok: false, issues: toIssues(r.error) }
}

export function parseManifest(input: unknown): ParseResult<Manifest> {
  const r = ManifestSchema.safeParse(input)
  return r.success ? { ok: true, value: r.data } : { ok: false, issues: toIssues(r.error) }
}
