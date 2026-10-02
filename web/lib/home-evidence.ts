/** The homepage is a reading of named records, never a selection of the latest run. */
import type { OffendingCase } from '@/components/LabOffendingCase'
import type { SieveFixture } from '@/components/Sieve'

import type { Artifact, Story } from './artifact'
import { findEntry, loadArtifact, loadIndex } from './data'
import type { DemoBundle, DemoStory } from './demo'
import { loadDemo } from './demo-data'
import { loadGuardExperimentResult, type GuardExperiment } from './guard-experiment'
import type { LabRun } from './lab/artifact'
import { loadLabIndex, loadLabRun, loadOffendingCase } from './lab/data'
import { explorerHref, type ExplorerUrl } from './url-state'

export const HOME_RUN_ID = 'prod-llm__2026-09-02__47edb50' as const
export const HOME_RECORDED_RUN_FILE = 'count-guard-v1-clean.json' as const
export const HOME_RECORDED_RUN_HREF = '/lab/count-guard-v1-clean' as const

const LOSS_STAGES = [
  {
    key: 'lookback',
    label: 'Lookback',
    beforeScorer: true,
    explanation: 'The retrieval window never loaded these stories. A better scorer cannot recover an article it never receives.',
  },
  {
    key: 'prefilter:cap',
    label: 'Prefilter cap',
    beforeScorer: true,
    explanation: 'These stories were cut by the candidate cap before the relevance scorer saw them.',
  },
  {
    key: 'blended',
    label: 'Scoring',
    beforeScorer: false,
    explanation: 'These stories reached scoring and were dropped at the blended-score stage. The recorded rationale is a diagnostic, not proof that the verdict belongs to that article.',
  },
  {
    key: 'rank',
    label: 'Rank cutoff',
    beforeScorer: false,
    explanation: 'These stories missed the top-12 ranking cutoff. Their trace retains the outcome label written by the historical export.',
  },
] as const

export interface RetrievalLossSegment {
  readonly key: (typeof LOSS_STAGES)[number]['key']
  readonly label: string
  readonly count: number
  readonly beforeScorer: boolean
  readonly explanation: string
  readonly example: {
    readonly persona: string
    readonly story: Story
    readonly href: ExplorerUrl
  } | null
}

export interface RetrievalLossData {
  readonly runId: string
  readonly snapshot: string
  readonly fixtureCount: number
  readonly total: number
  readonly beforeScorer: number
  readonly unit: 'fixture/article pairs'
  readonly segments: readonly RetrievalLossSegment[]
}

export interface HomeEvidence {
  readonly editionPreview: EditionPreviewData | null
  readonly artifact: Artifact | null
  readonly fixtures: readonly SieveFixture[]
  readonly offendingCase: OffendingCase | null
  readonly guardExperiment: GuardExperiment | null
  readonly losses: RetrievalLossData | null
  readonly lab: {
    readonly caseCount: number | null
    readonly recordedCaseCount: number | null
    readonly faultCount: number | null
    readonly publishedRuns: number | null
    readonly sandboxRuns: number | null
    readonly specHash: string | null
  }
  readonly recordedRun: LabRun | null
  readonly recordedRunHref: typeof HOME_RECORDED_RUN_HREF
  readonly issues: readonly string[]
}

export interface EditionPreviewData {
  readonly persona: 'ray'
  readonly frozenAt: string
  readonly stories: readonly DemoStory[]
}

/** The preview is a slice of the same recording, never a substitute edition. */
export function deriveEditionPreview(bundle: DemoBundle, artifact: Artifact | null): EditionPreviewData | null {
  if (artifact === null || bundle.run_id !== HOME_RUN_ID || bundle.run_id !== artifact.run_id ||
      bundle.snapshot !== artifact.provenance.snapshot.name ||
      artifact.provenance.snapshot.sha256 === 'unknown' ||
      bundle.snapshot_sha256 !== artifact.provenance.snapshot.sha256 ||
      !Number.isFinite(Date.parse(bundle.frozen_at)) ||
      Date.parse(bundle.frozen_at) !== Date.parse(artifact.provenance.snapshot.frozen_now)) return null
  const edition = bundle.editions.find((item) => item.persona === 'ray')
  if (!edition || edition.stories.length < 3) return null
  const stories = edition.stories.slice(0, 3)
  if (stories.some((story, index) => story.position !== index + 1)) return null
  return { persona: 'ray', frozenAt: bundle.frozen_at, stories }
}

