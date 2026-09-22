/**
 * The trusted evaluator.
 *
 * This is the only code that decides anything. It runs outside the sandbox, in
 * a different language from the candidate, over JSON the candidate cannot
 * extend: `PredictionRecordSchema` strips unknown keys, so a self-assessment
 * never reaches this file even if a candidate emits one.
 *
 * Three rules govern every branch below.
 *
 *  1. **Absence is never acceptance.** A missing record, a crash, a timeout, an
 *     unreadable bundle — each resolves to `incomplete` or `rejected`, and
 *     there is no path from "we could not tell" to "accepted".
 *  2. **The candidate's protocol claim is checked, not believed.** A bundle
 *     declaring `keyed-v2` is scored on keyed-v2 association cases; declaring a
 *     protocol it does not implement makes it fail those cases, not skip them.
 *  3. **Acceptance means eligible for human review**, under this spec hash,
 *     against these public cases. It is not a claim about production quality
 *     and the artifact says so.
 */

import { EXPERIMENT, specHash, type AcceptanceCriterion, type CaseFamily, type ExperimentSpec, type Protocol } from './spec'
import type { Case, PredictionRecord, RecordBundle } from './records'

export type Applicability = 'scored' | 'not-applicable'

export type CaseStatus =
  | 'correct'
  | 'wrong-association'
  | 'should-have-refused'
  | 'should-have-parsed'
  | 'crashed'
  | 'timeout'
  | 'missing-record'
  | 'not-applicable'

export interface CaseOutcome {
  readonly case_id: string
  readonly group: Case['group']
  readonly family: CaseFamily
  readonly protocol: Protocol
  readonly applicability: Applicability
  readonly status: CaseStatus
  /** Why the status is what it is, in one sentence, for the operator. */
  readonly detail: string
  /** The single clearest wrong association, when there is one. */
  readonly counterexample: Counterexample | null
  readonly observed_refusal_kind: string | null
  readonly expected_refusal_kinds: readonly string[]
  readonly ms: number | null
}

export interface Counterexample {
  readonly article_id: string
  readonly article_title: string
  readonly expected: { relevant: boolean; score: number }
  readonly actual: { relevant: boolean; score: number | null; reason: string } | null
}

export interface CriterionResult {
  readonly id: string
  readonly question: string
  readonly threshold: number
  readonly applicable: number
  readonly satisfied: number
  /** null when nothing was applicable — not 1.0, and not 0.0. */
  readonly rate: number | null
  readonly passed: boolean
}

export type Verdict =
  | 'accepted-for-review'
  | 'rejected'
  | 'incomplete'
  | 'failed'
  | 'cancelled'

/**
 * Something the run showed that no criterion grades.
 *
 * Added because a real candidate walked through a real gap. A parser that
 * declares `keyed-v2` is marked not-applicable on positional association
 * cases, and rightly so -- scoring it on another protocol's inputs would be
 * comparing two protocols on one protocol's recordings. But nothing checked
 * that it *refused* those cases rather than quietly handling them, and a
 * candidate with a positional fallback therefore reproduced the exact defect
 * this experiment exists to measure, on the case built to expose it, and was
 * accepted.
 *
 * This is reported, not graded. Turning it into a sixth criterion would
 * change the spec hash and re-decide seven runs that never faced it, which
 * is precisely the move `spec.ts` says invalidates a comparison. Publishing
 * the number lets a reader see the gap without the gap being closed behind
 * their back.
 */
export interface Diagnostic {
  readonly id: string
  readonly question: string
  readonly value: number
  readonly of: number
  readonly detail: string
  /** Case ids, so the claim is checkable rather than a count to trust. */
  readonly case_ids: readonly string[]
}

export interface Evaluation {
  readonly verdict: Verdict
  readonly reason: string
  readonly criteria: readonly CriterionResult[]
  readonly outcomes: readonly CaseOutcome[]
  readonly counts: Readonly<Record<CaseStatus, number>>
  readonly declared_protocol: string
  /** Which generation of the criteria produced this verdict. */
  readonly spec_version: number
  readonly spec_hash: string
  readonly smallest_counterexample: Counterexample | null
  /** Measured and published; never an input to the verdict. */
  readonly diagnostics: readonly Diagnostic[]
}

/**
 * Is this case scored against a candidate declaring `protocol`?
 *
 * A universal-refusal case binds everyone: no parser of any protocol can
 * recover an association from a truncated or miscounted response. A
 * protocol-association case binds only parsers that declare it.
 */
