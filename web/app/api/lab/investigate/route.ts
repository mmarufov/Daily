/**
 * Start one real investigation. Owner only, enforced here.
 *
 * This is the only route in the application that can spend money at a
 * provider, and it exists so that spending happens on the deployment holding
 * the credential rather than on whichever machine an operator happens to be
 * sitting at. `AI_GATEWAY_API_KEY` is a Vercel sensitive variable: it can be
 * set and never read back, which is the correct shape for a key and the
 * reason the paid loop lives here.
 *
 * The response is a run id. Progress and the finished evidence are read from
 * the public `GET /api/lab/run/[runId]`, so the owner who starts a run and a
 * visitor who watches it are looking at the same state through the same code.
 */

import { start } from 'workflow/api'

import { readiness } from '@/lib/lab/investigator'
import { investigationWorkflow } from '@/lib/lab/orchestration'
import { authoriseOwner } from '@/lib/lab/owner'
import { specHash } from '@/lib/lab/spec'

export const runtime = 'nodejs'

export async function POST(request: Request): Promise<Response> {
  const auth = authoriseOwner(request)
  if (!auth.ok) return Response.json({ error: auth.reason }, { status: auth.status })

  // Checked before a run exists, so a deployment without a gateway key does
  // not leave a trail of workflow runs whose only content is their own
  // refusal. `investigate()` checks it again where it matters; this is the
  // early, legible one.
  const ready = readiness()
  if (!ready.ready) {
    return Response.json({ error: ready.reason, needs: ready.needs }, { status: 503 })
  }

  let body: unknown = {}
  try {
    body = (await request.json()) as unknown
  } catch {
    // An empty body is fine: every field has a default.
  }
  const { candidate_id: candidateId, suspend_seconds: suspendSeconds } = (body ?? {}) as {
    candidate_id?: unknown
    suspend_seconds?: unknown
  }

  const id =
    typeof candidateId === 'string' && /^agent-[a-z0-9-]{1,40}$/.test(candidateId)
      ? candidateId
      : 'agent-001'
  const suspend =
    typeof suspendSeconds === 'number' && Number.isFinite(suspendSeconds)
      ? Math.max(0, Math.min(300, Math.trunc(suspendSeconds)))
      : 0

  // The suite is not passed in: every workflow argument is journalled, and
  // `observed.json` alone is 1.8 MB. The steps load it from the staged copy
  // beside them.
  const run = await start(investigationWorkflow, [
    {
      run_id: `${id}__${Date.now().toString(36)}`,
      candidate_id: id,
      spec_hash: specHash(),
      suspend_seconds: suspend,
    },
  ])

  return Response.json(
    { run_id: run.runId, candidate_id: id, suspend_seconds: suspend, gateway: ready.gateway },
    { status: 202 },
  )
}