/**
 * Keep three different units separate: candidate marks, labelled losses, and
 * Lab cases. A loss is a fixture/article pair, so one article can occur twice.
 * The historical export omits labels on loss rows; its loss_by_stage attribution
 * and matching trace are the evidence, not a fabricated per-story label.
 */
export function deriveRetrievalLoss(artifact: Artifact): RetrievalLossData | null {
  if (artifact.run_id !== HOME_RUN_ID || artifact.personas.length === 0) return null
  if (artifact.personas.some((persona) => !persona.trace_available)) return null
  const known = new Set<string>(LOSS_STAGES.map((stage) => stage.key))
  if (Object.keys(artifact.summary_loss_by_stage).some((key) => !known.has(key))) return null

  const segments: RetrievalLossSegment[] = []
  for (const stage of LOSS_STAGES) {
    const count = artifact.summary_loss_by_stage[stage.key]
    // Missing means unavailable. It must not become a zero-length segment.
    if (count === undefined || !Number.isSafeInteger(count) || count < 0) return null
    const attributed = artifact.personas.reduce(
      (total, persona) => total + (persona.loss_by_stage[stage.key] ?? 0),
      0,
    )
    if (attributed !== count) return null

    const traces = artifact.personas.flatMap((persona) =>
      persona.stories
        .filter((story) => story.dropped_at === stage.key)
        .map((story) => ({ persona: persona.key, story })),
    )
    if (traces.length !== count) return null
    const example = traces[0]
    segments.push({
      ...stage,
      count,
      example: example === undefined ? null : {
        ...example,
        href: explorerHref({ run: artifact.run_id }, {
          persona: example.persona,
          view: 'stories',
          outcome: example.story.outcome,
          story: example.story.id,
        }),
      },
    })
  }

  return {
    runId: artifact.run_id,
    snapshot: artifact.provenance.snapshot.name,
    fixtureCount: artifact.personas.length,
    total: segments.reduce((total, segment) => total + segment.count, 0),
    beforeScorer: segments.filter((segment) => segment.beforeScorer)
      .reduce((total, segment) => total + segment.count, 0),
    unit: 'fixture/article pairs',
    segments,
  }
}

function settledValue<T>(
  result: PromiseSettledResult<T>,
  name: string,
  issues: string[],
): T | null {
  if (result.status === 'fulfilled') return result.value
  issues.push(`${name}: ${result.reason instanceof Error ? result.reason.message : String(result.reason)}`)
  return null
}

