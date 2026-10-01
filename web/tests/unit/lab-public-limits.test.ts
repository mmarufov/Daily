/**
 * The public runner's limits, exercised rather than asserted.
 *
 * Every test here drives the real request handler and the real admission
 * code against a store that implements the Redis commands they send, with
 * the semantics Redis gives them: sorted sets, counters and expiry on a clock
 * the test controls. A limiter that only *exists* passes a test that checks
 * for its presence. These check that the sixth request is refused, that the
 * refusal says why and until when, and that the request after the reset is
 * admitted again.
 */

import { describe, expect, it } from 'vitest'

import type { WorkflowInput } from '@/lib/lab/orchestration'
import {
  addressBucket,
  PUBLIC_RUN_LIMITS,
  PublicRunGate,
  releaseRun,
  UNMETERED_RUN_CPU_MS,
  upstashStore,
  type Command,
  type LimitStore,
} from '@/lib/lab/public-limits'
import { handleRunRequest, MAX_SOURCE_BYTES } from '@/lib/lab/public-run'

/* ------------------------------------------------------ a fake Redis --- */

class FakeRedis implements LimitStore {
  readonly zsets = new Map<string, Map<string, number>>()
  readonly strings = new Map<string, string>()
  readonly expiry = new Map<string, number>()
  transactions = 0
  failing = false

  constructor(private readonly now: () => number) {}

  async exec(commands: readonly Command[]): Promise<readonly unknown[]> {
    if (this.failing) throw new Error('connection refused')
    this.transactions += 1
    // One synchronous pass: nothing interleaves, which is what MULTI promises.
    return commands.map((c) => this.run(c.map(String)))
  }

  private alive(key: string): void {
    const at = this.expiry.get(key)
    if (at !== undefined && this.now() >= at) {
      this.zsets.delete(key)
      this.strings.delete(key)
      this.expiry.delete(key)
    }
  }

  private zset(key: string): Map<string, number> {
    this.alive(key)
    let z = this.zsets.get(key)
    if (z === undefined) {
      z = new Map()
      this.zsets.set(key, z)
    }
    return z
  }

  private run([name, key = '', ...args]: string[]): unknown {
    switch (name) {
      case 'ZREMRANGEBYSCORE': {
        const z = this.zset(key)
        const min = args[0] === '-inf' ? -Infinity : Number(args[0])
        const max = Number(args[1])
        let removed = 0
        for (const [m, s] of z) if (s >= min && s <= max) (z.delete(m), (removed += 1))
        return removed
      }
      case 'ZADD': {
        const z = this.zset(key)
        const fresh = !z.has(args[1] as string)
        z.set(args[1] as string, Number(args[0]))
        return fresh ? 1 : 0
      }
      case 'ZCARD':
        return this.zset(key).size
      case 'ZRANGE': {
        const sorted = [...this.zset(key)].sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0]))
        const [lo, hi] = [Number(args[0]), Number(args[1])]
        return sorted.slice(lo, hi + 1).flatMap(([m, s]) => [m, String(s)])
      }
      case 'ZREM':
        return this.zset(key).delete(args[0] as string) ? 1 : 0
      case 'PEXPIRE':
        this.expiry.set(key, this.now() + Number(args[0]))
        return 1
      case 'EXPIRE':
        this.expiry.set(key, this.now() + Number(args[0]) * 1000)
        return 1
      case 'INCR':
      case 'DECR':
      case 'INCRBY': {
        this.alive(key)
        const by = name === 'INCR' ? 1 : name === 'DECR' ? -1 : Number(args[0])
        const next = Number(this.strings.get(key) ?? '0') + by
        this.strings.set(key, String(next))
        return next
      }
      case 'GET':
        this.alive(key)
        return this.strings.get(key) ?? null
      default:
        throw new Error(`the fake does not implement ${name}`)
    }
  }
}

/* --------------------------------------------------------- harness --- */

