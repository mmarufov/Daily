/**
 * Aggregation across reader fixtures.
 *
 * One rule governs every count here: a story counted once per persona is a
 * persona/article pair, not an article. Ten fixtures looking at one corpus
 * means the same article can be must-see for three readers and never-wanted for
 * another, so "86 missed must-see stories" and "86 distinct articles missed"
 * are different claims. Both are computed and both are labelled.
 */

import type { Artifact, PersonaArtifact, Story, StoryOutcome } from './artifact'
import { stageOrderFor } from './funnel'

/** Metrics shown before any disclosure, in this order. */
export const HEADLINE_METRICS = [
  'recall_at_k',
  'raw_recall_at_k',
  'recall_at_retrieval',
  'never_rate',
  'need_to_know_recall',
  'event_delivery',
  'needle_recall',
  'lookalike_rate',
] as const

/** Additional metrics available on disclosure. */
export const SECONDARY_METRICS = [
  'followup_recall',
  'major_delivery',
  'false_major_rate',
  'judge_precision',
  'judge_recall',
  'distinct_sources',
  'feed_size_k',
  'latency_s',
] as const

export const RUN_LEVEL_METRICS = [
  'cost_usd_total',
  'calls_total',
  'calls_max_per_persona',
  'cache_misses_total',
] as const

export function summaryValue(artifact: Artifact, metric: string, aggregate: 'mean' | 'min'): number | null {
  const direct = artifact.summary[`${metric}_${aggregate}`]
  if (direct !== undefined) return direct
  const plain = artifact.summary[metric]
  return plain ?? null
}

export function findPersona(artifact: Artifact, key: string | undefined): PersonaArtifact | undefined {
  if (key === undefined) return undefined
  return artifact.personas.find((p) => p.key === key)
}

export interface PairCounts {
  /** Persona/article pairs. */
  readonly pairs: number
  /** Distinct article ids across all personas. */
  readonly uniqueArticles: number
}

export function countStories(
  personas: readonly PersonaArtifact[],
  predicate: (story: Story) => boolean,
): PairCounts {
  let pairs = 0
  const unique = new Set<string>()
  for (const persona of personas) {
    for (const story of persona.stories) {
      if (!predicate(story)) continue
      pairs += 1
      unique.add(story.id)
    }
  }
  return { pairs, uniqueArticles: unique.size }
}

export function outcomeBreakdown(personas: readonly PersonaArtifact[]): Map<StoryOutcome, PairCounts> {
  const outcomes: StoryOutcome[] = [
    'delivered-wanted',
    'delivered-unwanted',
    'delivered-unlabelled',
    'lost-before-scorer',
    'lost-at-or-after-scorer',
  ]
  const result = new Map<StoryOutcome, PairCounts>()
  for (const outcome of outcomes) {
    result.set(outcome, countStories(personas, (s) => s.outcome === outcome))
  }
  return result
}

export interface AggregateFunnelStep {
  readonly stage: string
  readonly label: string
  readonly explanation: string | null
  readonly survivors: number
  readonly lostEnteringStage: number
  readonly passRate: number | null
  /** How many personas contributed a tally at this stage. */
  readonly personasReporting: number
}

/**
 * Sum the per-persona funnels. Survivor counts add across personas because each
 * persona evaluates its own copy of the pool, so the total is persona/article
 * pairs surviving — not distinct articles.
 */
export function aggregateFunnel(
  personas: readonly PersonaArtifact[],
  runner: string,
): readonly AggregateFunnelStep[] {
  const order = stageOrderFor(runner)
  const survivors = new Map<string, number>()
  const reporting = new Map<string, number>()
  const labels = new Map<string, string>()
  const explanations = new Map<string, string | null>()

  for (const persona of personas) {
    for (const step of persona.funnel) {
      labels.set(step.stage, step.label)
      explanations.set(step.stage, step.explanation)
      survivors.set(step.stage, (survivors.get(step.stage) ?? 0) + step.survivors)
      if (!step.absent) reporting.set(step.stage, (reporting.get(step.stage) ?? 0) + 1)
    }
  }

  const steps: AggregateFunnelStep[] = []
  let previous: number | null = null
  for (const stage of order) {
    const total = survivors.get(stage) ?? 0
    steps.push({
      stage,
      label: labels.get(stage) ?? stage,
      explanation: explanations.get(stage) ?? null,
      survivors: total,
      lostEnteringStage: previous === null ? 0 : previous - total,
      passRate: previous === null || previous === 0 ? null : total / previous,
      personasReporting: reporting.get(stage) ?? 0,
    })
    previous = total
  }
  return steps
}

/** Sum a `loss_by_stage` map across personas. */
export function aggregateLossByStage(
  personas: readonly PersonaArtifact[],
): ReadonlyMap<string, number> {
  const total = new Map<string, number>()
  for (const persona of personas) {
    for (const [stage, count] of Object.entries(persona.loss_by_stage)) {
      total.set(stage, (total.get(stage) ?? 0) + count)
    }
  }
  return new Map([...total].sort((a, b) => b[1] - a[1]))
}

/**
 * The weakest fixture for a metric, so an average cannot hide it. Returns null
 * when no fixture reported the metric at all.
 */
export function weakestPersona(
  personas: readonly PersonaArtifact[],
  metric: string,
  direction: 'higher-better' | 'lower-better' | 'neutral',
): { key: string; value: number } | null {
  if (direction === 'neutral') return null
  let worst: { key: string; value: number } | null = null
  for (const persona of personas) {
    const value = persona.metrics[metric]
    if (value === null || value === undefined) continue
    if (worst === null) {
      worst = { key: persona.key, value }
      continue
    }
    const isWorse = direction === 'higher-better' ? value < worst.value : value > worst.value
    if (isWorse) worst = { key: persona.key, value }
  }
  return worst
}
