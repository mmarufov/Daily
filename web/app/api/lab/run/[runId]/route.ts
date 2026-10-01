/**
 * Read one durable run. Public, because inspection is public.
 *
 * Starting a run is bounded by counters; watching one costs nothing and is
 * not. This route is the half anybody may use as often as they like, and the
 * one the `/lab` runner polls.
 *
 * What is returned is the workflow's own state, not a copy kept somewhere
 * else. There is no second store to drift from the journal, which is the
 * point of moving durability to the platform in the first place.
 */

import { getRun } from 'workflow/api'

import { isProgressEvent, PROGRESS_NAMESPACE, type ProgressEvent } from '@/lib/lab/live'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const NO_STORE = { 'Cache-Control': 'no-store' }

/** A status after which nothing about the run will change. */
function finished(status: string): boolean {
  return status === 'completed' || status === 'failed' || status === 'cancelled'
}

function within<T>(promise: Promise<T>, ms: number): Promise<T> {
  return Promise.race([
    promise,
    new Promise<never>((_, reject) => setTimeout(() => reject(new Error('timed out')), ms)),
  ])
}

/**
 * Every progress event written so far, read without waiting for more.
 *
 * The stream stays open while the run is live, so reading it to the end would
 * turn a poll into a long-poll. The tail index says how many chunks exist;
 * exactly that many are read and the reader is let go. Null, rather than an
 * empty list, when the stream could not be read: "no events" and "could not
 * tell" are different statements.
 */
async function readProgress(run: ReturnType<typeof getRun>): Promise<ProgressEvent[] | null> {
  try {
    const readable = run.getReadable<unknown>({ namespace: PROGRESS_NAMESPACE })
    const tail = await within(readable.getTailIndex(), 2_000)
    if (tail < 0) {
      await readable.cancel().catch(() => {})
      return []
    }
    const reader = readable.getReader()
    const events: ProgressEvent[] = []
    try {
      for (let i = 0; i <= Math.min(tail, 63); i += 1) {
        const { value, done } = await within(reader.read(), 2_000)
        if (done) break
        if (isProgressEvent(value)) events.push({ at: value.at, stage: value.stage.slice(0, 200) })
      }
    } finally {
      await reader.cancel().catch(() => {})
    }
    return events
  } catch {
    return null
  }
}

export async function GET(
  _request: Request,
  context: { params: Promise<{ runId: string }> },
): Promise<Response> {
  const { runId } = await context.params
  if (!/^[A-Za-z0-9_-]{1,128}$/.test(runId)) {
    return Response.json({ error: 'malformed run id' }, { status: 400, headers: NO_STORE })
  }

  // `getRun` fetches nothing: it returns a handle, and the first property
  // read is the first request. This route used to wrap only `getRun` in a
  // try and then await `run.status` outside it, so an unknown id threw past
  // the guard and production served a bodiless 500 for it. A visitor
  // mistyping a run id is a 404; a 500 says this deployment is broken.
  // `exists` maps the store's not-found to false; a store that rejects the id
  // as malformed is the same answer for a reader.
  const run = getRun(runId)
  let exists: boolean
  try {
    exists = await run.exists
  } catch (error) {
    const status = (error as { status?: unknown } | null)?.status
    if (status === 400 || status === 404) exists = false
    else return Response.json({ error: 'the run store could not be reached' }, { status: 503, headers: NO_STORE })
  }
  if (!exists) {
    return Response.json({ error: 'no such run' }, { status: 404, headers: NO_STORE })
  }

  const status = await run.status
  // `returnValue` blocks until completion, so it is read only once the run
  // has finished. `pending` is not finished: treating it as such awaited a
  // run that had not started and turned a status poll into a long-poll.
  const outcome = status === 'completed' ? await run.returnValue.catch(() => null) : null
  const progress = await readProgress(run)

  return Response.json(
    { run_id: runId, status, finished: finished(status), outcome, progress },
    { headers: NO_STORE },
  )
}
