/**
 * Read one durable run. Public, because inspection is public.
 *
 * Starting a run costs money and is owner-only; watching one costs nothing
 * and is not. That asymmetry is the access model in one sentence, and this
 * route is the half of it that anybody may use.
 *
 * What is returned is the workflow's own state, not a copy kept somewhere
 * else. There is no second store to drift from the journal — which is the
 * point of moving durability to the platform in the first place.
 */

import { getRun } from 'workflow/api'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

export async function GET(
  _request: Request,
  context: { params: Promise<{ runId: string }> },
): Promise<Response> {
  const { runId } = await context.params
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(runId)) {
    return Response.json({ error: 'malformed run id' }, { status: 400 })
  }

  // `getRun` throws on an unknown id rather than returning null, so the
  // not-found path was reaching the framework's error handler and serving a
  // bodiless 500. A visitor mistyping a run id is a 404; a 500 says this
  // deployment is broken, which is a worse lie than it looks -- the whole
  // point of the public read route is that a stranger can check a claim, and
  // a 500 tells them the claim is unavailable rather than absent.
  let run: Awaited<ReturnType<typeof getRun>> | null = null
  try {
    run = await getRun(runId)
  } catch {
    run = null
  }
  if (run === null || run === undefined) {
    return Response.json({ error: 'no such run' }, { status: 404, headers: { 'Cache-Control': 'no-store' } })
  }

  const status = await run.status
  // `returnValue` blocks until completion, so it is read only once the run
  // has actually finished. Awaiting it on a running workflow would turn a
  // status poll into a long-poll of unbounded length.
  const finished = status !== 'running'
  const returnValue = finished ? await run.returnValue.catch(() => null) : null

  return Response.json(
    { run_id: runId, status, outcome: returnValue },
    { headers: { 'Cache-Control': 'no-store' } },
  )
}
