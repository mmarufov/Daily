/**
 * Metric semantics for Daily's S0 evaluation harness.
 *
 * Every number the explorer renders passes through this map. The map is
 * explicit rather than inferred because several of these metrics are easy to
 * get backwards, and a dashboard that points an improvement arrow the wrong way
 * is worse than no dashboard.
 *
 * Definitions are taken from backend/evals/README.md and backend/evals/metrics.py.
 * Direction polarity mirrors backend/evals/compare.py:33, which treats
 * never_rate, lookalike_rate, false_major_rate and latency_s as "bad when up".
 */

export type MetricDirection = 'higher-better' | 'lower-better' | 'neutral'

/** How a value should be formatted and how deltas should be expressed. */
export type MetricKind = 'fraction' | 'count' | 'usd' | 'seconds'

export interface MetricDefinition {
  readonly key: string
  readonly label: string
  readonly direction: MetricDirection
  readonly kind: MetricKind
  /** Plain-language meaning, shown before any technical provenance. */
  readonly plain: string
  /** Exact computation, shown on disclosure. */
  readonly formula?: string
  /** True when the harness legitimately reports null for some runners. */
  readonly nullable?: boolean
  /** Runner/snapshot restrictions that make the metric meaningless elsewhere. */
  readonly appliesOnly?: string
}

const DEFS: readonly MetricDefinition[] = [
  {
    key: 'recall_at_k',
    label: 'Capped recall@k',
    direction: 'higher-better',
    kind: 'fraction',
    plain: 'Of the stories this reader had to see, the share that made the feed — with the target capped at the number of slots available.',
    formula: 'must_see_in_top_k / min(n_must_see, k)',
  },
  {
    key: 'raw_recall_at_k',
    label: 'Raw recall@k',
    direction: 'higher-better',
    kind: 'fraction',
    plain: 'The same count divided by every must-see story, even when there are more must-see stories than feed slots. Always at or below capped recall.',
    formula: 'must_see_in_top_k / n_must_see',
  },
  {
    key: 'recall_at_retrieval',
    label: 'Reached the scorer',
    direction: 'higher-better',
    kind: 'fraction',
    plain: 'The share of must-see stories that survived long enough to be judged at all. A story never loaded cannot be ranked.',
    formula: 'must_see reaching the scoring stage / n_must_see',
  },
  {
    key: 'need_to_know_recall',
    label: 'Need-to-know recall',
    direction: 'higher-better',
    kind: 'fraction',
    plain: 'Recall restricted to stories labelled as ones the reader genuinely needed to know.',
  },
  {
    key: 'followup_recall',
    label: 'Follow-up recall',
    direction: 'higher-better',
    kind: 'fraction',
    plain: 'Recall restricted to stories that continue a thread the reader was already following.',
  },
  {
    key: 'never_rate',
    label: 'Unwanted rate',
    direction: 'lower-better',
    kind: 'fraction',
    plain: 'The share of the delivered feed that the reader had explicitly labelled as never wanted. Lower is better.',
    formula: 'never_labelled_in_top_k / k',
  },
  {
    key: 'event_delivery',
    label: 'World-critical delivery',
    direction: 'higher-better',
    kind: 'fraction',
    plain: 'Of the events everyone should have been told about, the share that put at least one story in the feed.',
  },
  {
    key: 'major_delivery',
    label: 'Major-event delivery',
    direction: 'higher-better',
    kind: 'fraction',
    plain: 'The same measure for events rated major rather than world-critical.',
  },
  {
    key: 'false_major_rate',
    label: 'False-major rate',
    direction: 'lower-better',
    kind: 'fraction',
    plain: 'How often the pipeline promoted a story as a major event when no major event existed. Measured on the quiet-day corpus, where the right answer is restraint.',
    appliesOnly: 'quiet snapshots, prototype runner only',
    nullable: true,
  },
  {
    key: 'event_slot_contamination',
    label: 'Event-slot contamination',
    direction: 'lower-better',
    kind: 'fraction',
    plain: 'Legacy alias carrying the same value as the false-major rate. Retained so older scorecards still read correctly.',
    nullable: true,
  },
  {
    key: 'judge_precision',
    label: 'Judge precision',
    direction: 'higher-better',
    kind: 'fraction',
    plain: 'When the model accepted a story, how often the labels agreed. Reported only for runners whose judge emits an explicit verdict.',
    nullable: true,
  },
  {
    key: 'judge_recall',
    label: 'Judge recall',
    direction: 'higher-better',
    kind: 'fraction',
    plain: 'Of the stories the labels wanted, how many the model accepted once it saw them.',
    nullable: true,
  },
  {
    key: 'needle_recall',
    label: 'Planted-needle recall',
    direction: 'higher-better',
    kind: 'fraction',
    plain: 'Recall on stories injected at run time whose correct answer is known by construction rather than by opinion.',
  },
  {
    key: 'lookalike_rate',
    label: 'Lookalike rate',
    direction: 'lower-better',
    kind: 'fraction',
    plain: 'How often a deliberate decoy got through — the right keyword attached to the wrong thing.',
  },
  {
    key: 'feed_size_k',
    label: 'Feed size at k',
    direction: 'neutral',
    kind: 'count',
    plain: 'How many slots the feed actually filled. A size, not a quality score.',
  },
  {
    key: 'distinct_sources',
    label: 'Distinct sources',
    direction: 'higher-better',
    kind: 'count',
    plain: 'How many different publications the feed drew from. More breadth is generally healthier, but this is a diversity proxy, not a correctness measure.',
  },
  {
    key: 'latency_s',
    label: 'Build latency',
    direction: 'lower-better',
    kind: 'seconds',
    plain: 'Wall-clock time to assemble one reader’s feed during the run. Offline replay timings are not production latency.',
  },
  {
    key: 'cost_usd',
    label: 'Estimated model cost',
    direction: 'lower-better',
    kind: 'usd',
    plain: 'Token-priced cost reconstructed for this run. Under offline replay no provider was actually charged.',
  },
  {
    key: 'cost_usd_total',
    label: 'Estimated model cost, all personas',
    direction: 'lower-better',
    kind: 'usd',
    plain: 'The same reconstruction summed across every persona in the run.',
  },
  {
    key: 'calls',
    label: 'Model calls',
    direction: 'lower-better',
    kind: 'count',
    plain: 'How many model requests the run needed for this persona.',
  },
  {
    key: 'calls_total',
    label: 'Model calls, all personas',
    direction: 'lower-better',
    kind: 'count',
    plain: 'Total model requests across the run.',
  },
  {
    key: 'calls_max_per_persona',
    label: 'Peak model calls for one persona',
    direction: 'lower-better',
    kind: 'count',
    plain: 'The worst single reader, which is what a per-request budget has to survive.',
  },
  {
    key: 'cache_misses_total',
    label: 'Cache misses',
    direction: 'lower-better',
    kind: 'count',
    plain: 'Requests that were not already in the committed response cache. Under offline replay this must be zero, because a miss fails the run rather than spending money.',
  },
  {
    key: 'personas',
    label: 'Personas',
    direction: 'neutral',
    kind: 'count',
    plain: 'How many reader fixtures the run covered. These are adversarial test fixtures, not users.',
  },
]

