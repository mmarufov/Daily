import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { deriveRetrievalLoss, HOME_RUN_ID, loadHomeEvidence } from '../../lib/home-evidence'
import { parseGuardExperiment } from '../../lib/guard-experiment'
import type { Artifact } from '../../lib/artifact'
import { GuardExperiment } from '../../components/GuardExperiment'
import { RetrievalLoss } from '../../components/RetrievalLoss'
import { HeroSieve } from '../../components/HeroSieve'
import { EditionPreview } from '../../components/EditionPreview'
import { deriveEditionPreview } from '../../lib/home-evidence'
import type { DemoBundle } from '../../lib/demo'

const artifact = JSON.parse(readFileSync(`public/artifacts/${HOME_RUN_ID}.json`, 'utf8')) as Artifact
const experiment = JSON.parse(readFileSync('public/experiments/batch-alignment.json', 'utf8'))
const edition = JSON.parse(readFileSync('public/demo/editions.json', 'utf8')) as DemoBundle

describe('the pinned homepage narrative', () => {
  it('reconciles independent populations with their source records', async () => {
    const home = await loadHomeEvidence()
    expect(home.issues).toEqual([])
    expect(home.editionPreview?.stories).toEqual(edition.editions.find(item => item.persona === 'ray')!.stories.slice(0, 3))
    expect(home.losses?.segments.map(s => s.count)).toEqual([75, 9, 9, 4])
    expect(home.losses?.beforeScorer).toBe(84)
    expect(home.losses?.unit).toBe('fixture/article pairs')
    expect(home.lab).toMatchObject({ caseCount: 64, faultCount: 22, publishedRuns: 39, sandboxRuns: 9 })
    expect(home.recordedRun?.counts).toMatchObject({ correct: 48, 'not-applicable': 12 })
    expect(home.runStory).toMatchObject({
      runId: 'wrun_01M3WXWPKMF3H8Q66KZA56MZCV',
      specVersion: 2,
      counts: { total: 64, correct: 48, failed: 4, notApplicable: 12, faultInjected: 22 },
    })
    for (const segment of home.losses!.segments) {
      const example = segment.example!
      const query = example.href.query
      expect(query.run).toBe(HOME_RUN_ID)
      expect(query.outcome).toBe(example.story.outcome)
      expect(example.story.dropped_at).toBe(segment.key)
    }
  })
  it.each(['missing count', 'mismatched total', 'missing trace', 'different recording'])('rejects %s instead of substituting a plausible story', (failure) => {
    const changed = JSON.parse(JSON.stringify(artifact))
    if (failure === 'missing count') delete changed.summary_loss_by_stage.lookback
    if (failure === 'mismatched total') changed.summary_loss_by_stage.lookback = 74
    if (failure === 'missing trace') changed.personas[0]!.trace_available = false
    if (failure === 'different recording') changed.run_id = 'different'
    expect(deriveRetrievalLoss(changed)).toBeNull()
  })
  it('renders explicit unavailable states rather than invented metrics', () => {
    expect(renderToStaticMarkup(createElement(GuardExperiment, { experiment: null }))).toContain('unavailable')
    expect(renderToStaticMarkup(createElement(RetrievalLoss, { data: null }))).toContain('unavailable')
    expect(renderToStaticMarkup(createElement(HeroSieve, { fixtures: [], runId: HOME_RUN_ID, snapshot: '' }))).toContain('unavailable')
    expect(renderToStaticMarkup(createElement(EditionPreview, { edition: null }))).toContain('recorded Ray edition is unavailable')
  })
})

describe('the recorded edition introduction', () => {
  it.each(['run', 'snapshot', 'hash', 'date', 'fixture', 'too short', 'order'])('rejects a mismatched %s without silently selecting another edition', (failure) => {
    const changed = structuredClone(edition)
    if (failure === 'run') changed.run_id = 'other-run'
    if (failure === 'snapshot') changed.snapshot = '2026-08-31'
    if (failure === 'hash') changed.snapshot_sha256 = 'different'
    if (failure === 'date') changed.frozen_at = '2026-09-03T00:00:00Z'
    if (failure === 'fixture') changed.editions = changed.editions.filter(item => item.persona !== 'ray')
    const ray = changed.editions.find(item => item.persona === 'ray')
    if (failure === 'too short') ray!.stories = ray!.stories.slice(0, 2)
    if (failure === 'order') ray!.stories.reverse()
    expect(deriveEditionPreview(changed, artifact)).toBeNull()
  })
  it('keeps authored test stories visibly distinguished and preserves their headline', () => {
    const preview = deriveEditionPreview(edition, artifact)!
    const story = { ...preview.stories[0]!, synthetic: true }
    const html = renderToStaticMarkup(createElement(EditionPreview, { edition: { ...preview, stories: [story] } }))
    expect(html).toContain('Authored test story')
    expect(html).toContain(story.headline)
    expect(html).toContain('Recorded edition · September 2, 2026')
    expect(deriveEditionPreview(edition, null)).toBeNull()
  })
})
describe('historical experiment provenance', () => {
  it('keeps the recorded results and their historical limits explicit', () => {
    const parsed = parseGuardExperiment(experiment)
    expect(parsed.ok).toBe(true)
    expect(experiment.original.summary.recall_at_k_mean).toBe(0.2207)
    expect(experiment.guard.summary.recall_at_k_mean).toBe(0.1866)
    expect(experiment.guard.summary.never_rate_mean).toBe(0.425)
    expect(experiment.scope).toBe('historical-working-tree-experiment')
    expect(experiment.historical_test_result).toMatchObject({ failed: 6, baseline_re_recorded: false })
    expect(experiment.guard.revision_is_guard_commit).toBe(false)
    expect(experiment.guard.implementation_sha256).toBeNull()
  })
  it('identifies committed reference inputs and the original scorecard by their actual bytes', () => {
    const files = [experiment.original.source, ...experiment.input_provenance.reference_files] as {path: string; sha256: string}[]
    for (const file of files) {
      const hash = createHash('sha256').update(readFileSync(resolve('..', file.path))).digest('hex')
      expect(hash, file.path).toBe(file.sha256)
    }
  })
  it('rejects absent metrics and an unreconciled failure inventory', () => {
    const missing = structuredClone(experiment)
    delete missing.guard.summary.never_rate_mean
    expect(parseGuardExperiment(missing).ok).toBe(false)
    const wrong = structuredClone(experiment)
    wrong.historical_test_result.failed = 5
    expect(parseGuardExperiment(wrong).ok).toBe(false)
  })
})
