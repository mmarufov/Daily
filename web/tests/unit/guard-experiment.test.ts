import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { parseGuardExperiment } from '../../lib/guard-experiment'

/**
 * The September 21 experiment is the only source for "the fix made the
 * numbers worse". These keep its limits explicit and its inputs checkable.
 */
const experiment = JSON.parse(readFileSync('public/experiments/batch-alignment.json', 'utf8'))

describe('the recorded guard experiment', () => {
  it('keeps the recorded results and their historical limits explicit', () => {
    expect(parseGuardExperiment(experiment).ok).toBe(true)
    expect(experiment.original.summary.recall_at_k_mean).toBe(0.2207)
    expect(experiment.guard.summary.recall_at_k_mean).toBe(0.1866)
    expect(experiment.guard.summary.never_rate_mean).toBe(0.425)
    expect(experiment.scope).toBe('historical-working-tree-experiment')
    expect(experiment.historical_test_result).toMatchObject({ failed: 6, baseline_re_recorded: false })
    expect(experiment.guard.revision_is_guard_commit).toBe(false)
    expect(experiment.guard.implementation_sha256).toBeNull()
  })

  it('identifies committed reference inputs and the original scorecard by their bytes', () => {
    const files = [experiment.original.source, ...experiment.input_provenance.reference_files] as {
      path: string
      sha256: string
    }[]
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
