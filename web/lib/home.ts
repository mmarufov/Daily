/**
 * Everything the homepage shows, read from stored runs.
 *
 * Each figure on `/` comes out of this module, and each value here is read
 * from a committed file rather than typed in. The run is pinned rather than
 * taken from `defaultEntry`, because the homepage tells one story about one
 * run, and a new export must not quietly change the numbers under the
 * sentences that describe them. When a source is missing the field is null
 * and the section that needs it does not render; nothing is filled in.
 *
 *   artifact   public/artifacts/prod-llm__2026-09-02__47edb50.json
 *   guard      public/experiments/count-guard-prod-llm-2026-09-02.json
 *              (the same runner and snapshot replayed with the count guard,
 *              revision 3b11a3c, 2026-09-21)
 *   defect     lab-evidence/backend/lab/cases/observed.json, the case suite
 *   recorded   public/runs/wrun_01M3WXWPKMF3H8Q66KZA56MZCV.json
 *   lab        public/lab-artifacts/manifest.json
 */

import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

import { parseArtifact, type Artifact } from './artifact'
import { loadIndex } from './data'
import { loadLabIndex } from './lab/data'
import { loadCasesForRun } from './lab/case-loader'
import type { RunStatusBody } from './lab/live'
import { personaName } from './personas'

export const HOME_RUN = 'prod-llm__2026-09-02__47edb50'
export const HOME_FIXTURE = 'ray'
export const DEFECT_CASE = 'observed-2026-09-02-040'
export const RECORDED_RUN = 'wrun_01M3WXWPKMF3H8Q66KZA56MZCV'
const GUARD_FILE = 'count-guard-prod-llm-2026-09-02.json'

const PUBLIC = join(process.cwd(), 'public')

export interface SieveStepData {
  readonly stage: string
  readonly label: string
  readonly explanation: string | null
  readonly survivors: number
  readonly lost_entering_stage: number
  readonly pass_rate: number | null
  readonly absent: boolean
}

export interface FixtureRecall {
  readonly key: string
  readonly name: string
  /** Capped recall@k: needed stories delivered. */
  readonly delivered: number
  /** Needed stories that reached the scorer at all. */
  readonly reached: number
}

export interface MissStage {
  readonly key: string
  readonly label: string
  readonly note: string
  readonly count: number
}

export interface DefectBatch {
  readonly caseId: string
  readonly snapshot: string
  readonly articles: readonly { readonly title: string; readonly source: string }[]
  /** Every verdict up to the first of the repeated run, in order. */
  readonly distinct: readonly string[]
  /** The sentence the response then repeated, and how many times. */
  readonly loop: { readonly text: string; readonly start: number; readonly count: number }
  readonly returned: number
  readonly finishReason: string | null
  readonly completionTokens: number | null
}

export interface GuardMetric {
  readonly key: string
  readonly label: string
  readonly before: number
  readonly after: number
  /** True when a higher value is worse. */
  readonly lowerIsBetter: boolean
}

export interface RecordedRun {
  readonly preset: string
  readonly capturedFrom: string
  readonly body: RunStatusBody
}

export interface HomeEvidence {
  readonly run: { readonly id: string; readonly snapshot: string; readonly sha256: string; readonly k: number } | null
  readonly sieve: { readonly fixture: string; readonly name: string; readonly steps: readonly SieveStepData[] } | null
  readonly ladder: { readonly reached: number; readonly delivered: number; readonly fixtures: readonly FixtureRecall[] } | null
  readonly misses: { readonly total: number; readonly stages: readonly MissStage[] } | null
  readonly defect: DefectBatch | null
  readonly guard: { readonly revision: string; readonly date: string; readonly metrics: readonly GuardMetric[] } | null
  readonly recorded: RecordedRun | null
  readonly lab: {
    readonly specHash: string
    readonly runs: number
    readonly accepted: number
    readonly rejected: number
    readonly recordedCases: number
    readonly faultCases: number
  } | null
  readonly corpus: { readonly labels: number; readonly snapshots: number } | null
}

