/**
 * Where a candidate is allowed to execute.
 *
 * Two runners, and the difference between them is a security boundary rather
 * than a convenience:
 *
 *   `local-known`   — a subprocess on this machine. Permitted ONLY for
 *                     implementations that are committed to this repository and
 *                     whose bytes hash to a value recorded here. That is what
 *                     makes it safe: nothing novel ever runs locally.
 *   `vercel-sandbox`— an isolated microVM with the network disabled, pinned to
 *                     a base image, bounded in time and output, holding no
 *                     production secret. Everything else goes here.
 *
 * `selectRunner` is the single decision point, and it fails closed: an unknown
 * hash cannot be talked into `local-known` by any argument, including "it is
 * probably fine" or "the sandbox is unavailable". If the sandbox cannot run,
 * the correct outcome is an `incomplete` run, not a local execution.
 */

import { createHash } from 'node:crypto'

export type RunnerKind = 'local-known' | 'vercel-sandbox'

export interface KnownImplementation {
  readonly candidate_id: string
  readonly path: string
  readonly kind: 'preserved-version' | 'seeded-control'
  readonly description: string
  readonly declared_protocol: 'positional-v0' | 'keyed-v2'
  readonly transcribed_from: string
}

/**
 * Every implementation that may run outside the sandbox.
 *
 * Deliberately a hand-maintained list in trusted code rather than a directory
 * scan: dropping a file into `contract/` must not grant it local execution.
 */
export const KNOWN_IMPLEMENTATIONS: readonly KnownImplementation[] = [
  {
    candidate_id: 'positional-v0',
    path: 'backend/lab/contract/versions/positional_v0.py',
    kind: 'preserved-version',
    description:
      'Historical behaviour: associates results[i] with articles[i] and pads the tail. This is what production does today.',
    declared_protocol: 'positional-v0',
    transcribed_from: 'origin/main:backend/app/services/openai_service.py',
  },
  {
    candidate_id: 'count-guard-v1',
    path: 'backend/lab/contract/versions/count_guard_v1.py',
    kind: 'preserved-version',
    description:
      'PR #59: discards the batch when the verdict count differs from the article count, and lets CacheMiss and BudgetExceeded propagate.',
    declared_protocol: 'positional-v0',
    transcribed_from: '81b20198:backend/app/services/openai_service.py',
  },
  {
    candidate_id: 'keyed-v2',
    path: 'backend/lab/contract/versions/keyed_v2.py',
    kind: 'preserved-version',
    description:
      'Proposed contract: every verdict names its article, the id set must match exactly, and a non-stop finish_reason is a failure.',
    declared_protocol: 'keyed-v2',
    transcribed_from: 'modelled on backend/app/services/ranking_contract.py:131',
  },
  {
    candidate_id: 'control-lenient-keyed',
    path: 'backend/lab/contract/controls/lenient_keyed.py',
    kind: 'seeded-control',
    description:
      'SEEDED DEFECT: keeps the last verdict when an article is judged twice, drops unknown ids silently, and coerces unusable scores to 0.0.',
    declared_protocol: 'keyed-v2',
    transcribed_from: 'unknown',
  },
  {
    candidate_id: 'control-self-reporting',
    path: 'backend/lab/contract/controls/self_reporting.py',
    kind: 'seeded-control',
    description:
      'SEEDED DEFECT: fabricates a complete association for every case and decorates it with passed/score/all_tests_green. Exists to prove a candidate cannot grade itself.',
    declared_protocol: 'keyed-v2',
    transcribed_from: 'unknown',
  },
  {
    candidate_id: 'control-zero-filling',
    path: 'backend/lab/contract/controls/zero_filling.py',
    kind: 'seeded-control',
    description:
      'SEEDED DEFECT: turns every failure, including a missing recording, into a confident all-zero answer. This is the blanket except Exception on the production path.',
    declared_protocol: 'positional-v0',
    transcribed_from: 'unknown',
  },
]

export function sha256(text: string): string {
  return createHash('sha256').update(text).digest('hex')
}

export interface RunnerDecision {
  readonly runner: RunnerKind
  readonly reason: string
  readonly known: KnownImplementation | null
}

/**
 * Decide where a candidate runs, from its bytes alone.
 *
 * `knownHashes` maps candidate_id to the sha256 of the committed source. A
 * candidate matches only if its content hashes to one of those values — the
 * path it claims is not evidence of anything.
 */
export function selectRunner(
  source: string,
  knownHashes: ReadonlyMap<string, string>,
): RunnerDecision {
  const digest = sha256(source)
  for (const implementation of KNOWN_IMPLEMENTATIONS) {
    if (knownHashes.get(implementation.candidate_id) === digest) {
      return {
        runner: 'local-known',
        reason: `bytes match the committed ${implementation.candidate_id}`,
        known: implementation,
      }
    }
  }
  return {
    runner: 'vercel-sandbox',
    reason: 'source does not match any committed implementation, so it is treated as untrusted',
    known: null,
  }
}

/** Limits applied to a sandboxed run. Recorded in the artifact. */
export interface SandboxLimits {
  readonly image: string
  readonly network: 'disabled'
  readonly wall_clock_seconds: number
  readonly max_output_bytes: number
  readonly dependencies: 'none — the candidate is a single stdlib-only file'
  readonly secrets: 'none'
}

export const SANDBOX_LIMITS: SandboxLimits = {
  image: 'python3.13',
  network: 'disabled',
  wall_clock_seconds: 120,
  max_output_bytes: 4 * 1024 * 1024,
  dependencies: 'none — the candidate is a single stdlib-only file',
  secrets: 'none',
}
