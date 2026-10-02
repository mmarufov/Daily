/**
 * Shared Redis transactions reserve capacity before admission and refund refusals.
 * Concurrent reservations can conservatively refuse a request. An unavailable store
 * closes admission; CPU limits use the platform's metered units.
 */

import { createHash } from 'node:crypto'

import { SANDBOX_LIMITS, SANDBOX_VCPUS } from './runner'

export const PUBLIC_RUN_LIMITS = {
  per_address: { runs: 5, window_seconds: 60 * 60 },
  concurrent_runs: 3,
  runs_per_day: 50,
  cpu_ms_per_day: 20 * 60 * 1000,
  /** Lease expiry frees a slot when workflow cleanup never runs. */
  lease_seconds: 300,
} as const

/** Unmetered attempts are charged for every vCPU over the maximum sandbox lifetime. */
export const UNMETERED_RUN_CPU_MS = SANDBOX_VCPUS * SANDBOX_LIMITS.wall_clock_seconds * 1000

export type LimitId = 'per-address' | 'concurrent' | 'daily-runs' | 'daily-cpu'

export interface Refusal {
  readonly limit: LimitId
  /** The configured ceiling, in `unit`. */
  readonly allowed: number
  /** Count clamped to the run ceiling because concurrent reservations may still be refunded. */
  readonly used: number
  readonly unit: 'runs' | 'cpu-ms'
  /** The earliest moment a retry can succeed against this limit. */
  readonly resets_at: string
  readonly retry_after_seconds: number
  readonly error: string
}

export type Admission =
  | { readonly ok: true; readonly slot: string; readonly day: string; readonly address_runs_left: number }
  | { readonly ok: false; readonly refusal: Refusal }

/** Vercel supplies x-real-ip. Requests without it share one conservative bucket. */
export function clientAddress(headers: Headers): string | null {
  const raw = (headers.get('x-real-ip') ?? '').trim()
  return raw === '' ? null : raw
}

/** Group IPv6 by /64 to prevent one subscriber rotating through addresses to bypass the limit. */
export function addressBucket(address: string | null): string {
  if (address === null) return 'unknown'
  const value = address.toLowerCase()
  if (!value.includes(':')) return value
  const mapped = /^::ffff:(\d{1,3}(?:\.\d{1,3}){3})$/.exec(value)
  if (mapped !== null) return mapped[1] as string
  const groups = expandIpv6(value)
  return groups === null ? value : `${groups.slice(0, 4).join(':')}::/64`
}

function expandIpv6(value: string): string[] | null {
  const [head, tail, extra] = value.split('::')
  if (extra !== undefined) return null
  const left = head === undefined || head === '' ? [] : head.split(':')
  const right = tail === undefined ? null : tail === '' ? [] : tail.split(':')
  const fill = right === null ? 0 : 8 - left.length - right.length
  if (fill < 0) return null
  const groups = [...left, ...Array.from({ length: fill }, () => '0'), ...(right ?? [])]
  if (groups.length !== 8 || groups.some((g) => !/^[0-9a-f]{1,4}$/.test(g))) return null
  return groups.map((g) => g.replace(/^0+(?=.)/, ''))
}

/** IPv4 hashes can be reversed by enumeration. TTL limits retention to the rate-limit window. */
export function addressKey(bucket: string): string {
  return createHash('sha256').update(`lab-public-address:${bucket}`).digest('hex').slice(0, 32)
}

export type Command = readonly (string | number)[]

/** Commands execute atomically and results preserve command order. */
export interface LimitStore {
  exec(commands: readonly Command[]): Promise<readonly unknown[]>
}

/** Read credentials lazily so imports work during builds without deployment credentials. */
export function upstashStore(
  env: Readonly<Record<string, string | undefined>> = process.env,
  fetchImpl: typeof fetch = fetch,
): LimitStore | null {
  const url = (env.KV_REST_API_URL ?? env.UPSTASH_REDIS_REST_URL ?? '').trim().replace(/\/+$/, '')
  const token = (env.KV_REST_API_TOKEN ?? env.UPSTASH_REDIS_REST_TOKEN ?? '').trim()
  if (url === '' || token === '') return null
  return {
    async exec(commands) {
      const response = await fetchImpl(`${url}/multi-exec`, {
        method: 'POST',
        headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
        body: JSON.stringify(commands.map((c) => c.map(String))),
        signal: AbortSignal.timeout(5_000),
      })
      if (!response.ok) throw new Error(`the counter store answered ${response.status}`)
      const body = (await response.json()) as unknown
      if (!Array.isArray(body) || body.length !== commands.length) {
        throw new Error('the counter store returned a transaction of the wrong shape')
      }
      return body.map((entry: unknown) => {
        const e = entry as { result?: unknown; error?: unknown }
        if (typeof e?.error === 'string') throw new Error(`the counter store refused a command: ${e.error}`)
        return e?.result ?? null
      })
    },
  }
}