/** Must-see losses, in pipeline order. The keys are the scorecard's own. */
const MISS_ORDER: readonly { key: string; label: string; note: string }[] = [
  { key: 'lookback', label: 'Recency window', note: 'Only the newest 300 rows are loaded. Nothing has judged relevance yet.' },
  { key: 'prefilter:cap', label: 'Prefilter cap', note: 'A keyword pass keeps 100 for the model to score.' },
  { key: 'blended', label: 'Score blend', note: 'Relevance, recency and source weights combined.' },
  { key: 'rank', label: 'Final rank', note: 'Cut to the twelve slots of the edition.' },
]

const GUARD_METRICS: readonly { key: string; label: string; lowerIsBetter: boolean }[] = [
  { key: 'recall_at_k_mean', label: 'Needed stories delivered', lowerIsBetter: false },
  { key: 'never_rate_mean', label: 'Unwanted stories delivered', lowerIsBetter: true },
  { key: 'recall_at_retrieval_mean', label: 'Needed stories that reached the scorer', lowerIsBetter: false },
]

async function readJson(path: string): Promise<unknown> {
  return JSON.parse(await readFile(path, 'utf8')) as unknown
}

async function loadRun(): Promise<Artifact | null> {
  try {
    const parsed = parseArtifact(await readJson(join(PUBLIC, 'artifacts', `${HOME_RUN}.json`)))
    return parsed.ok ? parsed.value : null
  } catch {
    return null
  }
}

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

async function loadDefect(): Promise<DefectBatch | null> {
  try {
    const cases = await loadCasesForRun()
    const kase = cases.find((c) => c.case_id === DEFECT_CASE)
    if (kase === undefined) return null
    const content = (kase.response as { content?: unknown }).content
    if (typeof content !== 'string') return null
    const parsed = JSON.parse(content) as { results?: { reason?: unknown }[] }
    const reasons = (parsed.results ?? []).map((r) => (typeof r.reason === 'string' ? r.reason : ''))
    if (reasons.length === 0) return null

    // The longest run of one identical sentence, found rather than assumed.
    let best = { start: 0, count: 0 }
    for (let i = 0; i < reasons.length; ) {
      let j = i
      while (j + 1 < reasons.length && reasons[j + 1] === reasons[i]) j += 1
      if (j - i + 1 > best.count) best = { start: i, count: j - i + 1 }
      i = j + 1
    }

    return {
      caseId: kase.case_id,
      snapshot: kase.snapshot ?? '',
      articles: kase.articles.map((a) => ({ title: a.title, source: a.source ?? '' })),
      distinct: reasons.slice(0, best.start),
      loop: { text: reasons[best.start] ?? '', start: best.start, count: best.count },
      returned: reasons.length,
      finishReason:
        typeof (kase.response as { finish_reason?: unknown }).finish_reason === 'string'
          ? ((kase.response as { finish_reason: string }).finish_reason)
          : null,
      completionTokens: kase.completion_tokens ?? null,
    }
  } catch {
    return null
  }
}

async function loadGuard(artifact: Artifact | null): Promise<HomeEvidence['guard']> {
  if (artifact === null) return null
  try {
    const raw = (await readJson(join(PUBLIC, 'experiments', GUARD_FILE))) as {
      git_sha?: unknown
      created_at?: unknown
      runner?: unknown
      snapshot?: unknown
      k?: unknown
      summary?: Record<string, unknown>
    }
    // The comparison only means something on identical inputs.
    if (raw.runner !== 'prod-llm' || raw.snapshot !== artifact.provenance.snapshot.name || raw.k !== artifact.provenance.k) {
      return null
    }
    const metrics: GuardMetric[] = []
    for (const m of GUARD_METRICS) {
      const before = num(artifact.summary[m.key])
      const after = num(raw.summary?.[m.key])
      if (before === null || after === null) return null
      metrics.push({ key: m.key, label: m.label, before, after, lowerIsBetter: m.lowerIsBetter })
    }
    return {
      revision: typeof raw.git_sha === 'string' ? raw.git_sha : 'unknown',
      date: typeof raw.created_at === 'string' ? raw.created_at.slice(0, 10) : 'unknown',
      metrics,
    }
  } catch {
    return null
  }
}

