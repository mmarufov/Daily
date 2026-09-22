/**
 * Start one durable run. Owner only, enforced here rather than in the UI.
 *
 * Everything public about the Lab is a replay of committed evidence. This is
 * the one surface that creates a microVM and may call a model, so it is the
 * one surface that costs money, and the authorisation is server-side for the
 * obvious reason that a hidden button is not an access control.
 *
 * The response is the run id and nothing else. Progress is read from the
 * public status route, so a caller who starts a run and a visitor who watches
 * it are looking at the same state through the same code path.
 */

import { start } from 'workflow/api'

import { runCandidateWorkflow } from '@/lib/lab/orchestration'
import { authoriseOwner } from '@/lib/lab/owner'
import { loadCasesForRun } from '@/lib/lab/case-loader'
import { checkPatchScope } from '@/lib/lab/scope'
import { ALLOWED_PATCH_PATHS, specHash } from '@/lib/lab/spec'

export const runtime = 'nodejs'

/** A candidate larger than this is refused before anything is allocated. */
const MAX_SOURCE_BYTES = 64 * 1024

export async function POST(request: Request): Promise<Response> {
  const auth = authoriseOwner(request)
  if (!auth.ok) {
    return Response.json({ error: auth.reason }, { status: auth.status })
  }

  let body: unknown
  try {
    body = await request.json()
  } catch {
    return Response.json({ error: 'the request body is not JSON' }, { status: 400 })
  }

  const { candidate_id: candidateId, source, suspend_seconds: suspendSeconds } = (body ?? {}) as {
    candidate_id?: unknown
    source?: unknown
    suspend_seconds?: unknown
  }

  if (typeof candidateId !== 'string' || !/^[a-z0-9][a-z0-9-]{1,40}$/.test(candidateId)) {
    return Response.json({ error: 'candidate_id must match ^[a-z0-9][a-z0-9-]{1,40}$' }, { status: 400 })
  }
  if (typeof source !== 'string' || source.length === 0 || source.length > MAX_SOURCE_BYTES) {
    return Response.json({ error: `source must be 1..${MAX_SOURCE_BYTES} bytes` }, { status: 400 })
  }

  // The scope gate runs again inside the workflow, where its decision is
  // journaled. Running it here as well is not redundancy for its own sake: it
  // means an out-of-scope patch is refused before a durable run exists,
  // instead of creating a run whose only content is its own rejection.
  const scope = checkPatchScope([{ path: ALLOWED_PATCH_PATHS[0] as string, content: source }])
  if (!scope.allowed) {
    return Response.json({ error: `${scope.rejection}: ${scope.detail}` }, { status: 422 })
  }

  const suspend =
    typeof suspendSeconds === 'number' && Number.isFinite(suspendSeconds)
      ? Math.max(0, Math.min(300, Math.trunc(suspendSeconds)))
      : 0

  const cases = await loadCasesForRun()
  const run = await start(runCandidateWorkflow, [
    {
      run_id: `${candidateId}__${Date.now().toString(36)}`,
      candidate_id: candidateId,
      source,
      spec_hash: specHash(),
      suspend_seconds: suspend,
    },
    cases,
  ])

  return Response.json({ run_id: run.runId, suspend_seconds: suspend }, { status: 202 })
}