const T0 = Date.parse('2026-10-01T10:00:00.000Z')
const MINUTE = 60_000
const HOUR = 60 * MINUTE
const SOURCE = 'def parse(articles, response):\n    return {"ok": False, "refusal": {"kind": "x"}}\n'

function harness(options: { store?: boolean; env?: Record<string, string> } = {}) {
  let now = T0
  const redis = new FakeRedis(() => now)
  const started: WorkflowInput[] = []
  let startFails = false
  const gate = options.store === false ? null : new PublicRunGate(redis)

  const post = async (address: string, body: Record<string, unknown> = {}, headers: Record<string, string> = {}) => {
    const request = new Request('https://marufov.com/api/lab/run', {
      method: 'POST',
      headers: { 'content-type': 'application/json', 'x-real-ip': address, ...headers },
      body: JSON.stringify({ candidate_id: 'visitor', source: SOURCE, ...body }),
    })
    const response = await handleRunRequest(request, {
      gate,
      now: () => now,
      env: options.env ?? {},
      start: async (input) => {
        if (startFails) throw new Error('queue unavailable')
        started.push(input)
        return { runId: `wrun_${started.length}` }
      },
    })
    return { status: response.status, headers: response.headers, body: (await response.json()) as Record<string, unknown> }
  }

  /** What the workflow's `releaseStep` does when a run ends. */
  const finish = async (input: WorkflowInput, cpuMs: number | null = 2_000) =>
    releaseRun(redis, { slot: input.slot, day: input.day, cpu_ms: cpuMs })

  return {
    redis,
    started,
    post,
    finish,
    at: (ms: number) => {
      now = ms
    },
    failStart: () => {
      startFails = true
    },
  }
}

const runsToday = (h: ReturnType<typeof harness>) => Number(h.redis.strings.get('lab:public:runs:2026-10-01') ?? '0')

/* ----------------------------------------------------------- tests --- */

describe('per address: 5 runs in any rolling hour', () => {
  it('refuses the sixth run, says when, and admits the next one after that moment', async () => {
    const h = harness()
    for (let i = 0; i < 5; i += 1) {
      h.at(T0 + i * MINUTE)
      const ok = await h.post('203.0.113.7')
      expect(ok.status, `run ${i + 1}`).toBe(202)
      expect(ok.body.address_runs_left).toBe(4 - i)
      await h.finish(h.started[i] as WorkflowInput)
    }

    h.at(T0 + 10 * MINUTE)
    const refused = await h.post('203.0.113.7')
    expect(refused.status).toBe(429)
    expect(refused.body.limit).toBe('per-address')
    expect(refused.body.allowed).toBe(5)
    expect(refused.body.used).toBe(5)
    // The oldest of the five ages out an hour after it started.
    expect(refused.body.resets_at).toBe(new Date(T0 + HOUR).toISOString())
    expect(refused.body.retry_after_seconds).toBe(50 * 60)
    expect(refused.headers.get('retry-after')).toBe(String(50 * 60))
    expect(refused.body.error).toMatch(/started 5 runs in the last hour/)
    expect(refused.body.error).toMatch(/11:00 UTC/)
    expect(h.started).toHaveLength(5)

    // A different address is not affected.
    expect((await h.post('198.51.100.1')).status).toBe(202)

    // One millisecond before the reset it is still refused; at it, admitted.
    h.at(T0 + HOUR - 1)
    expect((await h.post('203.0.113.7')).status).toBe(429)
    h.at(T0 + HOUR)
    expect((await h.post('203.0.113.7')).status).toBe(202)
  })

  it('treats every address in one IPv6 /64 as one visitor', async () => {
    expect(addressBucket('2001:db8:1:2:aaaa::1')).toBe(addressBucket('2001:0db8:0001:0002:bbbb:0:0:2'))
    expect(addressBucket('2001:db8:1:2::1')).not.toBe(addressBucket('2001:db8:1:3::1'))
    expect(addressBucket('::ffff:192.0.2.9')).toBe('192.0.2.9')
    expect(addressBucket(null)).toBe('unknown')

    const h = harness()
    for (let i = 0; i < 5; i += 1) {
      expect((await h.post(`2001:db8:1:2::${i + 1}`)).status).toBe(202)
      await h.finish(h.started[i] as WorkflowInput)
    }
    const rotated = await h.post('2001:db8:1:2:ffff:ffff:ffff:ffff')
    expect(rotated.status).toBe(429)
    expect(rotated.body.limit).toBe('per-address')
  })

  it('counts requests with no address together, rather than not at all', async () => {
    const h = harness()
    const statuses: number[] = []
    for (let i = 0; i < 6; i += 1) {
      statuses.push((await h.post('')).status)
      const last = h.started[h.started.length - 1]
      if (last !== undefined) await h.finish(last)
    }
    expect(statuses).toEqual([202, 202, 202, 202, 202, 429])
  })
})

