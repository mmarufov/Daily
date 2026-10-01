/**
 * `POST /api/lab/run`, as a function of its dependencies.
 *
 * The route file wires the real ones in. Keeping the handler here means the
 * whole admission path, from body parsing to the refusal a visitor reads, is
 * exercised by tests against a store and a clock they control, rather than
 * asserted to exist.
 *
 * The order is the policy:
 *
 *   1. parse and validate        free, and refuses garbage before it costs
 *   2. the scope gate            an out-of-scope patch never reaches a counter
 *   3. the counters              shared across every instance, fail closed
 *   4. start                     a reservation whose run never started is
 *                                refunded, so it costs the visitor nothing
 */

import { randomUUID } from 'node:crypto'

import type { WorkflowInput } from './orchestration'
import { authoriseOwner } from './owner'
import { addressBucket, addressKey, clientAddress, type PublicRunGate } from './public-limits'
import { checkPatchScope } from './scope'
import { ALLOWED_PATCH_PATHS, specHash } from './spec'

/** A candidate larger than this is refused before anything is allocated. */
export const MAX_SOURCE_BYTES = 64 * 1024

export interface RunRequestDeps {
  /** Null when no counter store is configured: the runner is closed. */
  readonly gate: PublicRunGate | null
  readonly start: (input: WorkflowInput) => Promise<{ readonly runId: string }>
  readonly now?: () => number
  readonly env?: Readonly<Record<string, string | undefined>>
}

const json = (body: unknown, status: number, headers: Record<string, string> = {}): Response =>
  Response.json(body, { status, headers: { 'Cache-Control': 'no-store', ...headers } })

export async function handleRunRequest(request: Request, deps: RunRequestDeps): Promise<Response> {
  const now = deps.now ?? Date.now

  let body: unknown
  try {
    body = await request.json()
  } catch {
    return json({ error: 'the request body is not JSON' }, 400)
  }

  const { candidate_id: candidateId, source, suspend_seconds: suspendSeconds } = (body ?? {}) as {
    candidate_id?: unknown
    source?: unknown
    suspend_seconds?: unknown
  }

  if (typeof candidateId !== 'string' || !/^[a-z0-9][a-z0-9-]{1,40}$/.test(candidateId)) {
    return json({ error: 'candidate_id must match ^[a-z0-9][a-z0-9-]{1,40}$' }, 400)
  }
  if (typeof source !== 'string' || source.length === 0 || source.length > MAX_SOURCE_BYTES) {
    return json({ error: `source must be 1..${MAX_SOURCE_BYTES} bytes` }, 400)
  }

  // The scope gate runs again inside the workflow, where its decision is
  // journaled. Running it here as well means an out-of-scope patch is refused
  // before it reaches a counter or a durable run exists.
  const scope = checkPatchScope([{ path: ALLOWED_PATCH_PATHS[0] as string, content: source }])
  if (!scope.allowed) {
    return json({ error: `${scope.rejection}: ${scope.detail}` }, 422)
  }

  // Suspension is the durability demonstration, and a suspended run holds a
  // slot for as long as it sleeps. So it is the owner's alone; anyone else's
  // request for it is ignored rather than refused.
  const owner = authoriseOwner(request, deps.env ?? process.env).ok
  const suspend =
    owner && typeof suspendSeconds === 'number' && Number.isFinite(suspendSeconds)
      ? Math.max(0, Math.min(300, Math.trunc(suspendSeconds)))
      : 0

  if (deps.gate === null) {
    return json(
      {
        error:
          'the public runner is closed on this deployment: no counter store is configured, so no run can be counted and none is started',
      },
      503,
    )
  }

  const at = now()
  const key = addressKey(addressBucket(clientAddress(request.headers)))
  const slot = randomUUID()

  let admission: Awaited<ReturnType<PublicRunGate['admit']>>
  try {
    admission = await deps.gate.admit({ now: at, address_key: key, slot, extra_lease_seconds: suspend })
  } catch {
    return json(
      { error: 'the run counter could not be reached, so no run was started. Nothing was counted against you.' },
      503,
    )
  }

  if (!admission.ok) {
    return json(admission.refusal, 429, { 'Retry-After': String(admission.refusal.retry_after_seconds) })
  }

  let run: { readonly runId: string }
  try {
    run = await deps.start({
      run_id: `${candidateId}__${at.toString(36)}`,
      candidate_id: candidateId,
      source,
      spec_hash: specHash(),
      suspend_seconds: suspend,
      slot: admission.slot,
      day: admission.day,
    })
  } catch {
    await deps.gate.refund({ slot: admission.slot, day: admission.day, address_key: key }).catch(() => {})
    return json({ error: 'the run could not be started, and nothing was counted against you' }, 503)
  }

  return json(
    { run_id: run.runId, suspend_seconds: suspend, address_runs_left: admission.address_runs_left },
    202,
  )
}