async function loadRecorded(): Promise<RecordedRun | null> {
  try {
    const raw = (await readJson(join(PUBLIC, 'runs', `${RECORDED_RUN}.json`))) as {
      preset?: unknown
      captured_from?: unknown
      response?: RunStatusBody
    }
    const body = raw.response
    if (body === undefined || body.run_id !== RECORDED_RUN || body.outcome === null || !body.finished) return null
    return {
      preset: typeof raw.preset === 'string' ? raw.preset : 'unknown',
      capturedFrom: typeof raw.captured_from === 'string' ? raw.captured_from : '',
      body,
    }
  } catch {
    return null
  }
}

async function loadCorpus(): Promise<HomeEvidence['corpus']> {
  try {
    const index = await loadIndex()
    const snapshots = index.manifest?.snapshots ?? []
    let labels = 0
    for (const snap of snapshots) {
      const entry = index.entries.find((e) => e.snapshot === snap.name && !e.is_baseline)
      if (entry === undefined) return null
      const parsed = parseArtifact(await readJson(join(PUBLIC, 'artifacts', entry.file)))
      if (!parsed.ok) return null
      const rows = parsed.value.provenance.labels?.rows
      if (typeof rows !== 'number') return null
      labels += rows
    }
    return snapshots.length > 0 ? { labels, snapshots: snapshots.length } : null
  } catch {
    return null
  }
}

async function loadLab(): Promise<HomeEvidence['lab']> {
  try {
    const { manifest } = await loadLabIndex()
    if (manifest === null) return null
    const cases = await loadCasesForRun()
    return {
      specHash: manifest.spec_hash,
      runs: manifest.entries.length,
      accepted: manifest.entries.filter((e) => e.verdict === 'accepted-for-review').length,
      rejected: manifest.entries.filter((e) => e.verdict === 'rejected').length,
      recordedCases: cases.filter((c) => c.origin === 'recorded-replay').length,
      faultCases: cases.filter((c) => c.origin === 'fault-injection').length,
    }
  } catch {
    return null
  }
}

export async function loadHomeEvidence(): Promise<HomeEvidence> {
  const artifact = await loadRun()
  const [defect, guard, recorded, lab, corpus] = await Promise.all([
    loadDefect(),
    loadGuard(artifact),
    loadRecorded(),
    loadLab(),
    loadCorpus(),
  ])

  const lead = artifact?.personas.find((p) => p.key === HOME_FIXTURE)
  const reached = num(artifact?.summary.recall_at_retrieval_mean)
  const delivered = num(artifact?.summary.recall_at_k_mean)
  const fixtures: FixtureRecall[] = []
  for (const p of artifact?.personas ?? []) {
    const d = num(p.metrics.recall_at_k)
    const r = num(p.metrics.recall_at_retrieval)
    if (d === null || r === null) continue
    fixtures.push({ key: p.key, name: personaName(p.key), delivered: d, reached: r })
  }

  const loss = artifact?.summary_loss_by_stage ?? {}
  const known = new Set(MISS_ORDER.map((m) => m.key))
  // Every attributed miss must land in a known stage, or the figure would
  // silently drop some. If the data grows a stage, the section goes away
  // rather than misstating the total.
  const missesComplete = Object.keys(loss).every((k) => known.has(k))
  const stages = MISS_ORDER.map((m) => ({ ...m, count: loss[m.key] ?? 0 }))

  return {
    run:
      artifact === null
        ? null
        : {
            id: artifact.run_id,
            snapshot: artifact.provenance.snapshot.name,
            sha256: artifact.provenance.snapshot.sha256 ?? '',
            k: artifact.provenance.k,
          },
    sieve: lead === undefined ? null : { fixture: lead.key, name: personaName(lead.key), steps: lead.funnel },
    ladder:
      reached === null || delivered === null || fixtures.length === 0 ? null : { reached, delivered, fixtures },
    misses:
      artifact === null || !missesComplete
        ? null
        : { total: stages.reduce((s, m) => s + m.count, 0), stages },
    defect,
    guard,
    recorded,
    lab,
    corpus,
  }
}
