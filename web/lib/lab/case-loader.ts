/**
 * The frozen case suite, as the server sees it.
 *
 * Read from the committed JSON rather than a database, because the whole
 * experiment rests on the suite being the same bytes for every run — and a
 * sha256 of a file is checkable by a reader in a way that a table row is not.
 */

import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

import { parseCaseSuite, type Case } from './records'

export async function loadCasesForRun(
  labDir: string = join(process.cwd(), '..', 'backend', 'lab'),
): Promise<Case[]> {
  const cases: Case[] = []
  for (const group of ['observed', 'synthetic'] as const) {
    const text = await readFile(join(labDir, 'cases', `${group}.json`), 'utf8')
    const parsed = parseCaseSuite(JSON.parse(text))
    if (!parsed.ok) throw new Error(`invalid case suite ${group}: ${parsed.issues.join('; ')}`)
    cases.push(...parsed.value.cases)
  }
  return cases
}
