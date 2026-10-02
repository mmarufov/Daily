/** The homepage timeline and verdict share this pinned production execution. */
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { z } from 'zod'
import type { RunStoryData } from './run-story'

export const RECORDED_EXECUTION_ID = 'wrun_01M3WXWPKMF3H8Q66KZA56MZCV' as const
export const RECORDED_EXECUTION_HREF = `/runs/${RECORDED_EXECUTION_ID}.json` as const
export const RECORDED_EXECUTION_SOURCE = `https://marufov.com/api/lab/run/${RECORDED_EXECUTION_ID}` as const

export const ISOLATION_LABELS = {
  'egress-dns': 'DNS lookup fails',
  'egress-https': 'HTTPS request fails',
  'no-evaluator-present': 'Grader not on disk',
  'no-secrets-in-env': 'No credentials in env',
} as const

const stages = [
  'scope checked: only candidate.py is written',
  'creating microVM',
  'uploading 5 files',
  'running the harness',
  'probing isolation',
  'stopping the microVM',
  'microVM stopped',
] as const
const timestamp = z.iso.datetime()
const caseStatuses = ['correct', 'wrong-association', 'should-have-refused', 'should-have-parsed', 'crashed', 'timeout', 'missing-record', 'not-applicable'] as const
const count = z.number().int().nonnegative()
const schema = z.object({
  captured_from: z.literal(RECORDED_EXECUTION_SOURCE),
  captured_at: z.iso.date(),
  preset: z.literal('count-guard-v1'),
  response: z.object({
    run_id: z.literal(RECORDED_EXECUTION_ID),
    status: z.literal('completed'),
    finished: z.literal(true),
    outcome: z.object({
      kind: z.literal('graded'),
      grading: z.object({
        spec_version: z.literal(2),
        spec_hash: z.literal('f027762ab4d08b35'),
        verdict: z.literal('rejected'),
        counts: z.object({
          correct: count,
          'wrong-association': count,
          'should-have-refused': count,
          'should-have-parsed': count,
          crashed: count,
          timeout: count,
          'missing-record': count,
          'not-applicable': count,
        }),
        cases: z.array(z.object({
          case_id: z.string().min(1),
          group: z.enum(['observed', 'synthetic']),
          origin: z.enum(['recorded-replay', 'fault-injection']),
          applicability: z.enum(['scored', 'not-applicable']),
          status: z.enum(caseStatuses),
          observed_refusal_kind: z.string().nullable(),
        })).length(64),
      }),
      sandbox: z.object({
        network_policy: z.literal('deny-all'),
        isolation: z.array(z.object({
          name: z.enum(['egress-dns', 'egress-https', 'no-evaluator-present', 'no-secrets-in-env']),
          expectation: z.string().min(1),
          held: z.boolean(),
        })).length(4),
      }),
    }),
    progress: z.array(z.object({ at: timestamp, stage: z.string() })).length(stages.length),
  }),
}).superRefine((record, context) => {
  const events = record.response.progress
  events.forEach((event, index) => {
    if (event.stage !== stages[index] || (index > 0 && Date.parse(event.at) < Date.parse(events[index - 1]!.at))) {
      context.addIssue({ code: 'custom', path: ['response', 'progress', index], message: 'Expected the complete, ordered recorded execution.' })
    }
  })
  if (new Set(record.response.outcome.sandbox.isolation.map(probe => probe.name)).size !== 4) {
    context.addIssue({ code: 'custom', path: ['response', 'outcome', 'sandbox', 'isolation'], message: 'Each of the four isolation probes must appear once.' })
  }
  const { cases, counts } = record.response.outcome.grading
  const path = ['response', 'outcome', 'grading']
  if (new Set(cases.map(item => item.case_id)).size !== cases.length) {
    context.addIssue({ code: 'custom', path: [...path, 'cases'], message: 'Recorded case IDs must be unique.' })
  }
  for (const status of caseStatuses) {
    if (counts[status] !== cases.filter(item => item.status === status).length) {
      context.addIssue({ code: 'custom', path: [...path, 'counts', status], message: 'The count must match its recorded case results.' })
    }
  }
  if (cases.some(item =>
    (item.group === 'synthetic') !== (item.origin === 'fault-injection') ||
    (item.status === 'not-applicable') !== (item.applicability === 'not-applicable'),
  ) || cases.filter(item => item.origin === 'fault-injection').length !== 22) {
    context.addIssue({ code: 'custom', path: [...path, 'cases'], message: 'Case origins and applicability must match the recorded suite.' })
  }
  const failure = cases.find(item => item.case_id === 'syn-positional-reordered')
  if (failure?.status !== 'should-have-refused' || failure.observed_refusal_kind !== null || failure.origin !== 'fault-injection') {
    context.addIssue({ code: 'custom', path: [...path, 'cases'], message: 'The recorded reordered-verdict failure is required.' })
  }
})

export type RecordedExecution = z.infer<typeof schema>

export function parseRecordedExecution(input: unknown): RecordedExecution | null {
  const result = schema.safeParse(input)
  return result.success ? result.data : null
}

export async function loadRecordedExecution(
  file = join(process.cwd(), 'public', RECORDED_EXECUTION_HREF),
): Promise<RecordedExecution | null> {
  try {
    return parseRecordedExecution(JSON.parse(await readFile(file, 'utf8')) as unknown)
  } catch {
    return null
  }
}

export function executionElapsed(at: string, origin: string): string {
  return ((Date.parse(at) - Date.parse(origin)) / 1000).toFixed(2)
}

export function deriveRunStory(execution: RecordedExecution | null): RunStoryData | null {
  if (execution === null) return null
  const { progress, outcome, run_id: runId } = execution.response
  const { grading, sandbox } = outcome
  const date = progress[0]!.at
  return {
    runId,
    preset: execution.preset,
    date,
    sourceHref: RECORDED_EXECUTION_HREF,
    specVersion: grading.spec_version,
    specHash: grading.spec_hash,
    events: progress.map(event => ({ stage: event.stage, elapsed: executionElapsed(event.at, date) })),
    probes: sandbox.isolation.map(probe => ({ name: probe.name, label: ISOLATION_LABELS[probe.name], held: probe.held })),
    cases: grading.cases.map(item => ({
      id: item.case_id,
      status: item.status === 'correct' || item.status === 'not-applicable' ? item.status : 'failed',
    })),
    counts: {
      total: grading.cases.length,
      correct: grading.counts.correct,
      failed: grading.cases.length - grading.counts.correct - grading.counts['not-applicable'],
      notApplicable: grading.counts['not-applicable'],
      faultInjected: grading.cases.filter(item => item.origin === 'fault-injection').length,
    },
    failure: { id: 'syn-positional-reordered', summary: 'Reordered verdicts passed the count check.' },
  }
}
