/**
 * Reproducible export: backend/evals/results/*.json -> public artifacts.
 *
 *   npm run export:artifacts            # writes web/public/artifacts/
 *   npm run export:artifacts -- --check # validates without writing
 *
 * The export establishes provenance rather than assuming it. Where a fact
 * cannot be recovered from the repository it is written as 'unknown'. Where a
 * file's own metadata contradicts its content, the contradiction is detected
 * programmatically and recorded as a note with a citation — not hardcoded, so
 * it stays honest if the underlying data changes.
 */

import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  ARTIFACT_VERSION,
  UNKNOWN,
  type Artifact,
  type Manifest,
  type ManifestEntry,
  type PersonaArtifact,
  type ProvenanceNote,
  type Story,
  type StoryOutcome,
  parseArtifact,
  parseManifest,
} from '../lib/artifact'
import { buildFunnel, normaliseDropReasons, stageOrderFor } from '../lib/funnel'
import { parseScorecard, type PersonaResult, type Scorecard } from '../lib/scorecard'

/**
 * Locate the repository root by walking up from this file (or the working
 * directory, when the loader gives us no module path) until the evaluation
 * harness is visible. Resolved this way the export behaves identically whether
 * it is run via npm from web/, directly with tsx, or from CI.
 */
function findRepoRoot(): string {
  const starts: string[] = []
  const metaUrl: string | undefined = typeof import.meta.url === 'string' ? import.meta.url : undefined
  if (metaUrl !== undefined) starts.push(dirname(fileURLToPath(metaUrl)))
  starts.push(process.cwd())

  for (const start of starts) {
    let current = resolve(start)
    for (let depth = 0; depth < 8; depth += 1) {
      if (existsSync(join(current, 'backend', 'evals', 'results'))) return current
      const parent = dirname(current)
      if (parent === current) break
      current = parent
    }
  }
  throw new Error(
    'Could not locate the repository root: no ancestor of this script or the working directory contains backend/evals/results.',
  )
}

const REPO = findRepoRoot()
const EVALS = join(REPO, 'backend', 'evals')
const RESULTS = join(EVALS, 'results')
const SNAPSHOTS = join(EVALS, 'snapshots')
const LABELS = join(EVALS, 'labels')
const OUT = join(REPO, 'web', 'public', 'artifacts')

const CHECK_ONLY = process.argv.includes('--check')

/**
 * The committed evidence an artifact is built from.
 *
 * `artifact_revision` is the last commit to touch any of these. Deliberately
 * NOT the exporter's own files: including them makes the value chase its own
 * tail, because the commit that ships a regenerated export also ships the
 * exporter change that caused it. Schema changes are covered by
 * `artifact_version` instead.
 */
const EVIDENCE_PATHS = [
  'backend/evals/results',
  'backend/evals/snapshots',
  'backend/evals/labels',
] as const

/* ------------------------------------------------------------------ git ---- */

