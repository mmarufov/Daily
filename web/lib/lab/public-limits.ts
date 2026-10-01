/**
 * What a stranger may spend, and how that is counted.
 *
 * The candidate runner used to be owner-only, because it is the one public
 * surface that creates a microVM. It makes no model call, so the only thing a
 * visitor can spend is Sandbox compute, and these limits are what bound it.
 *
 * Four limits, each decided against state shared by every function instance:
 *
 *   per address   5 runs in any rolling hour
 *   at once       3 runs executing across all visitors
 *   per UTC day   50 runs, and 20 minutes of microVM CPU as metered by the
 *                 platform, across all visitors
 *
 * They are constants rather than environment variables for the reason the
 * README gives about `LAB_MAX_USD`: raising a limit should be a commit
 * somebody reads, not a setting somebody changes.
 *
 * `LAB_MAX_USD` itself is not reused. It authorises model spend, in dollars,
 * for one investigation. A sandbox run has no measured dollar cost; it has
 * measured CPU milliseconds. A dollar cap here would enforce price times CPU,
 * which is an estimate, and this site does not act on numbers nobody
 * measured. So the daily cap is in the units the platform meters.
 *
 * The counters live in Upstash Redis, reached over its REST transaction
 * endpoint. Memory would not do: Fluid instances do not share it, so a limit
 * held there is a limit per instance, which is no limit. Every decision is one
 * MULTI transaction that reserves first and is compensated on refusal. Under a
 * burst that can refuse a request that would have fit. It cannot admit one
 * that does not, because every count it reads already includes the request
 * itself and comes out of a serialised transaction.
 *
 * Fails closed. No store configured, or a store that does not answer, means no
 * run starts. A run nobody counted is the one outcome this file exists to
 * prevent.
 */

import { createHash } from 'node:crypto'

import { SANDBOX_LIMITS, SANDBOX_VCPUS } from './runner'

export const PUBLIC_RUN_LIMITS = {
  per_address: { runs: 5, window_seconds: 60 * 60 },
  concurrent_runs: 3,
  runs_per_day: 50,
  cpu_ms_per_day: 20 * 60 * 1000,
  /**
   * How long a slot is held if the run never releases it. The microVM lives
   * at most `SANDBOX_LIMITS.wall_clock_seconds`, so this is generous on
   * purpose: it only matters when the release step itself never ran.
   */
  lease_seconds: 300,
} as const

/**
 * What a run is charged when the platform did not meter it.
 *
 * The worst case the sandbox allows: every vCPU busy for the whole lifetime.
 * Unknown is never counted as zero, for the same reason a missing record is
 * never a pass.
 */
export const UNMETERED_RUN_CPU_MS = SANDBOX_VCPUS * SANDBOX_LIMITS.wall_clock_seconds * 1000

export type LimitId = 'per-address' | 'concurrent' | 'daily-runs' | 'daily-cpu'

export interface Refusal {
  readonly limit: LimitId
  /** The configured ceiling, in `unit`. */
  readonly allowed: number
  /** What has been counted against it, in `unit`. */
  readonly used: number
  readonly unit: 'runs' | 'cpu-ms'
  /** The earliest moment a retry can succeed against this limit. */
  readonly resets_at: string
  readonly retry_after_seconds: number
  /** One sentence naming the limit and when it resets. */
  readonly error: string
}

export type Admission =
  | { readonly ok: true; readonly slot: string; readonly day: string; readonly address_runs_left: number }
  | { readonly ok: false; readonly refusal: Refusal }

/* ------------------------------------------------------- addresses --- */

/**
 * The address a request came from, as the Vercel proxy computed it.
 *
 * `x-real-ip` only. The platform sets it and a client cannot, which is not
 * true of `x-forwarded-for` on every host this code might run on. Absent
 * (local development, tests) means null, and every null shares one bucket:
 * a missing address is the most conservative identity, not a free pass.
 */
export function clientAddress(headers: Headers): string | null {
  const raw = (headers.get('x-real-ip') ?? '').trim()
  return raw === '' ? null : raw
}

