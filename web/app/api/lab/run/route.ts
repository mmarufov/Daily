/**
 * Start one durable run. Public, and bounded by counters rather than a token.
 *
 * This is the one public surface that creates a microVM. It calls no model,
 * so what a visitor can spend is Sandbox compute, and `public-limits.ts` is
 * what bounds it: per address, at once, and per day, decided against state
 * every instance shares. Starting paid model work is still owner-only, at
 * `/api/lab/investigate`.
 *
 * The response is the run id. Progress is read from the public status route,
 * so a visitor who starts a run and one who watches it are looking at the
 * same state through the same code path.
 */

import { randomUUID } from 'node:crypto'

import { start } from 'workflow/api'

import { runCandidateWorkflow } from '@/lib/lab/orchestration'
import { PublicRunGate, upstashStore } from '@/lib/lab/public-limits'
import { handleRunRequest } from '@/lib/lab/public-run'

export const runtime = 'nodejs'

/**
 * One gate per instance, so its memory of refusals that cannot change before
 * they reset is shared by every request this instance serves. The counters
 * themselves are in the store.
 */
let gate: PublicRunGate | null | undefined

function currentGate(): PublicRunGate | null {
  if (gate === undefined) {
    const store = upstashStore()
    gate = store === null ? null : new PublicRunGate(store)
  }
  return gate
}

/**
 * Which function instance answered, as an opaque random id.
 *
 * The limits are only limits if they hold across instances, and Fluid runs
 * several at once. This header is how that is checked from outside: fire
 * requests in parallel, see more than one id come back, and see the global
 * ceiling hold anyway. It carries nothing but the fact of being a different
 * instance.
 */
const INSTANCE = randomUUID().slice(0, 8)

export async function POST(request: Request): Promise<Response> {
  const response = await handleRunRequest(request, {
    gate: currentGate(),
    start: (input) => start(runCandidateWorkflow, [input]),
  })
  response.headers.set('X-Lab-Instance', INSTANCE)
  return response
}
