/**
 * Everything a sandboxed candidate can see.
 *
 * Its own module so both the CLI and the workflow step build the same set,
 * and so the list is short enough to audit in one glance. What is absent is
 * the substance of it: no repository, no git history, no evaluator, no
 * labels, no environment, no credential.
 */

import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

import { LAB_DIR } from './evidence-path'

export async function uploadSet(
  labDir: string = LAB_DIR,
): Promise<{ path: string; content: Buffer }[]> {
  const [harness, observed, synthetic] = await Promise.all([
    readFile(join(labDir, 'harness.py')),
    readFile(join(labDir, 'cases', 'observed.json')),
    readFile(join(labDir, 'cases', 'synthetic.json')),
  ])
  return [
    { path: 'lab/__init__.py', content: Buffer.from('') },
    { path: 'lab/harness.py', content: harness },
    { path: 'lab/cases/observed.json', content: observed },
    { path: 'lab/cases/synthetic.json', content: synthetic },
  ]
}
