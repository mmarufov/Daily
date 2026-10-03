import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { PUBLIC_RUN_LIMITS } from '@/lib/lab/public-limits'

/**
 * The production burst behind the README's admission claim, pinned.
 *
 * On 2026-10-01 at 23:48Z, 12 parallel POSTs to marufov.com/api/lab/run came
 * from one address that had 3 runs in its rolling hour. The file is the raw
 * capture: every response with its `X-Lab-Instance`, the address's Redis
 * entries before and after, and the two admitted runs' sandbox reports.
 */

interface Burst {
  before: { my_address_entries: string[] }
  results: { status: number; instance: string; body: { limit?: string } }[]
  finished: { verdict: string; sandbox: { network_policy: string; isolation: { held: boolean }[] } }[]
}

const BURST: Burst = JSON.parse(
  readFileSync(join(process.cwd(), 'results', 'lab-admission-burst-2026-10-01.json'), 'utf8'),
)

function summarize(burst: Burst) {
  // Each run is stored as a pair: its id and its start time.
  const usedBefore = burst.before.my_address_entries.length / 2
  const admitted = burst.results.filter((r) => r.status === 202).length
  return {
    requests: burst.results.length,
    instances: new Set(burst.results.map((r) => r.instance)).size,
    remainingBefore: PUBLIC_RUN_LIMITS.per_address.runs - usedBefore,
    admitted,
    refusedPerAddress: burst.results.filter((r) => r.status === 429 && r.body.limit === 'per-address').length,
    admittedExactlyRemaining: admitted === PUBLIC_RUN_LIMITS.per_address.runs - usedBefore,
  }
}

describe('the 2026-10-01 production admission burst', () => {
  it('spread 12 requests over 12 function instances and admitted exactly the 2 runs left', () => {
    expect(summarize(BURST)).toEqual({
      requests: 12,
      instances: 12,
      remainingBefore: 2,
      admitted: 2,
      refusedPerAddress: 10,
      admittedExactlyRemaining: true,
    })
  })

  it('ran both admitted candidates with networking denied and every isolation probe held', () => {
    expect(BURST.finished).toHaveLength(2)
    for (const run of BURST.finished) {
      expect(run.sandbox.network_policy).toBe('deny-all')
      expect(run.sandbox.isolation).toHaveLength(4)
      expect(run.sandbox.isolation.every((probe) => probe.held)).toBe(true)
    }
  })

  it('control: one more admission breaks the claim', () => {
    const doctored = structuredClone(BURST)
    const refused = doctored.results.find((r) => r.status === 429)!
    refused.status = 202
    expect(summarize(doctored).admittedExactlyRemaining).toBe(false)
  })

  it('control: a burst on one instance is not a cross-instance result', () => {
    const doctored = structuredClone(BURST)
    for (const r of doctored.results) r.instance = 'one'
    expect(summarize(doctored).instances).toBe(1)
  })
})
