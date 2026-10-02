/** Pinned production execution, separate from the published spec 1 result. */
import { readFile } from 'node:fs/promises'
import { join } from 'node:path'
import { z } from 'zod'

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
        verdict: z.enum(['accepted-for-review', 'rejected']),
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
