/**
 * Candidate-funnel reconstruction.
 *
 * The important subtlety: `stage_counts` in a scorecard is NOT survivorship.
 * The harness records each article once, at the furthest stage it reached
 * (backend/evals/runners.py records `stage_reached` per article; metrics.py
 * tallies it). Rendering those tallies directly produces an incoherent funnel —
 * for persona `ray` on snapshot 2026-09-02 it would show `scored` at 45 and
 * `feed` at 50, i.e. a funnel that grows.
 *
 * Survivors at a stage are therefore the sum of tallies at that stage and every
 * later stage. That reconstruction was validated against three independent
 * facts recorded elsewhere in the same scorecard:
 *
 *   survivors at `feed`        = 50  = the reported `feed_size`
 *   survivors at `loaded_rows` = 300 = `meta.served`, the recency window
 *   survivors at `scored`      = 100 = the documented 100-candidate cap
 *
 * and the total, 1362, exceeds the 1358-article snapshot by exactly 4 — the two
 * must-see needles and two lookalikes injected per persona at run time.
 */

/** backend/evals/metrics.py:20 */
export const PROD_ORDER = [
  'pool',
  'loaded_rows',
  'loaded',
  'prefilter',
  'scored',
  'blended',
  'dedup',
  'diversity',
  'roles',
  'feed',
] as const

/** backend/evals/metrics.py:21 */
export const PROTO_ORDER = ['pool', 'recall', 'triage', 'judge', 'feed'] as const

export type StageName = (typeof PROD_ORDER)[number] | (typeof PROTO_ORDER)[number]

const STAGE_LABELS: Record<string, string> = {
  pool: 'Corpus pool',
  loaded_rows: 'Recency window',
  loaded: 'Loaded',
  prefilter: 'Prefilter',
  scored: 'Scored',
  blended: 'Blended',
  dedup: 'Deduplicated',
  diversity: 'Diversity pass',
  roles: 'Role assignment',
  feed: 'Delivered feed',
  recall: 'Recall',
  triage: 'Triage',
  judge: 'Judge',
}

const STAGE_EXPLANATIONS: Record<string, string> = {
  pool: 'Every article in the frozen snapshot, plus the needles planted for this persona.',
  loaded_rows: 'What the recency window actually returned from the database.',
  loaded: 'Rows that survived loading and had usable text.',
  prefilter: 'Survivors of the cheap keyword and exclusion pass that runs before any model call.',
  scored: 'Candidates the relevance scorer actually saw. Nothing beyond this point can rescue a story dropped earlier.',
  blended: 'Candidates left after the score blend.',
  dedup: 'Candidates left after near-duplicate removal.',
  diversity: 'Candidates left after the source-diversity pass.',
  roles: 'Candidates left after hero and row roles were assigned.',
  feed: 'What the reader would have opened.',
  recall: 'Candidates returned by hybrid lexical and vector recall.',
  triage: 'Candidates that survived cheap triage before the judge.',
  judge: 'Candidates the LLM judge returned a verdict on.',
}

export function stageOrderFor(runner: string): readonly string[] {
  return runner.startsWith('proto') ? PROTO_ORDER : PROD_ORDER
}

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] ?? stage
}

export function stageExplanation(stage: string): string | undefined {
  return STAGE_EXPLANATIONS[stage]
}

export interface FunnelStep {
  readonly stage: string
  readonly label: string
  readonly explanation?: string
  /** Articles whose furthest stage was exactly this one. */
  readonly terminal: number
  /** Articles that reached this stage or later. */
  readonly survivors: number
  /** Articles lost between the previous stage and this one. */
  readonly lostEnteringStage: number
  /** Share of the previous stage's survivors that made it here, null at the head. */
  readonly passRate: number | null
  /** True when the harness emitted no tally for this stage at all. */
  readonly absent: boolean
}

export interface Funnel {
  readonly steps: readonly FunnelStep[]
  readonly total: number
  /** Stage tallies present in the data but absent from the declared order. */
  readonly unrecognisedStages: readonly string[]
}

export function buildFunnel(
  stageCounts: Readonly<Record<string, number>>,
  runner: string,
): Funnel {
  const order = stageOrderFor(runner)
  const known = new Set<string>(order)
  const unrecognisedStages = Object.keys(stageCounts)
    .filter((s) => !known.has(s))
    .sort()

  // Survivors accumulate from the last stage backwards.
  const survivorsByStage = new Map<string, number>()
  let running = 0
  for (let i = order.length - 1; i >= 0; i -= 1) {
    const stage = order[i]
    if (stage === undefined) continue
    running += stageCounts[stage] ?? 0
    survivorsByStage.set(stage, running)
  }

  const steps: FunnelStep[] = []
  let previousSurvivors: number | null = null
  for (const stage of order) {
    const survivors = survivorsByStage.get(stage) ?? 0
    const terminal = stageCounts[stage] ?? 0
    const absent = !(stage in stageCounts)
    const lostEnteringStage = previousSurvivors === null ? 0 : previousSurvivors - survivors
    const passRate =
      previousSurvivors === null || previousSurvivors === 0
        ? null
        : survivors / previousSurvivors

    const step: FunnelStep = {
      stage,
      label: stageLabel(stage),
      terminal,
      survivors,
      lostEnteringStage,
      passRate,
      absent,
      ...(stageExplanation(stage) !== undefined
        ? { explanation: stageExplanation(stage) as string }
        : {}),
    }
    steps.push(step)
    previousSurvivors = survivors
  }

  return {
    steps,
    total: survivorsByStage.get(order[0] as string) ?? 0,
    unrecognisedStages,
  }
}

export interface DropReason {
  /** Raw key as recorded, e.g. `prefilter:cap` or `lookback`. */
  readonly key: string
  /** Portion before the colon, which may or may not be a declared stage. */
  readonly group: string
  /** Portion after the colon, when present. */
  readonly detail: string | null
  readonly count: number
  /** True when `group` appears in this runner's declared stage order. */
  readonly mapsToStage: boolean
}

/**
 * Normalise a `drop_counts` or `loss_by_stage` map into grouped reasons.
 *
 * These keys are attrition *reasons*, not stages. Some coincide with a stage
 * name (`blended`), some qualify one (`prefilter:cap`), some name a mechanism
 * that sits between stages (`lookback`, the recency window), some are content
 * rejections (`text_too_short`), and `after:<stage>` marks an article that was
 * still alive when the pipeline ended. They are deliberately not forced onto
 * the stage axis.
 */
export function normaliseDropReasons(
  counts: Readonly<Record<string, number>>,
  runner: string,
): readonly DropReason[] {
  const order = new Set<string>(stageOrderFor(runner))
  return Object.entries(counts)
    .map(([key, count]): DropReason => {
      const colon = key.indexOf(':')
      const group = colon === -1 ? key : key.slice(0, colon)
      const detail = colon === -1 ? null : key.slice(colon + 1)
      return { key, group, detail, count, mapsToStage: order.has(group) }
    })
    .sort((a, b) => b.count - a.count || a.key.localeCompare(b.key))
}
