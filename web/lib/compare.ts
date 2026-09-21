/**
 * Comparison compatibility.
 *
 * A delta between two evaluation runs only means something if you can say what
 * was held fixed. Three different questions get confused otherwise:
 *
 *   - "did my code change make the feed worse?"  needs identical inputs AND an
 *     identical protocol, varying only the revision.
 *   - "is the prototype better than production?" deliberately varies the
 *     algorithm, and must be labelled that way rather than shown as a
 *     regression.
 *   - "did quality move between corpora?" varies the inputs, so per-metric
 *     arrows cannot be attributed to anything.
 *
 * Rather than hide an incompatible pair, the explorer shows it and explains
 * which invariant failed.
 */

import { UNKNOWN, type Artifact } from './artifact'

export type ComparisonKind =
  | 'code-regression'
  | 'algorithm'
  | 'incompatible'

export interface CompatibilityIssue {
  readonly field: string
  readonly severity: 'blocking' | 'caveat'
  readonly message: string
}

export interface Compatibility {
  readonly kind: ComparisonKind
  /** True when per-metric better/worse arrows may be displayed at all. */
  readonly showDirectionalDeltas: boolean
  readonly headline: string
  readonly issues: readonly CompatibilityIssue[]
}

export function assessCompatibility(a: Artifact, b: Artifact): Compatibility {
  const issues: CompatibilityIssue[] = []

  const pa = a.provenance
  const pb = b.provenance

  if (pa.snapshot.name !== pb.snapshot.name) {
    issues.push({
      field: 'snapshot',
      severity: 'blocking',
      message: `These runs used different corpora (${pa.snapshot.name} vs ${pb.snapshot.name}). A metric difference cannot be attributed to the pipeline when the input articles differ.`,
    })
  } else if (
    pa.snapshot.sha256 !== UNKNOWN &&
    pb.snapshot.sha256 !== UNKNOWN &&
    pa.snapshot.sha256 !== pb.snapshot.sha256
  ) {
    issues.push({
      field: 'snapshot.sha256',
      severity: 'blocking',
      message: 'Both runs name the same snapshot but its content hash differs, so the corpora are not actually identical.',
    })
  }

  if (pa.k !== pb.k) {
    issues.push({
      field: 'k',
      severity: 'blocking',
      message: `Different k (${pa.k} vs ${pb.k}). Recall and unwanted-rate are both defined against k, so the two are not the same measurement.`,
    })
  }

  const labelsA = pa.labels
  const labelsB = pb.labels
  if (labelsA && labelsB && labelsA.snapshot === labelsB.snapshot && labelsA.rows !== labelsB.rows) {
    issues.push({
      field: 'labels',
      severity: 'caveat',
      message: `The two runs saw a different number of label rows (${labelsA.rows} vs ${labelsB.rows}) for the same snapshot, so ground truth was not identical.`,
    })
  }

  const sameRunner = pa.runner === pb.runner
  const protocolKnown = pa.protocol !== UNKNOWN && pb.protocol !== UNKNOWN

  if (!protocolKnown) {
    const which =
      pa.protocol === UNKNOWN && pb.protocol === UNKNOWN
        ? 'Neither run'
        : pa.protocol === UNKNOWN
          ? 'The baseline run'
          : 'The comparison run'
    issues.push({
      field: 'protocol',
      severity: 'caveat',
      message: `${which} recorded a protocol identifier — the harness only began emitting one after these scorecards were written. Protocol equality therefore cannot be verified from the artifacts, only assumed from the runner name.`,
    })
  } else if (pa.protocol !== pb.protocol) {
    issues.push({
      field: 'protocol',
      severity: 'caveat',
      message: `Different evaluation protocols (${pa.protocol} vs ${pb.protocol}). This is an algorithm comparison, not a regression check.`,
    })
  }

  if (pa.eval_revision !== UNKNOWN && pa.eval_revision === pb.eval_revision && !sameRunner) {
    issues.push({
      field: 'eval_revision',
      severity: 'caveat',
      message: 'Both runs executed at the same revision, so any difference reflects the two pipelines, not a code change over time.',
    })
  }

  const blocking = issues.some((i) => i.severity === 'blocking')
  if (blocking) {
    return {
      kind: 'incompatible',
      showDirectionalDeltas: false,
      headline: 'These two runs cannot be compared directly.',
      issues,
    }
  }

  if (!sameRunner) {
    return {
      kind: 'algorithm',
      showDirectionalDeltas: true,
      headline: `Algorithm comparison: ${pa.runner} against ${pb.runner}, same corpus and same k.`,
      issues,
    }
  }

  return {
    kind: 'code-regression',
    showDirectionalDeltas: true,
    headline: `Regression check on ${pa.runner}: same corpus, same k, same runner.`,
    issues,
  }
}
