/**
 * Everything a sandboxed candidate can see.
 *
 * Its own module so the CLI and the workflow step build the same set, and so
 * the list is short enough to audit in one glance. What is absent is the
 * substance of it: no repository, no git history, no evaluator, no labels, no
 * environment, no credential.
 *
 * And, since an audit demonstrated otherwise, **no answers**. The case files
 * were shipped verbatim, and a case carries `expectation` — three of them the
 * exact association to produce, fifty-eight the refusal kinds expected. A
 * candidate could fingerprint the response, look up the expectation beside it
 * and echo it back. That reached `accepted-for-review` over the real suite.
 *
 * The harness reads `case_id`, `articles` and `response` and nothing else, so
 * the fix costs nothing: what ships is a projection onto those three fields.
 * A projection rather than a `delete expectation` on purpose — an allowlist
 * has to recognise three names, a denylist has to anticipate every future
 * field that might carry ground truth, and this repository has already been
 * bitten by a denylist that quietly widened.
 */

import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

import { LAB_DIR } from './evidence-path'

/** The only fields the guest receives. Anything else is ground truth. */
export interface GuestCase {
  readonly case_id: string
  readonly articles: readonly unknown[]
  readonly response: unknown
}

export function projectForGuest(raw: unknown): GuestCase[] {
  const suite = raw as { cases?: { case_id?: unknown; articles?: unknown; response?: unknown }[] }
  return (suite.cases ?? []).map((c) => ({
    case_id: String(c.case_id),
    articles: Array.isArray(c.articles) ? c.articles : [],
    response: c.response ?? null,
  }))
}

async function stripped(path: string): Promise<Buffer> {
  const cases = projectForGuest(JSON.parse(await readFile(path, 'utf8')))
  return Buffer.from(`${JSON.stringify({ cases })}\n`, 'utf8')
}

export async function uploadSet(
  labDir: string = LAB_DIR,
): Promise<{ path: string; content: Buffer }[]> {
  const [harness, observed, synthetic] = await Promise.all([
    readFile(join(labDir, 'harness.py')),
    stripped(join(labDir, 'cases', 'observed.json')),
    stripped(join(labDir, 'cases', 'synthetic.json')),
  ])
  return [
    { path: 'lab/__init__.py', content: Buffer.from('') },
    { path: 'lab/harness.py', content: harness },
    { path: 'lab/cases/observed.json', content: observed },
    { path: 'lab/cases/synthetic.json', content: synthetic },
  ]
}