const KEYS = {
  active: 'lab:public:active',
  address: (key: string) => `lab:public:addr:${key}`,
  runs: (day: string) => `lab:public:runs:${day}`,
  cpu: (day: string) => `lab:public:cpu:${day}`,
}

/** Counters outlive their day by a day, so a late release still lands. */
const DAY_TTL_SECONDS = 2 * 24 * 60 * 60

export interface Counts {
  /** Runs holding a slot, this request included. */
  readonly active: number
  /** Latest release time of the earliest-expiring slot, in ms. */
  readonly active_earliest_expiry: number | null
  /** Runs from this address in the window, this request included. */
  readonly address: number
  readonly address_oldest: number | null
  /** Runs started today, this request included. */
  readonly runs_today: number
  /** Metered CPU charged to today by runs that have finished. */
  readonly cpu_ms_today: number
}

export function utcDay(now: number): string {
  return new Date(now).toISOString().slice(0, 10)
}

function nextUtcMidnight(now: number): number {
  const d = new Date(now)
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + 1)
}

function clock(ms: number): string {
  return `${new Date(ms).toISOString().slice(11, 16)} UTC`
}

function minutes(ms: number): string {
  const m = ms / 60_000
  return `${Number.isInteger(m) ? m : m.toFixed(1)} minute${m === 1 ? '' : 's'}`
}

function refusal(
  limit: LimitId,
  allowed: number,
  used: number,
  unit: Refusal['unit'],
  resetsAt: number,
  now: number,
  error: string,
): Refusal {
  return {
    limit,
    allowed,
    used,
    unit,
    resets_at: new Date(resetsAt).toISOString(),
    retry_after_seconds: Math.max(1, Math.ceil((resetsAt - now) / 1000)),
    error,
  }
}

/** Report the exceeded limit with the latest reset, when all active refusals can clear. */
export function decide(counts: Counts, now: number, limits = PUBLIC_RUN_LIMITS): Refusal | null {
  const over: Refusal[] = []
  const midnight = nextUtcMidnight(now)

  if (counts.cpu_ms_today >= limits.cpu_ms_per_day) {
    over.push(
      refusal(
        'daily-cpu',
        limits.cpu_ms_per_day,
        counts.cpu_ms_today,
        'cpu-ms',
        midnight,
        now,
        `Today's runs have used ${minutes(counts.cpu_ms_today)} of microVM CPU as the platform metered it, against a daily allowance of ${minutes(limits.cpu_ms_per_day)}. It resets at 00:00 UTC.`,
      ),
    )
  }
  if (counts.runs_today > limits.runs_per_day) {
    over.push(
      refusal(
        'daily-runs',
        limits.runs_per_day,
        Math.min(counts.runs_today - 1, limits.runs_per_day),
        'runs',
        midnight,
        now,
        `${limits.runs_per_day} runs have started today across every visitor, which is the daily ceiling. It resets at 00:00 UTC.`,
      ),
    )
  }
  if (counts.address > limits.per_address.runs) {
    const resets = (counts.address_oldest ?? now) + limits.per_address.window_seconds * 1000
    over.push(
      refusal(
        'per-address',
        limits.per_address.runs,
        Math.min(counts.address - 1, limits.per_address.runs),
        'runs',
        resets,
        now,
        `This address has started ${limits.per_address.runs} runs in the last hour, the most it may. The next one is allowed at ${clock(resets)}.`,
      ),
    )
  }
  if (counts.active > limits.concurrent_runs) {
    const resets = counts.active_earliest_expiry ?? now + limits.lease_seconds * 1000
    over.push(
      refusal(
        'concurrent',
        limits.concurrent_runs,
        Math.min(counts.active - 1, limits.concurrent_runs),
        'runs',
        resets,
        now,
        `${limits.concurrent_runs} runs are already executing, the most allowed at once. A slot frees when one of them finishes, and no later than ${clock(resets)}.`,
      ),
    )
  }

  if (over.length === 0) return null
  return over.reduce((a, b) => (Date.parse(b.resets_at) > Date.parse(a.resets_at) ? b : a))
}

function num(value: unknown): number {
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : 0
}

/** `ZRANGE ... WITHSCORES` returns `[member, score, ...]`. */
function firstScore(value: unknown): number | null {
  if (!Array.isArray(value) || value.length < 2) return null
  const n = Number(value[1])
  return Number.isFinite(n) ? n : null
}

export interface AdmitOptions {
  readonly now: number
  readonly address_key: string
  readonly slot: string
  /** Extra seconds this run may hold its slot, for an owner's suspension. */
  readonly extra_lease_seconds?: number
  readonly limits?: typeof PUBLIC_RUN_LIMITS
}

