/**
 * A live run's outcome, built from committed evidence rather than typed in.
 *
 * The e2e tests cannot start a microVM, so they replay what the status route
 * would return. Writing that payload by hand would be inventing a result on
 * a site whose claim is that it invents none. This grades a committed record
 * bundle with the real evaluator and summarises it with the real
 * `summariseGrading`, so the fixture is whatever the code says it is.
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { evaluate } from '../../lib/lab/evaluator'
import { summariseGrading, type LiveGrading } from '../../lib/lab/live'
import { parseCaseSuite, parseRecordBundle, type Case } from '../../lib/lab/records'

const BACKEND = join(__dirname, '..', '..', '..', 'backend', 'lab')

export function committedCases(): Case[] {
  return (['observed', 'synthetic'] as const).flatMap((group) => {
    const parsed = parseCaseSuite(JSON.parse(readFileSync(join(BACKEND, 'cases', `${group}.json`), 'utf8')))
    if (!parsed.ok) throw new Error(`${group}: ${parsed.issues.join('; ')}`)
    return parsed.value.cases
  })
}

export function gradeCommitted(records: 'count-guard-v1' | 'keyed-v2' | 'positional-v0'): LiveGrading {
  const cases = committedCases()
  const bundle = parseRecordBundle(JSON.parse(readFileSync(join(BACKEND, 'records', `${records}.json`), 'utf8')))
  if (!bundle.ok) throw new Error(`${records}: ${bundle.issues.join('; ')}`)
  return summariseGrading(evaluate(cases, bundle.value), cases)
}

/** The body `GET /api/lab/run/[runId]` returns for a finished, graded run. */
export function finishedRunBody(runId: string, records: 'count-guard-v1' | 'keyed-v2' | 'positional-v0') {
  const grading = gradeCommitted(records)
  return {
    run_id: runId,
    status: 'completed',
    finished: true,
    progress: [],
    outcome: {
      kind: grading.verdict === 'incomplete' || grading.verdict === 'failed' ? 'incomplete' : 'graded',
      verdict: grading.verdict,
      reason: grading.reason,
      detail: grading.reason,
      grading,
      // These bundles ran on the local path, so there is no microVM to report,
      // and the page must say so rather than show a zero.
      sandbox: null,
      events: [],
      processes: [],
      resumed: false,
    },
  }
}