/**
 * The unit an address is limited in.
 *
 * IPv4 is limited per address. IPv6 is limited per /64, because a single
 * subscriber is routinely handed a whole /64 and could otherwise rotate
 * through 2^64 identities without leaving their connection.
 */
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

/**
 * Pseudonymous, not anonymous. The IPv4 space is small enough to reverse a
 * hash by enumeration, so the protection here is the TTL: a key outlives its
 * window by nothing.
 */
export function addressKey(bucket: string): string {
  return createHash('sha256').update(`lab-public-address:${bucket}`).digest('hex').slice(0, 32)
}

/* --------------------------------------------------------- the store --- */

/** One Redis command, as the REST transaction endpoint takes it. */
export type Command = readonly (string | number)[]

/**
 * Everything the limiter needs from a store: run these commands as one
 * transaction and return their results in order.
 */
export interface LimitStore {
  exec(commands: readonly Command[]): Promise<readonly unknown[]>
}

/**
 * Upstash over REST, or null when it is not configured.
 *
 * Read lazily, never at module scope: CI builds and tests with no environment
 * at all, and an import that throws on a missing variable would break both.
 */
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

/* ------------------------------------------------------- the decision --- */

export interface Counts {
  /** Runs holding a slot, this request included. */
  readonly active: number
  /** When the earliest-expiring slot frees at the latest, ms. */
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

/**
 * Which limit, if any, this request is over.
 *
 * Pure, so the arithmetic is tested without a store. When several limits are
 * exceeded the one reported is the one that resets *last*: telling a visitor a
 * slot frees in ten seconds, when the daily ceiling will refuse them anyway,
 * is a true statement that misleads.
 */
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
        counts.runs_today - 1,
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
        counts.address - 1,
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
        counts.active - 1,
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

/* ------------------------------------------------------- admission --- */

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

/**
 * Reserve a slot and every counter in one transaction, then decide.
 *
 * Reserve-then-compensate rather than check-then-reserve: a check and a
 * reservation in separate round trips is a race between instances, and the
 * loser of that race is the limit.
 */
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

/**
 * Undo a reservation that never became a run: refused, or `start` failed.
 * A refused request consumes nothing.
 */
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

/**
 * A run finished: free its slot and charge its CPU to the day it started on.
 *
 * The address entry and the day's run count stay. A run that ran is a run,
 * however it ended.
 */
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

/* ------------------------------------------------------------ gate --- */

/**
 * Admission with a memory of refusals that cannot change before they reset.
 *
 * An address over its hourly limit stays over it until its oldest run ages
 * out: refusals add nothing, so nothing else can lower the count. A day over
 * its ceiling stays over until midnight. Remembering those refusals until
 * their exact reset time means a client hammering the route costs one store
 * transaction per instance, not one per request, and every answer it gets is
 * still exact.
 *
 * The concurrent limit is not remembered. A slot can free at any moment.
 */
export class PublicRunGate {
  private readonly remembered = new Map<string, Refusal>()

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
      const resets = Date.parse(known.resets_at)
      if (options.now < resets) {
        return {
          ok: false,
          refusal: { ...known, retry_after_seconds: Math.max(1, Math.ceil((resets - options.now) / 1000)) },
        }
      }
      this.remembered.delete(key)
    }

    const admission = await admitRun(this.store, { ...options, limits: this.limits })
    if (!admission.ok) {
      const { limit } = admission.refusal
      if (limit === 'per-address') this.remember(address, admission.refusal)
      if (limit === 'daily-runs' || limit === 'daily-cpu') this.remember(day, admission.refusal)
    }
    return admission
  }

  refund(reservation: { slot: string; day: string; address_key: string }): Promise<void> {
    return refund(this.store, reservation)
  }

  private remember(key: string, value: Refusal): void {
    // Bounded, because the keys are chosen by whoever is sending requests.
    if (this.remembered.size >= 10_000) this.remembered.clear()
    this.remembered.set(key, value)
  }
}