export function applicability(kase: Case, protocol: string): Applicability {
  if (kase.family === 'universal-refusal') return 'scored'
  return kase.protocol === protocol ? 'scored' : 'not-applicable'
}

function compareAssociation(
  kase: Case,
  record: PredictionRecord,
): { ok: boolean; counterexample: Counterexample | null; detail: string } {
  const expected = kase.expectation.association
  if (expected === null) return { ok: false, counterexample: null, detail: 'no ground truth recorded' }
  const actual = record.association ?? {}
  const titles = new Map(kase.articles.map((a) => [a.id, a.title]))

  // Walk in request order so the "smallest" counterexample is the earliest
  // article a reader would have noticed, not an arbitrary map entry.
  for (const article of kase.articles) {
    const want = expected[article.id]
    if (want === undefined) continue
    const got = actual[article.id]
    if (got === undefined) {
      return {
        ok: false,
        detail: `no verdict for ${article.id}`,
        counterexample: {
          article_id: article.id,
          article_title: titles.get(article.id) ?? article.id,
          expected: want,
          actual: null,
        },
      }
    }
    const scoreMatches = got.score !== null && Math.abs(got.score - want.score) < 1e-9
    if (!scoreMatches || got.relevant !== want.relevant) {
      return {
        ok: false,
        detail: `${article.id} received the wrong verdict`,
        counterexample: {
          article_id: article.id,
          article_title: titles.get(article.id) ?? article.id,
          expected: want,
          actual: { relevant: got.relevant, score: got.score, reason: got.reason },
        },
      }
    }
  }

  // A verdict for an article that was never sent is also a wrong association.
  const extra = Object.keys(actual).find((id) => expected[id] === undefined)
  if (extra !== undefined) {
    return {
      ok: false,
      detail: `verdict returned for ${extra}, which was not in the batch`,
      counterexample: {
        article_id: extra,
        article_title: titles.get(extra) ?? extra,
        expected: { relevant: false, score: 0 },
        actual: actual[extra] ?? null,
      },
    }
  }

  return { ok: true, counterexample: null, detail: 'every article received its own verdict' }
}

function judgeCase(kase: Case, record: PredictionRecord | undefined, protocol: string): CaseOutcome {
  const base = {
    case_id: kase.case_id,
    group: kase.group,
    family: kase.family,
    protocol: kase.protocol,
    expected_refusal_kinds: kase.expectation.refusal_kinds,
  } as const

  const applies = applicability(kase, protocol)
  if (applies === 'not-applicable') {
    return {
      ...base,
      applicability: applies,
      status: 'not-applicable',
      detail: `case is ${kase.protocol}; candidate declares ${protocol}`,
      counterexample: null,
      observed_refusal_kind: record?.refusal_kind ?? null,
      ms: record?.ms ?? null,
    }
  }

  if (record === undefined) {
    // The load-bearing branch. No record is not a pass.
    return {
      ...base,
      applicability: applies,
      status: 'missing-record',
      detail: 'the candidate produced no record for this case',
      counterexample: null,
      observed_refusal_kind: null,
      ms: null,
    }
  }

  const common = {
    ...base,
    applicability: applies,
    observed_refusal_kind: record.refusal_kind,
    ms: record.ms,
  } as const

  if (record.outcome === 'timeout') {
    return { ...common, status: 'timeout', detail: record.error ?? 'exceeded the case timeout', counterexample: null }
  }
  if (record.outcome === 'crashed') {
    return { ...common, status: 'crashed', detail: (record.error ?? 'raised').split('\n')[0] ?? 'raised', counterexample: null }
  }

  if (kase.expectation.expect === 'refuse') {
    if (record.outcome === 'refused') {
      return { ...common, status: 'correct', detail: `refused (${record.refusal_kind})`, counterexample: null }
    }
    // It produced an association where none was recoverable. For an observed
    // case this is the defect itself: a verdict attached to an article the
    // model never judged.
    return {
      ...common,
      status: 'should-have-refused',
      detail: kase.expectation.why,
      counterexample: null,
    }
  }

  if (record.outcome === 'refused') {
    return {
      ...common,
      status: 'should-have-parsed',
      detail: `refused (${record.refusal_kind}) a response it was expected to read`,
      counterexample: null,
    }
  }

  const comparison = compareAssociation(kase, record)
  return {
    ...common,
    status: comparison.ok ? 'correct' : 'wrong-association',
    detail: comparison.detail,
    counterexample: comparison.counterexample,
  }
}

const EMPTY_COUNTS: Record<CaseStatus, number> = {
  correct: 0,
  'wrong-association': 0,
  'should-have-refused': 0,
  'should-have-parsed': 0,
  crashed: 0,
  timeout: 0,
  'missing-record': 0,
  'not-applicable': 0,
}