describe('at once: 3 runs executing across every visitor', () => {
  it('refuses a fourth while three hold slots, and admits it once one finishes', async () => {
    const h = harness()
    for (const address of ['192.0.2.1', '192.0.2.2', '192.0.2.3']) {
      expect((await h.post(address)).status).toBe(202)
    }
    h.at(T0 + 5_000)
    const refused = await h.post('192.0.2.4')
    expect(refused.status).toBe(429)
    expect(refused.body.limit).toBe('concurrent')
    expect(refused.body.used).toBe(3)
    // No later than the first slot's lease, if nothing finishes first.
    expect(refused.body.resets_at).toBe(new Date(T0 + PUBLIC_RUN_LIMITS.lease_seconds * 1000).toISOString())
    expect(refused.body.error).toMatch(/3 runs are already executing/)

    await h.finish(h.started[1] as WorkflowInput)
    expect((await h.post('192.0.2.4')).status).toBe(202)
    expect(h.started).toHaveLength(4)
  })

  it('frees a slot whose run never released it once the lease expires', async () => {
    const h = harness()
    for (const address of ['192.0.2.1', '192.0.2.2', '192.0.2.3']) await h.post(address)
    h.at(T0 + PUBLIC_RUN_LIMITS.lease_seconds * 1000 - 1)
    expect((await h.post('192.0.2.9')).status).toBe(429)
    h.at(T0 + PUBLIC_RUN_LIMITS.lease_seconds * 1000)
    expect((await h.post('192.0.2.9')).status).toBe(202)
  })
})

describe('per UTC day: 50 runs, and 20 minutes of metered microVM CPU', () => {
  it('refuses the 51st run of the day until midnight UTC, then admits again', async () => {
    const h = harness()
    for (let i = 0; i < PUBLIC_RUN_LIMITS.runs_per_day; i += 1) {
      h.at(T0 + i * 1000)
      expect((await h.post(`10.0.${Math.floor(i / 200)}.${i % 200}`)).status).toBe(202)
      await h.finish(h.started[i] as WorkflowInput, 100)
    }
    const over = await h.post('172.16.0.1')
    expect(over.status).toBe(429)
    expect(over.body.limit).toBe('daily-runs')
    expect(over.body.used).toBe(50)
    expect(over.body.resets_at).toBe('2026-10-02T00:00:00.000Z')
    expect(over.body.error).toMatch(/50 runs have started today across every visitor/)

    h.at(Date.parse('2026-10-02T00:00:00.000Z'))
    expect((await h.post('172.16.0.1')).status).toBe(202)
  })

  it('refuses once the day has used its CPU allowance, counting an unmetered run at its worst case', async () => {
    expect(UNMETERED_RUN_CPU_MS).toBe(240_000)
    const h = harness()
    // Five runs the platform never metered: 5 x 240 s is the 20-minute allowance.
    for (let i = 0; i < 5; i += 1) {
      expect((await h.post(`192.0.2.${i + 10}`)).status).toBe(202)
      await h.finish(h.started[i] as WorkflowInput, null)
    }
    const over = await h.post('192.0.2.99')
    expect(over.status).toBe(429)
    expect(over.body.limit).toBe('daily-cpu')
    expect(over.body.unit).toBe('cpu-ms')
    expect(over.body.used).toBe(PUBLIC_RUN_LIMITS.cpu_ms_per_day)
    expect(over.body.resets_at).toBe('2026-10-02T00:00:00.000Z')
    expect(over.body.error).toMatch(/20 minutes of microVM CPU/)
  })

  it('charges the measured CPU when the platform reported it', async () => {
    const h = harness()
    await h.post('192.0.2.1')
    await h.finish(h.started[0] as WorkflowInput, 3_412)
    expect(h.redis.strings.get('lab:public:cpu:2026-10-01')).toBe('3412')
  })
})