const BY_KEY = new Map<string, MetricDefinition>(DEFS.map((d) => [d.key, d]))

/** Summary keys are emitted as `<metric>_mean` / `<metric>_min`. */
export type SummaryAggregate = 'mean' | 'min'

export interface ResolvedMetric extends MetricDefinition {
  /** Present when the key was a `_mean` / `_min` summary variant. */
  readonly aggregate?: SummaryAggregate
  /** False when the key is not in the definition map. */
  readonly known: boolean
}

/**
 * Resolve any scorecard key — per-persona or `_mean`/`_min` summary — to its
 * definition. An unrecognised key resolves to a neutral, unknown metric so the
 * UI renders it without claiming a direction.
 */
export function resolveMetric(key: string): ResolvedMetric {
  const direct = BY_KEY.get(key)
  if (direct) return { ...direct, known: true }

  for (const suffix of ['_mean', '_min'] as const) {
    if (key.endsWith(suffix)) {
      const base = BY_KEY.get(key.slice(0, -suffix.length))
      if (base) {
        const aggregate: SummaryAggregate = suffix === '_mean' ? 'mean' : 'min'
        return { ...base, aggregate, known: true }
      }
    }
  }

  return {
    key,
    label: key,
    direction: 'neutral',
    kind: 'count',
    plain: 'This metric is not in the explorer’s definition map, so no direction is claimed for it.',
    known: false,
  }
}

export function allMetricDefinitions(): readonly MetricDefinition[] {
  return DEFS
}