export async function loadHomeEvidence(): Promise<HomeEvidence> {
  const issues: string[] = []
  const results = await Promise.allSettled([
    loadIndex(),
    loadLabIndex(),
    loadLabRun(HOME_RECORDED_RUN_FILE),
    loadOffendingCase(),
    loadGuardExperimentResult(),
    loadDemo(),
  ])
  const index = settledValue(results[0], 'Evaluation index', issues)
  const labIndex = settledValue(results[1], 'Lab index', issues)
  let recordedRun = settledValue(results[2], 'Recorded parser run', issues)
  const offendingCase = settledValue(results[3], 'Recorded batch', issues)
  const guardResult = settledValue(results[4], 'Guard experiment', issues)
  const demo = settledValue(results[5], 'Recorded edition', issues)

  for (const error of index?.errors ?? []) issues.push(`${error.where}: ${error.issues.join('; ')}`)
  issues.push(...(labIndex?.issues ?? []))
  if (offendingCase === null) issues.push('The recorded offending batch is unavailable.')
  if (guardResult?.ok === false) issues.push(...guardResult.issues.map((issue) => `Guard experiment: ${issue}`))
  let guardExperiment = guardResult?.ok === true ? guardResult.value : null

  let artifact: Artifact | null = null
  const entry = findEntry(index?.entries ?? [], HOME_RUN_ID)
  if (entry === undefined) {
    issues.push(`The pinned evaluation ${HOME_RUN_ID} is unavailable.`)
  } else {
    try {
      const loaded = await loadArtifact(entry)
      if (!loaded.ok) issues.push(...loaded.error.issues)
      else if (loaded.artifact.run_id !== HOME_RUN_ID) {
        issues.push('The evaluation artifact does not match its pinned run id.')
      } else artifact = loaded.artifact
    } catch (error) {
      issues.push(`Pinned evaluation: ${error instanceof Error ? error.message : String(error)}`)
    }
  }

  if (artifact !== null && guardExperiment !== null) {
    const original = guardExperiment.original
    const metrics = ['recall_at_k_mean', 'never_rate_mean', 'recall_at_retrieval_mean', 'calls_total', 'cache_misses_total'] as const
    if (original.source.recorded_git_sha !== artifact.provenance.eval_revision ||
        metrics.some((key) => original.summary[key] !== artifact.summary[key])) {
      issues.push('The guard comparison does not match the pinned original scorecard.')
      guardExperiment = null
    }
  }

  if (recordedRun !== null &&
      (recordedRun.run_id !== 'article-to-verdict-association__count-guard-v1__2c2fb884ebdf__008af826__clean' ||
       recordedRun.candidate.candidate_id !== 'count-guard-v1')) {
    issues.push('The recorded parser artifact does not match the pinned candidate.')
    recordedRun = null
  }
  if (recordedRun === null) issues.push(`The recorded parser run ${HOME_RECORDED_RUN_FILE} is unavailable.`)

  let recordedCaseCount: number | null = null
  let faultCount: number | null = null
  if (recordedRun !== null) {
    const suites = recordedRun.provenance.case_suites
    const observed = suites.filter((suite) => suite.group === 'observed')
    const synthetic = suites.filter((suite) => suite.group === 'synthetic')
    const observedCount = observed.reduce((total, suite) => total + suite.n_cases, 0)
    const syntheticCount = synthetic.reduce((total, suite) => total + suite.n_cases, 0)
    if (observed.length === 1 && synthetic.length === 1 &&
        observedCount === recordedRun.outcomes.filter((outcome) => outcome.group === 'observed').length &&
        syntheticCount === recordedRun.outcomes.filter((outcome) => outcome.group === 'synthetic').length) {
      recordedCaseCount = observedCount
      faultCount = syntheticCount
    } else issues.push('Recorded case counts do not reconcile with the case-suite provenance.')
  }

  const manifest = labIndex?.manifest ?? null
  const losses = artifact === null ? null : deriveRetrievalLoss(artifact)
  if (artifact !== null && losses === null) issues.push('Retrieval-loss counts and recorded story traces do not reconcile.')
  const editionPreview = demo?.ok === true ? deriveEditionPreview(demo.bundle, artifact) : null
  if (editionPreview === null) issues.push('The recorded Ray edition is unavailable or does not match the pinned recording.')

  return {
    editionPreview,
    artifact,
    fixtures: artifact?.personas.map((persona) => ({ key: persona.key, steps: persona.funnel })) ?? [],
    offendingCase,
    guardExperiment,
    losses,
    lab: {
      caseCount: recordedCaseCount === null || faultCount === null ? null : recordedCaseCount + faultCount,
      recordedCaseCount,
      faultCount,
      publishedRuns: manifest?.entries.length ?? null,
      sandboxRuns: manifest?.entries.filter((run) => run.runner === 'vercel-sandbox').length ?? null,
      specHash: manifest?.spec_hash ?? null,
    },
    recordedRun,
    recordedRunHref: HOME_RECORDED_RUN_HREF,
    issues,
  }
}