describe('a refusal costs nothing and says the truth', () => {
  it('leaves every counter where it was, and repeats from memory without asking the store', async () => {
    const h = harness()
    for (let i = 0; i < 5; i += 1) {
      await h.post('203.0.113.7')
      await h.finish(h.started[i] as WorkflowInput)
    }
    const before = { runs: runsToday(h), transactions: h.redis.transactions }
    expect((await h.post('203.0.113.7')).status).toBe(429)
    expect(runsToday(h)).toBe(before.runs)
    expect(h.redis.zsets.get('lab:public:active')?.size ?? 0).toBe(0)

    const afterFirst = h.redis.transactions
    for (let i = 0; i < 20; i += 1) {
      const again = await h.post('203.0.113.7')
      expect(again.status).toBe(429)
      expect(again.body.limit).toBe('per-address')
    }
    // Twenty more refusals, no more transactions: the refusal cannot change
    // before it resets, so the store is not asked again.
    expect(h.redis.transactions).toBe(afterFirst)
    expect(afterFirst - before.transactions).toBe(2) // reserve, then refund
  })

  it('reports the limit that resets last when several are exceeded', async () => {
    const h = harness()
    // Two runs that finish, then three that are still executing: the address
    // is at its 5 and every slot is held.
    for (let i = 0; i < 5; i += 1) {
      await h.post('203.0.113.7')
      if (i < 2) await h.finish(h.started[i] as WorkflowInput)
    }
    expect(h.started).toHaveLength(5)
    const refused = await h.post('203.0.113.7')
    expect(refused.status).toBe(429)
    // Concurrent would reset within five minutes, the address in an hour.
    // Pointing at the earlier one would send the visitor back to be refused.
    expect(refused.body.limit).toBe('per-address')
  })

  it('refunds the reservation when the run cannot be started', async () => {
    const h = harness()
    h.failStart()
    const failed = await h.post('192.0.2.1')
    expect(failed.status).toBe(503)
    expect(failed.body.error).toMatch(/nothing was counted against you/)
    expect(runsToday(h)).toBe(0)
    expect(h.redis.zsets.get('lab:public:active')?.size ?? 0).toBe(0)
  })
})

describe('fails closed', () => {
  it('starts nothing when no counter store is configured', async () => {
    const h = harness({ store: false })
    const closed = await h.post('192.0.2.1')
    expect(closed.status).toBe(503)
    expect(closed.body.error).toMatch(/closed on this deployment/)
    expect(h.started).toHaveLength(0)
  })

  it('starts nothing when the store does not answer', async () => {
    const h = harness()
    h.redis.failing = true
    const down = await h.post('192.0.2.1')
    expect(down.status).toBe(503)
    expect(h.started).toHaveLength(0)
  })

  it('refuses an oversized or out-of-scope source before touching a counter', async () => {
    const h = harness()
    const tooLong = await h.post('192.0.2.1', { source: 'x'.repeat(MAX_SOURCE_BYTES + 1) })
    expect(tooLong.status).toBe(400)
    // Under 64 K characters, over 64 KB: the scope gate counts bytes.
    const tooHeavy = await h.post('192.0.2.1', { source: 'é'.repeat(40_000) })
    expect(tooHeavy.status).toBe(422)
    expect(String(tooHeavy.body.error)).toMatch(/^too-large/)
    const badId = await h.post('192.0.2.1', { candidate_id: '../evaluator' })
    expect(badId.status).toBe(400)
    expect(h.redis.transactions).toBe(0)
    expect(h.started).toHaveLength(0)
  })
})

