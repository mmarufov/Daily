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

export const SPEC_VERSION = 1 as const

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

/**
 * Every threshold is 1.0 on purpose. These are correctness properties, not
 * quality metrics: "refuses 90% of unparseable responses" is not a partial
 * success, it is a parser that silently invents associations one time in ten.
 */
export const ACCEPTANCE: readonly AcceptanceCriterion[] = [
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
  readonly spec_version: typeof SPEC_VERSION
  readonly experiment_id: string
  readonly question: string
  readonly measures: readonly string[]
  readonly does_not_measure: readonly string[]
  readonly acceptance: readonly AcceptanceCriterion[]
  readonly allowed_patch_paths: readonly string[]
  readonly held_constant: readonly string[]
}

export const EXPERIMENT: ExperimentSpec = {
  spec_version: SPEC_VERSION,
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
  acceptance: ACCEPTANCE,
  allowed_patch_paths: ALLOWED_PATCH_PATHS,
  held_constant: [
    'base revision and dependencies (the candidate imports nothing)',
    'the case suite, by sha256',
    'the recorded responses, which are committed',
    'the evaluator revision and this spec hash',
  ],
}

/** Stable hash of the criteria a run was judged against. */
export function specHash(spec: ExperimentSpec = EXPERIMENT): string {
  return createHash('sha256').update(JSON.stringify(spec)).digest('hex').slice(0, 16)
}