function criterion(
  id: string,
  outcomes: readonly CaseOutcome[],
  selects: (o: CaseOutcome) => boolean,
  acceptance: readonly AcceptanceCriterion[],
): CriterionResult {
  const definition = acceptance.find((c) => c.id === id)
  const applicable = outcomes.filter((o) => o.applicability === 'scored' && selects(o))
  const satisfied = applicable.filter((o) => o.status === 'correct').length
  const rate = applicable.length === 0 ? null : satisfied / applicable.length
  return {
    id,
    question: definition?.question ?? id,
    threshold: definition?.threshold ?? 1,
    applicable: applicable.length,
    satisfied,
    rate,
    // Vacuous truth is not a pass: a criterion with nothing to check cannot be
    // claimed as satisfied, and `complete-evidence` below turns that into
    // `incomplete` rather than acceptance.
    passed: rate !== null && rate >= (definition?.threshold ?? 1),
  }
}

export function evaluate(
  cases: readonly Case[],
  bundle: RecordBundle | null,
  options: { cancelled?: boolean; failure?: string; spec?: ExperimentSpec } = {},
): Evaluation {
  const spec = options.spec ?? EXPERIMENT
  if (options.cancelled === true) {
    return {
      verdict: 'cancelled',
      reason: 'the run was cancelled before it produced a complete result',
      criteria: [],
      outcomes: [],
      counts: { ...EMPTY_COUNTS },
      declared_protocol: bundle?.declared_protocol ?? 'unknown',
      spec_version: spec.spec_version,
      spec_hash: specHash(spec),
      smallest_counterexample: null,
      // No records, nothing measured. An empty list rather than a zero: zero
      // out-of-protocol associations is a clean result, and this run has none.
      diagnostics: [],
    }
  }
  if (bundle === null) {
    return {
      verdict: options.failure === undefined ? 'incomplete' : 'failed',
      reason: options.failure ?? 'no prediction records were produced',
      criteria: [],
      outcomes: [],
      counts: { ...EMPTY_COUNTS },
      declared_protocol: 'unknown',
      spec_version: spec.spec_version,
      spec_hash: specHash(spec),
      smallest_counterexample: null,
      diagnostics: [],
    }
  }

  const protocol = bundle.declared_protocol
  const byId = new Map(bundle.records.map((r) => [r.case_id, r]))
  const outcomes = cases.map((kase) => judgeCase(kase, byId.get(kase.case_id), protocol))

  const counts = { ...EMPTY_COUNTS }
  for (const o of outcomes) counts[o.status] += 1

  const scored = outcomes.filter((o) => o.applicability === 'scored')

  // Cases the candidate was excused from, on which it answered anyway.
  //
  // `judgeCase` returns early for a not-applicable case without inspecting
  // the record, so this reads the record directly. An association where the
  // protocol was not the candidate's own is undeclared behaviour: the parser
  // is doing something the criteria never looked at.
  const outOfProtocol = cases.filter((kase) => {
    if (applicability(kase, protocol) !== 'not-applicable') return false
    const record = byId.get(kase.case_id)
    return record !== undefined && record.outcome === 'parsed' && record.association !== null
  })

  const acceptance = spec.acceptance
  const criteria: CriterionResult[] = [
    criterion('universal-refusal', outcomes, (o) => o.family === 'universal-refusal', acceptance),
    criterion(
      'association-exact',
      outcomes,
      (o) => o.family === 'protocol-association' && o.expected_refusal_kinds.length === 0,
      acceptance,
    ),
    criterion(
      'protocol-violation-refusal',
      outcomes,
      (o) => o.family === 'protocol-association' && o.expected_refusal_kinds.length > 0,
      acceptance,
    ),
  ]

  // The diagnostic survives its own promotion to a criterion.
  //
  // Under generation 2 this *is* graded, so the wording must stop saying it
  // is not -- a stale sentence describing a closed gap is the same failure as
  // a stale honesty note describing an unexercised boundary. What the
  // diagnostic still carries that the criterion does not is the case ids, so
  // a reader can check the claim rather than take the count.
  const graded = acceptance.some((c) => c.id === 'protocol-exclusivity')
  const diagnostics: Diagnostic[] = [
    {
      id: 'out-of-protocol-association',
      question:
        'On cases outside its declared protocol, did it refuse — or associate anyway?',
      value: outOfProtocol.length,
      of: outcomes.filter((o) => o.applicability === 'not-applicable').length,
      detail:
        outOfProtocol.length === 0
          ? 'It produced no association on any case outside its declared protocol.'
          : graded
            ? `It produced a complete association on ${outOfProtocol.length} case(s) outside its declared protocol. Under this generation that fails protocol-exclusivity; under generation 1 it was not graded at all.`
            : `It produced a complete association on ${outOfProtocol.length} case(s) it was marked not-applicable for, so that behaviour was never graded. A parser can therefore reproduce the association defect outside its declared protocol and still satisfy every criterion.`,
      case_ids: outOfProtocol.map((k) => k.case_id),
    },
  ]
  const broken = scored.filter((o) => o.status === 'crashed' || o.status === 'timeout').length
  criteria.push({
    id: 'no-crash',
    question: acceptance.find((c) => c.id === 'no-crash')?.question ?? 'no-crash',
    threshold: 1,
    applicable: scored.length,
    satisfied: scored.length - broken,
    rate: scored.length === 0 ? null : (scored.length - broken) / scored.length,
    passed: scored.length > 0 && broken === 0,
  })

  const missing = scored.filter((o) => o.status === 'missing-record').length
  criteria.push({
    id: 'complete-evidence',
    question: acceptance.find((c) => c.id === 'complete-evidence')?.question ?? 'complete-evidence',
    threshold: 1,
    applicable: scored.length,
    satisfied: scored.length - missing,
    rate: scored.length === 0 ? null : (scored.length - missing) / scored.length,
    passed: scored.length > 0 && missing === 0,
  })

  // The sixth criterion, present only in the generation that defines it.
  //
  // Graded over the cases the candidate was *excused* from, which is why it
  // cannot go through `criterion()` -- that selects `scored` outcomes, and
  // these are by construction not-applicable. A case with no record at all is
  // excluded: silence there is `complete-evidence`'s business, and counting it
  // as a refusal would credit a candidate for not running.
  if (acceptance.some((c) => c.id === 'protocol-exclusivity')) {
    const excused = cases.filter(
      (kase) => applicability(kase, protocol) === 'not-applicable' && byId.has(kase.case_id),
    )
    const refused = excused.length - outOfProtocol.length
    criteria.push({
      id: 'protocol-exclusivity',
      question:
        acceptance.find((c) => c.id === 'protocol-exclusivity')?.question ?? 'protocol-exclusivity',
      threshold: 1,
      applicable: excused.length,
      satisfied: refused,
      rate: excused.length === 0 ? null : refused / excused.length,
      // Vacuous truth is not a pass here either. A candidate that declares a
      // protocol covering every case has nothing to be exclusive about, and
      // that is an absence of evidence rather than a clean bill.
      passed: excused.length > 0 && outOfProtocol.length === 0,
    })
  }

  const smallest =
    outcomes
      .filter((o) => o.counterexample !== null)
      .sort((a, b) => a.case_id.localeCompare(b.case_id))[0]?.counterexample ?? null

  // Order matters: evidence problems resolve before quality ones, so an
  // incomplete run can never be reported as a rejection on the merits (or,
  // worse, as an acceptance).
  const evidence = criteria.filter((c) => c.id === 'complete-evidence' || c.id === 'no-crash')
  if (evidence.some((c) => !c.passed)) {
    const why = missing > 0 ? `${missing} case(s) produced no record` : `${broken} case(s) crashed or timed out`
    return {
      verdict: 'incomplete',
      reason: `${why}; missing evidence is never acceptance`,
      criteria,
      outcomes,
      counts,
      declared_protocol: protocol,
      spec_version: spec.spec_version,
      spec_hash: specHash(spec),
      smallest_counterexample: smallest,
      diagnostics,
    }
  }

  const failedCriteria = criteria.filter((c) => !c.passed)
  if (failedCriteria.length > 0) {
    const first = failedCriteria[0]
    return {
      verdict: 'rejected',
      reason:
        first === undefined
          ? 'an acceptance criterion was not met'
          : `${first.id}: ${first.satisfied}/${first.applicable} cases satisfied, threshold ${first.threshold}`,
      criteria,
      outcomes,
      counts,
      declared_protocol: protocol,
      spec_version: spec.spec_version,
      spec_hash: specHash(spec),
      smallest_counterexample: smallest,
      diagnostics,
    }
  }

  return {
    verdict: 'accepted-for-review',
    reason: `all ${criteria.length} criteria satisfied over ${scored.length} applicable cases`,
    criteria,
    outcomes,
    counts,
    declared_protocol: protocol,
    spec_version: spec.spec_version,
    spec_hash: specHash(spec),
    smallest_counterexample: smallest,
    diagnostics,
  }
}