describe('suspension is the owner’s alone', () => {
  it('ignores suspend_seconds from a visitor and honours it for the owner', async () => {
    const visitor = harness({ env: { LAB_OWNER_TOKEN: 'correct-horse' } })
    const v = await visitor.post('192.0.2.1', { suspend_seconds: 300 })
    expect(v.status).toBe(202)
    expect(v.body.suspend_seconds).toBe(0)
    expect(visitor.started[0]?.suspend_seconds).toBe(0)

    const owner = harness({ env: { LAB_OWNER_TOKEN: 'correct-horse' } })
    const o = await owner.post('192.0.2.1', { suspend_seconds: 90 }, { authorization: 'Bearer correct-horse' })
    expect(o.body.suspend_seconds).toBe(90)
    // A suspended run holds its slot for the whole sleep, so its lease is longer.
    const lease = [...(owner.redis.zsets.get('lab:public:active') ?? new Map()).values()][0]
    expect(lease).toBe(T0 + (PUBLIC_RUN_LIMITS.lease_seconds + 90) * 1000)
  })
})

describe('the Upstash store', () => {
  it('is absent, not broken, when unconfigured', () => {
    expect(upstashStore({})).toBeNull()
    expect(upstashStore({ KV_REST_API_URL: 'https://x.upstash.io' })).toBeNull()
  })

  it('sends one transaction to /multi-exec and returns results in order', async () => {
    const calls: { url: string; init: RequestInit }[] = []
    const fetchImpl = (async (url: string, init: RequestInit) => {
      calls.push({ url, init })
      return Response.json([{ result: 1 }, { result: ['a', '5'] }, { result: null }])
    }) as unknown as typeof fetch
    const store = upstashStore({ KV_REST_API_URL: 'https://x.upstash.io/', KV_REST_API_TOKEN: 't0ken' }, fetchImpl)
    const out = await store?.exec([['INCR', 'k'], ['ZRANGE', 'z', 0, 0, 'WITHSCORES'], ['GET', 'g']])
    expect(out).toEqual([1, ['a', '5'], null])
    expect(calls[0]?.url).toBe('https://x.upstash.io/multi-exec')
    expect((calls[0]?.init.headers as Record<string, string>).authorization).toBe('Bearer t0ken')
    expect(JSON.parse(String(calls[0]?.init.body))).toEqual([['INCR', 'k'], ['ZRANGE', 'z', '0', '0', 'WITHSCORES'], ['GET', 'g']])
  })

  it('throws on a refused command or a failed response, so the route fails closed', async () => {
    const refusing = (async () => Response.json([{ error: 'ERR wrong type' }])) as unknown as typeof fetch
    await expect(
      upstashStore({ KV_REST_API_URL: 'https://x', KV_REST_API_TOKEN: 't' }, refusing)?.exec([['INCR', 'k']]),
    ).rejects.toThrow(/refused a command/)
    const down = (async () => new Response('', { status: 401 })) as unknown as typeof fetch
    await expect(
      upstashStore({ KV_REST_API_URL: 'https://x', KV_REST_API_TOKEN: 't' }, down)?.exec([['INCR', 'k']]),
    ).rejects.toThrow(/answered 401/)
  })
})
