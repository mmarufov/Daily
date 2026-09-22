/**
 * The frozen experiment specification.
 *
 * Written down, hashed, and committed *before* any candidate runs. The hash
 * travels into every artifact, so a reader can tell whether the criteria a run
 * was judged against are the criteria in the repository today. Moving a
 * threshold to obtain a green result changes the hash and invalidates the
 * comparison — which is the point.
 *
 * What this experiment measures: **contract correctness** — whether a parser
 * associates the right verdict with the right article, and refuses when it
 * cannot. It deliberately does not measure relevance quality, latency or cost.
 * Those are separate questions and mixing them is how a correctness regression
 * gets argued away as a quality trade-off.
 */

import { createHash } from 'node:crypto'

/**
 * The spec is versioned, and every generation stays addressable.
 *
 * Generation 2 adds a criterion that generation 1 lacked, because a real
 * candidate walked through the gap: `keyed-fallback-v1` declared `keyed-v2`,
 * was marked not-applicable on positional association cases -- correctly --
 * and then quietly associated on them anyway, reproducing the exact defect
 * this experiment exists to measure on the case built to expose it. Nothing
 * checked that a parser *refused* what it did not declare.
 *
 * Both generations are kept and every run is graded under both, for a reason
 * the alternative makes obvious: silently re-grading eight runs under criteria
 * they never faced is how a result gets rewritten after the fact. Publishing
 * both lets a reader see the same candidate accepted under v1 and rejected
 * under v2 and decide what that is worth, which is a stronger claim than
 * either verdict alone.
 *
 * `SPEC_V1` is frozen. Its serialisation -- key order included -- is what
 * `specHash` digests, so editing it would rewrite the hash already carried by
 * every committed artifact. `spec.test.ts` pins that hash.
 */
export const SPEC_VERSION = 2 as const

/** Protocols a candidate may declare. */
export const PROTOCOLS = ['positional-v0', 'keyed-v2'] as const
export type Protocol = (typeof PROTOCOLS)[number]

/**
 * Case families, and the obligation each carries.
 *
 * `universal-refusal` — the response is truncated, malformed, or carries a
 * different number of verdicts than there were articles. No parser of any
 * protocol can recover an association from it, so every candidate is scored
 * here. Only the refusal is required; the *kind* is reported as a diagnostic
 * but not graded, because a keyed parser legitimately calls the same defect
 * `missing_id` where a positional one calls it `count_mismatch`.
 *
 * `protocol-association` — the case exercises the association rules of one
 * specific protocol. A candidate that does not declare that protocol is marked
 * not-applicable: neither credited nor penalised. Scoring a keyed parser on its
 * inability to read a positional recording would be comparing two protocols on
 * one protocol's inputs, which this repository already refuses to do elsewhere.
 */
export const CASE_FAMILIES = ['universal-refusal', 'protocol-association'] as const
export type CaseFamily = (typeof CASE_FAMILIES)[number]

export interface AcceptanceCriterion {
  readonly id: string
  readonly question: string
  /** Minimum share of applicable cases that must satisfy it, 0..1. */
  readonly threshold: number
}

/** Every criterion id the evaluator knows how to compute. */
export type CriterionId =
  | 'universal-refusal'
  | 'association-exact'
  | 'protocol-violation-refusal'
  | 'no-crash'
  | 'complete-evidence'
  | 'protocol-exclusivity'

/**
 * Every threshold is 1.0 on purpose. These are correctness properties, not
 * quality metrics: "refuses 90% of unparseable responses" is not a partial
 * success, it is a parser that silently invents associations one time in ten.
 */
export const ACCEPTANCE_V1: readonly AcceptanceCriterion[] = [
  {
    id: 'universal-refusal',
    question: 'Does it refuse every response from which no association can be recovered?',
    threshold: 1,
  },
  {
    id: 'association-exact',
    question: 'On its own protocol, does every article receive exactly the verdict it was given?',
    threshold: 1,
  },
  {
    id: 'protocol-violation-refusal',
    question: 'Does it refuse duplicate, unknown, missing ids and unusable scores?',
    threshold: 1,
  },
  {
    id: 'no-crash',
    question: 'Does it terminate on every case without crashing or hanging?',
    threshold: 1,
  },
  {
    id: 'complete-evidence',
    question: 'Is there a prediction record for every applicable case?',
    threshold: 1,
  },
]

/**
 * The sixth criterion, and why it is a criterion rather than a diagnostic.
 *
 * A declared protocol was treated as a shield: say `keyed-v2` and the
 * positional cases stop counting. That is right for *association* -- scoring a
 * keyed parser on a positional recording compares two protocols on one
 * protocol's inputs -- and wrong for *refusal*. A parser that quietly handles
 * inputs it did not declare is not narrower than the contract, it is wider
 * than the contract and unmeasured in the excess.
 *
 * Threshold 1, like the rest. "Refuses 90% of the protocols it does not
 * implement" is not a partial success.
 */