function git(...args: readonly string[]): string | null {
  try {
    return execFileSync('git', args, { cwd: REPO, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  } catch {
    return null
  }
}

/**
 * Is `sha` an ancestor of HEAD?
 *
 * This has to give the same answer in a developer's clone and in CI, because
 * the export is committed and CI asserts the commit is in sync. That rules out
 * treating "git could not resolve the object" as unknown, since the revisions
 * these scorecards name live on abandoned branches: `47edb50` is present here
 * only as an unreferenced loose object and is absent from `git rev-list --all`,
 * so a fresh clone does not have it at all.
 *
 * The resolution is that in a complete clone, an object that is absent cannot
 * be an ancestor of HEAD -- `false` is the correct answer, not `unknown`. Only
 * a shallow clone genuinely cannot tell, because history was truncated, and
 * that case is detected rather than guessed.
 */
function isAncestor(sha: string): boolean | typeof UNKNOWN {
  if (git('rev-parse', '--is-shallow-repository') === 'true') return UNKNOWN

  try {
    execFileSync('git', ['merge-base', '--is-ancestor', sha, 'HEAD'], {
      cwd: REPO,
      stdio: 'ignore',
    })
    return true
  } catch {
    return false
  }
}

/** The commit that last touched a path, i.e. where the file is stored. */
function storageRevision(relPath: string): string | typeof UNKNOWN {
  return git('log', '-1', '--format=%h', '--', relPath) ?? UNKNOWN
}

/* ------------------------------------------------------- runner metadata --- */

/**
 * Output runner name -> the `--runner` argument that produces it, read from
 * backend/evals/runners.py:456 and run.py:120.
 *
 * `proto-hybrid-judge-events` is the ambiguous one and is deliberately left
 * unknown: it is the *default* proto runner's output name, but the stored
 * scorecards carrying it predate the protocol field, and the repository's own
 * regression gate maps this runner key to `proto-s0-legacy-v1`
 * (backend/tests/test_eval_gate.py:63). Claiming either CLI argument would be
 * a guess presented as provenance.
 */
const RUNNER_CLI_ARG: Readonly<Record<string, string>> = {
  'prod-llm': 'prod',
  'prod-fallback': 'prod-fallback',
  'proto-bm25': 'proto-bm25',
  'proto-hybrid-judge-events-s0-legacy-v1': 'proto-s0-legacy-v1',
}

/* ------------------------------------------------------------- snapshots --- */

interface SnapshotManifestRow {
  name: string
  file?: string
  built_at?: string
  frozen_now?: string
  n_articles?: number
  sha256?: string
  derived_from?: string | null
  removed_clusters?: string[]
  note?: string | null
}

function loadSnapshotManifest(): Map<string, SnapshotManifestRow> {
  const path = join(SNAPSHOTS, 'manifest.json')
  if (!existsSync(path)) return new Map()
  const raw: unknown = JSON.parse(readFileSync(path, 'utf8'))
  const rows: SnapshotManifestRow[] = Array.isArray(raw)
    ? (raw as SnapshotManifestRow[])
    : ((raw as { snapshots?: SnapshotManifestRow[] }).snapshots ?? [])
  return new Map(rows.filter((r) => typeof r.name === 'string').map((r) => [r.name, r]))
}

function snapshotProvenance(name: string, manifest: Map<string, SnapshotManifestRow>) {
  const row = manifest.get(name)
  return {
    name,
    sha256: row?.sha256 ?? UNKNOWN,
    n_articles: row?.n_articles ?? null,
    built_at: row?.built_at ?? UNKNOWN,
    frozen_now: row?.frozen_now ?? UNKNOWN,
    derived_from: row?.derived_from ?? null,
    removed_clusters: row?.removed_clusters ?? [],
    note: row?.note ?? null,
  }
}

/* ---------------------------------------------------------------- labels --- */

interface LabelRow {
  article_id?: string
  label?: string
  source?: string
  model?: string
  contested?: boolean
}

function labelProvenance(snapshot: string) {
  const dir = join(LABELS, snapshot)
  if (!existsSync(dir)) return null

  const files = readdirSync(dir).filter((f) => f.endsWith('.jsonl'))
  if (files.length === 0) return null

  const bySource = new Map<string, number>()
  const models = new Set<string>()
  const uniqueArticles = new Set<string>()
  let rows = 0
  let contested = 0

  for (const file of files) {
    for (const line of readFileSync(join(dir, file), 'utf8').split('\n')) {
      const trimmed = line.trim()
      if (trimmed === '') continue
      let row: LabelRow
      try {
        row = JSON.parse(trimmed) as LabelRow
      } catch {
        throw new Error(`Malformed label row in ${snapshot}/${file}`)
      }
      rows += 1
      if (row.article_id !== undefined) uniqueArticles.add(row.article_id)
      const source = row.source ?? UNKNOWN
      bySource.set(source, (bySource.get(source) ?? 0) + 1)
      if (row.model !== undefined) models.add(row.model)
      if (row.contested === true) contested += 1
    }
  }

  const sources = [...bySource.keys()]
  const humanReviewed = sources.includes('human') && !sources.some((s) => s === 'model' || s === 'agent')

  return {
    snapshot,
    rows,
    unique_articles: uniqueArticles.size,
    personas: files.length,
    by_source: Object.fromEntries([...bySource].sort(([a], [b]) => a.localeCompare(b))),
    models: [...models].sort(),
    contested,
    status: humanReviewed ? ('human-reviewed' as const) : ('provisional-model-and-agent' as const),
  }
}

/* --------------------------------------------------------------- stories --- */

const TRUNCATION_MARKERS = ['…', '...']

function looksTruncated(text: string | null | undefined): boolean {
  if (typeof text !== 'string') return false
  const trimmed = text.trimEnd()
  return TRUNCATION_MARKERS.some((m) => trimmed.endsWith(m))
}

function classifyOutcome(
  delivered: boolean,
  label: string | null,
  droppedAt: string | null,
  runner: string,
): StoryOutcome {
  if (delivered) {
    if (label === 'never') return 'delivered-unwanted'
    if (label === null) return 'delivered-unlabelled'
    return 'delivered-wanted'
  }
  const order = stageOrderFor(runner)
  const scorerStage = runner.startsWith('proto') ? 'judge' : 'scored'
  const scorerIndex = order.indexOf(scorerStage)
  const group = droppedAt === null ? '' : (droppedAt.split(':')[0] ?? '')
  const droppedIndex = order.indexOf(group)
  // `lookback` and other pre-load mechanisms are not stage names; they all sit
  // before the scorer, so an unrecognised reason is treated as pre-scorer only
  // when it is not a known later stage.
  if (droppedIndex === -1) return 'lost-before-scorer'
  return droppedIndex < scorerIndex ? 'lost-before-scorer' : 'lost-at-or-after-scorer'
}

function buildStories(persona: PersonaResult, runner: string): { stories: Story[]; traceAvailable: boolean } {
  const stories = new Map<string, Story>()

  for (const entry of persona.feed) {
    stories.set(entry.id, {
      id: entry.id,
      title: entry.title ?? null,
      source: entry.source ?? null,
      label: entry.label ?? null,
      rank: entry.rank,
      score: entry.score ?? null,
      dropped_at: null,
      reason: null,
      reason_truncated: false,
      outcome: classifyOutcome(true, entry.label ?? null, null, runner),
    })
  }

  for (const loss of persona.losses) {
    const existing = stories.get(loss.id)
    const title = loss.title ?? existing?.title ?? null
    const reason = loss.reason ?? null
    const story: Story = {
      id: loss.id,
      title,
      source: existing?.source ?? null,
      // A loss row carries no label field; must-see status is implied by the
      // harness only including missed must-sees here, so nothing is asserted.
      label: existing?.label ?? null,
      rank: existing?.rank ?? null,
      score: loss.score ?? existing?.score ?? null,
      dropped_at: loss.dropped_at ?? null,
      reason,
      reason_truncated: looksTruncated(reason) || looksTruncated(title),
      outcome: classifyOutcome(false, existing?.label ?? null, loss.dropped_at ?? null, runner),
    }
    stories.set(loss.id, story)
  }

  for (const never of persona.never_in_feed) {
    const existing = stories.get(never.id)
    if (existing) {
      stories.set(never.id, { ...existing, label: 'never' })
    }
  }

  const traceAvailable = persona.losses.length > 0 || persona.feed.length > 0
  return {
    stories: [...stories.values()].sort((a, b) => {
      if (a.rank !== null && b.rank !== null) return a.rank - b.rank
      if (a.rank !== null) return -1
      if (b.rank !== null) return 1
      return a.id.localeCompare(b.id)
    }),
    traceAvailable,
  }
}

/* -------------------------------------------------------------- personas --- */

const PERSONA_METRIC_KEYS = [
  'recall_at_k',
  'raw_recall_at_k',
  'recall_at_retrieval',
  'need_to_know_recall',
  'followup_recall',
  'never_rate',
  'event_delivery',
  'major_delivery',
  'false_major_rate',
  'event_slot_contamination',
  'judge_precision',
  'judge_recall',
  'needle_recall',
  'lookalike_rate',
  'latency_s',
  'cost_usd',
  'calls',
  'distinct_sources',
  'feed_size_k',
] as const

function toPersonaArtifact(key: string, persona: PersonaResult, runner: string): PersonaArtifact {
  const metrics: Record<string, number | null> = {}
  for (const metric of PERSONA_METRIC_KEYS) {
    const value = persona[metric]
    // undefined (absent from this runner) and null (reported as absent) are
    // both recorded as null; neither becomes zero.
    metrics[metric] = typeof value === 'number' ? value : null
  }

  const funnel = buildFunnel(persona.stage_counts, runner)
  const { stories, traceAvailable } = buildStories(persona, runner)

  return {
    key,
    metrics,
    counts: {
      must_see: persona.n_must_see ?? null,
      need_to_know: persona.n_need_to_know ?? null,
      labelled: persona.n_labelled ?? null,
      feed_size: persona.feed_size ?? null,
      feed_size_at_k: persona.feed_size_k ?? null,
      unlabelled_in_feed: persona.unlabelled_in_feed ?? null,
      distinct_sources: persona.distinct_sources ?? null,
    },
    funnel: funnel.steps.map((s) => ({
      stage: s.stage,
      label: s.label,
      explanation: s.explanation ?? null,
      terminal: s.terminal,
      survivors: s.survivors,
      lost_entering_stage: s.lostEnteringStage,
      pass_rate: s.passRate,
      absent: s.absent,
    })),
    unrecognised_stages: [...funnel.unrecognisedStages],
    drop_reasons: normaliseDropReasons(persona.drop_counts, runner).map((d) => ({
      key: d.key,
      group: d.group,
      detail: d.detail,
      count: d.count,
      maps_to_stage: d.mapsToStage,
    })),
    loss_by_stage: persona.loss_by_stage,
    stories,
    trace_available: traceAvailable,
    meta: persona.meta as Record<string, unknown>,
  }
}

/* --------------------------------------------------------------- summary --- */

function flattenSummary(summary: Scorecard['summary']): {
  metrics: Record<string, number | null>
  lossByStage: Record<string, number>
} {
  const metrics: Record<string, number | null> = {}
  let lossByStage: Record<string, number> = {}
  for (const [key, value] of Object.entries(summary)) {
    if (key === 'loss_by_stage') {
      if (value !== null && typeof value === 'object') lossByStage = value as Record<string, number>
      continue
    }
    if (value === null) {
      metrics[key] = null
    } else if (typeof value === 'number') {
      metrics[key] = value
    }
    // Nested objects other than loss_by_stage (e.g. global_preparation) are
    // structured provenance, not scalar metrics, and are not flattened here.
  }
  return { metrics, lossByStage }
}

/* ------------------------------------------------------------ provenance --- */

const SUMMARY_KEYS_ADDED_AFTER_STORAGE = [
  'reader_pipeline_calls_max_per_persona',
  'event_slot_contamination_mean',
] as const

function buildNotes(card: Scorecard, relPath: string, reachable: boolean | typeof UNKNOWN): ProvenanceNote[] {
  const notes: ProvenanceNote[] = []

  if (reachable === false) {
    notes.push({
      severity: 'warning',
      message: `The revision that executed this run (${card.git_sha}) is not reachable from the current default branch, so "this result came from that code" cannot be verified by checking out the revision. Everything under backend/evals/ reached the default branch in a single squash commit.`,
      source: `git merge-base --is-ancestor ${card.git_sha} HEAD`,
    })
  } else if (reachable === UNKNOWN) {
    notes.push({
      severity: 'caution',
      message: `Whether ${card.git_sha} is reachable from the current branch could not be determined in this environment.`,
      source: `git merge-base --is-ancestor ${card.git_sha} HEAD`,
    })
  }

  const meta = card.meta as Record<string, unknown>
  if (typeof meta.protocol !== 'string') {
    notes.push({
      severity: 'warning',
      message:
        'This scorecard records no protocol identifier. The harness only began emitting one later (backend/evals/run.py writes meta.protocol), so the evaluation protocol cannot be read from the artifact and is reported as unknown rather than inferred from the runner name.',
      source: 'backend/evals/run.py',
    })
  }

  const missing = SUMMARY_KEYS_ADDED_AFTER_STORAGE.filter((k) => !(k in card.summary))
  if (missing.length > 0) {
    notes.push({
      severity: 'caution',
      message: `This scorecard is missing summary keys that the current harness emits unconditionally (${missing.join(', ')}). It therefore could not have been produced by the code on the current default branch, and re-running today would not yield a document of the same shape.`,
      source: 'backend/evals/run.py, backend/evals/metrics.py',
    })
  }

  if (card.runner === 'proto-hybrid-judge-events') {
    notes.push({
      severity: 'warning',
      message:
        'This runner name belongs to the corrected default prototype pipeline, but the repository’s own regression gate maps this runner key to the historical proto-s0-legacy-v1 adapter, whose protocol reproduces known defects (per-reader event discovery, uncapped forced delivery that ignores reader exclusions). Treat this run as evidence about the historical S0 protocol, not as validation of the corrected default pipeline.',
      source: 'backend/tests/test_eval_gate.py, backend/evals/legacy_s0.py',
    })
  }

  notes.push({
    severity: 'caution',
    message:
      'A reported cache-miss total of zero does not prove offline replay: the harness increments its miss counter only on the live network path, so the counter is structurally zero whenever offline mode is active. Execution mode is therefore reported as unknown unless the scorecard states it.',
    source: 'backend/evals/llm_cache.py',
  })

  notes.push({
    severity: 'info',
    message: `Stored in the repository tree at ${relPath}.`,
    source: relPath,
  })

  return notes
}

/* -------------------------------------------------------- baseline check --- */

/**
 * Detect a baseline whose stored per-snapshot thresholds disagree with the
 * committed run scorecard for the same runner and snapshot. Computed rather
 * than hardcoded so it keeps telling the truth if the data changes.
 */
function baselineIntegrity(
  card: Scorecard,
  runsByRunnerSnapshot: Map<string, Scorecard>,
): { is_baseline: boolean; snapshot_baseline_keys: string[]; disagrees_with_run: string[] } {
  const isBaseline = card.snapshot_baselines !== undefined || card.baseline_created_at !== undefined
  if (!isBaseline || card.snapshot_baselines === undefined) {
    return { is_baseline: isBaseline, snapshot_baseline_keys: [], disagrees_with_run: [] }
  }

  const keys = Object.keys(card.snapshot_baselines).sort()
  const disagrees: string[] = []

  for (const snapshot of keys) {
    const run = runsByRunnerSnapshot.get(`${card.runner}::${snapshot}`)
    if (run === undefined) continue
    const stored = card.snapshot_baselines[snapshot]
    if (stored === undefined) continue
    const runSummary = run.summary

    for (const [key, value] of Object.entries(stored)) {
      if (typeof value !== 'number') continue
      const other = runSummary[key]
      if (typeof other !== 'number') continue
      if (Math.abs(value - other) > 1e-9) {
        disagrees.push(snapshot)
        break
      }
    }
  }

  return { is_baseline: true, snapshot_baseline_keys: keys, disagrees_with_run: [...new Set(disagrees)] }
}

/* ------------------------------------------------------------------ main --- */

function sha256(text: string): string {
  return createHash('sha256').update(text).digest('hex')
}

function main(): void {
  if (!existsSync(RESULTS)) {
    throw new Error(`No scorecards found at ${RESULTS}`)
  }

  // The revision of the evidence, not of HEAD.
  //
  // HEAD is the obvious choice and it is wrong: the export is committed, so
  // committing it changes HEAD, which changes the next export, which never
  // matches the commit -- CI's staleness check would fail forever. Anchoring to
  // the evidence is stable under every commit that does not add new scorecards,
  // and says the more useful thing anyway: which evidence this was built from.
  const artifactRevision = git('log', '-1', '--format=%h', '--', ...EVIDENCE_PATHS) ?? UNKNOWN
  const builtAt =
    git('log', '-1', '--format=%cI', '--', ...EVIDENCE_PATHS) ?? new Date().toISOString()
  const snapshotManifest = loadSnapshotManifest()
  const labelCache = new Map<string, ReturnType<typeof labelProvenance>>()

  const files = readdirSync(RESULTS).filter((f) => f.endsWith('.json')).sort()
  if (files.length === 0) throw new Error(`No .json scorecards in ${RESULTS}`)

  // First pass: parse everything, so baseline integrity can compare against runs.
  const parsed: { file: string; card: Scorecard }[] = []
  for (const file of files) {
    const raw: unknown = JSON.parse(readFileSync(join(RESULTS, file), 'utf8'))
    const result = parseScorecard(raw)
    if (!result.ok) {
      throw new Error(`Invalid scorecard ${file}:\n  ${result.issues.join('\n  ')}`)
    }
    parsed.push({ file, card: result.value })
  }

  const runsByRunnerSnapshot = new Map<string, Scorecard>()
  for (const { card } of parsed) {
    const isBaseline = card.snapshot_baselines !== undefined || card.baseline_created_at !== undefined
    if (!isBaseline) runsByRunnerSnapshot.set(`${card.runner}::${card.snapshot}`, card)
  }

  const entries: ManifestEntry[] = []
  const artifacts: { name: string; json: string }[] = []

  for (const { file, card } of parsed) {
    const relPath = `backend/evals/results/${file}`
    const reachable = card.git_sha === '' ? UNKNOWN : isAncestor(card.git_sha)
    const integrity = baselineIntegrity(card, runsByRunnerSnapshot)

    if (!labelCache.has(card.snapshot)) {
      labelCache.set(card.snapshot, labelProvenance(card.snapshot))
    }
    const labels = labelCache.get(card.snapshot) ?? null

    const notes = buildNotes(card, relPath, reachable)
    let timestampsTrustworthy = true
    if (integrity.disagrees_with_run.length > 0) {
      timestampsTrustworthy = false
      notes.unshift({
        severity: 'warning',
        message: `This baseline's stored thresholds for ${integrity.disagrees_with_run.join(', ')} disagree with the committed run scorecard for the same runner and snapshot, which means the file was re-recorded after the timestamps embedded in it. Its embedded created_at must not be read as the date of the numbers it carries.`,
        source: relPath,
      })
    }

    const meta = card.meta as Record<string, unknown>
    const models = new Set<string>()
    for (const persona of Object.values(card.per_persona)) {
      const pm = persona.meta as Record<string, unknown>
      for (const field of ['model', 'embedding_model'] as const) {
        if (typeof pm[field] === 'string') models.add(pm[field] as string)
      }
    }

    const { metrics, lossByStage } = flattenSummary(card.summary)
    const personas = Object.entries(card.per_persona)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, persona]) => toPersonaArtifact(key, persona, card.runner))

    const runId = `${card.runner}__${card.snapshot}__${card.git_sha}${integrity.is_baseline ? '__baseline' : ''}`

    const artifact: Artifact = {
      artifact_version: ARTIFACT_VERSION,
      run_id: runId,
      origin: 'imported-historical',
      provenance: {
        eval_revision: card.git_sha === '' ? UNKNOWN : card.git_sha,
        eval_revision_reachable: reachable,
        artifact_revision: artifactRevision,
        artifact_built_at: builtAt,
        storage_revision: storageRevision(relPath),
        run_created_at: card.created_at === '' ? UNKNOWN : card.created_at,
        timestamps_trustworthy: timestampsTrustworthy,
        runner: card.runner,
        runner_cli_arg: RUNNER_CLI_ARG[card.runner] ?? UNKNOWN,
        protocol: typeof meta.protocol === 'string' ? meta.protocol : UNKNOWN,
        protocol_source: typeof meta.protocol === 'string' ? 'recorded' : 'absent-in-source',
        k: card.k,
        execution_mode: UNKNOWN,
        execution_mode_basis:
          'The scorecard does not record an execution mode. A zero cache-miss total cannot stand in for one, because the harness only counts misses on the live network path.',
        needles: typeof meta.needles === 'boolean' ? meta.needles : UNKNOWN,
        quiet: typeof meta.quiet === 'boolean' ? meta.quiet : UNKNOWN,
        models: [...models].sort(),
        cache_keys: card.cache_keys.length,
        snapshot: snapshotProvenance(card.snapshot, snapshotManifest),
        labels,
        notes,
      },
      summary: metrics,
      summary_loss_by_stage: lossByStage,
      personas,
      baseline: integrity,
    }

    const validated = parseArtifact(artifact)
    if (!validated.ok) {
      throw new Error(`Export produced an invalid artifact for ${file}:\n  ${validated.issues.join('\n  ')}`)
    }

    const json = `${JSON.stringify(validated.value, null, 1)}\n`
    const name = `${runId}.json`
    artifacts.push({ name, json })
    entries.push({
      run_id: runId,
      file: name,
      runner: card.runner,
      snapshot: card.snapshot,
      protocol: artifact.provenance.protocol,
      k: card.k,
      origin: 'imported-historical',
      eval_revision: artifact.provenance.eval_revision,
      is_baseline: integrity.is_baseline,
      personas: personas.length,
      sha256: sha256(json),
      bytes: Buffer.byteLength(json),
    })
  }

  const manifest: Manifest = {
    manifest_version: ARTIFACT_VERSION,
    artifact_revision: artifactRevision,
    built_at: builtAt,
    complete: true,
    entries: entries.sort((a, b) => a.run_id.localeCompare(b.run_id)),
    snapshots: [...snapshotManifest.keys()].sort().map((n) => snapshotProvenance(n, snapshotManifest)),
    notes: [
      {
        severity: 'info',
        message: `Exported ${entries.length} artifacts from backend/evals/results/ at revision ${artifactRevision}. Every entry is an import of a historical scorecard, not a run executed by this export.`,
        source: 'web/scripts/export-artifacts.ts',
      },
    ],
  }

  const validatedManifest = parseManifest(manifest)
  if (!validatedManifest.ok) {
    throw new Error(`Export produced an invalid manifest:\n  ${validatedManifest.issues.join('\n  ')}`)
  }

  if (CHECK_ONLY) {
    console.log(`validated ${entries.length} artifacts + manifest (no files written)`)
    return
  }

  // Write artifacts first, manifest last: the manifest asserts completeness, so
  // it must not exist until everything it lists is on disk and validated.
  rmSync(OUT, { recursive: true, force: true })
  mkdirSync(OUT, { recursive: true })
  for (const { name, json } of artifacts) {
    writeFileSync(join(OUT, name), json, 'utf8')
  }
  writeFileSync(join(OUT, 'manifest.json'), `${JSON.stringify(validatedManifest.value, null, 1)}\n`, 'utf8')

  console.log(`wrote ${entries.length} artifacts + manifest.json to web/public/artifacts/`)
  for (const entry of entries) {
    console.log(`  ${entry.run_id}  (${entry.personas} personas, ${entry.bytes} bytes)`)
  }
}

main()