/** Reserve all counters atomically, then compensate on refusal to avoid cross-instance races. */
export async function admitRun(store: LimitStore, options: AdmitOptions): Promise<Admission> {
  const { now, slot } = options
  const limits = options.limits ?? PUBLIC_RUN_LIMITS
  const day = utcDay(now)
  const windowMs = limits.per_address.window_seconds * 1000
  const leaseMs = (limits.lease_seconds + (options.extra_lease_seconds ?? 0)) * 1000
  const address = KEYS.address(options.address_key)

  const r = await store.exec([
    ['ZREMRANGEBYSCORE', KEYS.active, '-inf', now],
    ['ZADD', KEYS.active, now + leaseMs, slot],
    ['ZCARD', KEYS.active],
    ['ZRANGE', KEYS.active, 0, 0, 'WITHSCORES'],
    ['ZREMRANGEBYSCORE', address, '-inf', now - windowMs],
    ['ZADD', address, now, slot],
    ['ZCARD', address],
    ['ZRANGE', address, 0, 0, 'WITHSCORES'],
    ['PEXPIRE', address, windowMs],
    ['INCR', KEYS.runs(day)],
    ['EXPIRE', KEYS.runs(day), DAY_TTL_SECONDS],
    ['GET', KEYS.cpu(day)],
  ])

  const counts: Counts = {
    active: num(r[2]),
    active_earliest_expiry: firstScore(r[3]),
    address: num(r[6]),
    address_oldest: firstScore(r[7]),
    runs_today: num(r[9]),
    cpu_ms_today: num(r[11]),
  }

  const refused = decide(counts, now, limits)
  if (refused !== null) {
    await refund(store, { slot, day, address_key: options.address_key })
    return { ok: false, refusal: refused }
  }
  return {
    ok: true,
    slot,
    day,
    address_runs_left: Math.max(0, limits.per_address.runs - counts.address),
  }
}

/** Refund admission refusals and workflow startup failures. */
export async function refund(
  store: LimitStore,
  reservation: { readonly slot: string; readonly day: string; readonly address_key: string },
): Promise<void> {
  await store.exec([
    ['ZREM', KEYS.active, reservation.slot],
    ['ZREM', KEYS.address(reservation.address_key), reservation.slot],
    ['DECR', KEYS.runs(reservation.day)],
  ])
}

/** Release concurrency and charge CPU to the start day. Address and daily run counts remain. */
export async function releaseRun(
  store: LimitStore,
  run: { readonly slot: string; readonly day: string; readonly cpu_ms: number | null },
): Promise<void> {
  const charged = run.cpu_ms === null ? UNMETERED_RUN_CPU_MS : Math.max(0, Math.round(run.cpu_ms))
  await store.exec([
    ['ZREM', KEYS.active, run.slot],
    ['INCRBY', KEYS.cpu(run.day), charged],
    ['EXPIRE', KEYS.cpu(run.day), DAY_TTL_SECONDS],
  ])
}

/** Refresh cached refusals within a minute so operator corrections take effect. */
export const REFUSAL_MEMORY_MS = 60_000

/**
 * Cache address and daily refusals until reset or REFUSAL_MEMORY_MS, whichever comes first.
 * Concurrent slots can free at any time, so always check them against the store.
 */
export class PublicRunGate {
  private readonly remembered = new Map<string, { refusal: Refusal; until: number }>()

  constructor(
    private readonly store: LimitStore,
    private readonly limits: typeof PUBLIC_RUN_LIMITS = PUBLIC_RUN_LIMITS,
  ) {}

  async admit(options: Omit<AdmitOptions, 'limits'>): Promise<Admission> {
    const day = `day:${utcDay(options.now)}`
    const address = `addr:${options.address_key}`
    for (const key of [day, address]) {
      const known = this.remembered.get(key)
      if (known === undefined) continue
      if (options.now < known.until) {
        const resets = Date.parse(known.refusal.resets_at)
        return {
          ok: false,
          refusal: { ...known.refusal, retry_after_seconds: Math.max(1, Math.ceil((resets - options.now) / 1000)) },
        }
      }
      this.remembered.delete(key)
    }

    const admission = await admitRun(this.store, { ...options, limits: this.limits })
    if (!admission.ok) {
      const { limit } = admission.refusal
      if (limit === 'per-address') this.remember(address, admission.refusal, options.now)
      if (limit === 'daily-runs' || limit === 'daily-cpu') this.remember(day, admission.refusal, options.now)
    }
    return admission
  }

  refund(reservation: { slot: string; day: string; address_key: string }): Promise<void> {
    return refund(this.store, reservation)
  }

  private remember(key: string, refusal: Refusal, now: number): void {
    // Bounded, because the keys are chosen by whoever is sending requests.
    if (this.remembered.size >= 10_000) this.remembered.clear()
    this.remembered.set(key, { refusal, until: Math.min(Date.parse(refusal.resets_at), now + REFUSAL_MEMORY_MS) })
  }
}