export const ACCEPTANCE_V2: readonly AcceptanceCriterion[] = [
  ...ACCEPTANCE_V1,
  {
    id: 'protocol-exclusivity',
    question:
      'On cases outside its declared protocol, does it refuse rather than associate anyway?',
    threshold: 1,
  },
]

/** The criteria of the current generation. */
export const ACCEPTANCE = ACCEPTANCE_V2

/**
 * The only paths a candidate may change.
 *
 * One file. A candidate is self-contained with no project imports and no
 * third-party dependencies, which is what makes this list short enough to be
 * obviously correct.
 */
export const ALLOWED_PATCH_PATHS: readonly string[] = [
  'backend/lab/contract/candidate.py',
]

/** Paths that are never writable, listed so the refusal can name a reason. */
export const FORBIDDEN_PATCH_PREFIXES: readonly { prefix: string; reason: string }[] = [
  { prefix: 'web/lib/lab/', reason: 'the evaluator grades the candidate' },
  { prefix: 'backend/lab/cases/', reason: 'the cases are the evidence' },
  { prefix: 'backend/lab/harness.py', reason: 'the harness produces the records' },
  { prefix: 'backend/evals/', reason: 'labels, corpora and recordings are ground truth' },
  { prefix: 'backend/tests/', reason: 'tests are not negotiable by the thing under test' },
  { prefix: '.github/', reason: 'publishing and orchestration' },
  { prefix: 'web/package.json', reason: 'dependencies' },
  { prefix: 'web/package-lock.json', reason: 'dependencies' },
  { prefix: 'backend/requirements.txt', reason: 'dependencies' },
]

export interface ExperimentSpec {
  readonly spec_version: number
  readonly experiment_id: string
  readonly question: string
  readonly measures: readonly string[]
  readonly does_not_measure: readonly string[]
  readonly acceptance: readonly AcceptanceCriterion[]
  readonly allowed_patch_paths: readonly string[]
  readonly held_constant: readonly string[]
}

/**
 * Generation 1, frozen.
 *
 * Do not edit. `specHash` digests `JSON.stringify(spec)`, so any change here
 * -- including reordering a key -- rewrites the hash that eight committed
 * artifacts already carry, and a verdict would silently start claiming it was
 * judged against criteria it never faced.
 */
export const SPEC_V1: ExperimentSpec = {
  spec_version: 1,
  experiment_id: 'article-to-verdict-association',
  question:
    'Does a candidate parser associate every returned verdict with the article it was actually about, and refuse when that association cannot be recovered?',
  measures: [
    'association correctness on cases whose ground truth is known by construction',
    'refusal on responses that are truncated, malformed, or miscounted',
    'refusal on duplicate, unknown and missing article ids',
    'refusal on non-finite and out-of-range scores',
    'termination without crash or hang',
  ],
  does_not_measure: [
    'relevance quality — no keyed recordings exist, so no protocol-v2 feed has ever been built',
    'latency and cost — reported separately and never traded against correctness',
    'generalisation — the cases are public and a candidate may be written against them',
  ],
  acceptance: ACCEPTANCE_V1,
  allowed_patch_paths: ALLOWED_PATCH_PATHS,
  held_constant: [
    'base revision and dependencies (the candidate imports nothing)',
    'the case suite, by sha256',
    'the recorded responses, which are committed',
    'the evaluator revision and this spec hash',
  ],
}

/**
 * Generation 2: the same experiment, with the exclusivity gap closed.
 *
 * `measures` gains one line and `acceptance` gains one criterion. Everything
 * else is identical, deliberately -- the two generations differ in exactly
 * the thing under discussion, so a reader comparing verdicts is comparing one
 * change rather than a rewrite.
 */
export const SPEC_V2: ExperimentSpec = {
  ...SPEC_V1,
  spec_version: 2,
  measures: [
    ...SPEC_V1.measures,
    'refusal of inputs outside the protocol the candidate declares',
  ],
  acceptance: ACCEPTANCE_V2,
}

/** Every generation, oldest first. Each run is graded under all of them. */
export const SPECS: readonly ExperimentSpec[] = [SPEC_V1, SPEC_V2]

/** The generation a new run is judged by, and the one the page leads with. */
export const EXPERIMENT: ExperimentSpec = SPEC_V2

/** Stable hash of the criteria a run was judged against. */
export function specHash(spec: ExperimentSpec = EXPERIMENT): string {
  return createHash('sha256').update(JSON.stringify(spec)).digest('hex').slice(0, 16)
}
