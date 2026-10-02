/**
 * What the `/lab` runner offers before anyone types anything.
 *
 * Read at build time from the staged evidence, so the editor is prefilled
 * with the committed bytes of a real implementation rather than a copy that
 * could drift from it. The first preset is the default on purpose: it is the
 * experimental count guard, and a fault-injected case catches it, so the first click
 * shows the thing the Lab exists to show.
 */

import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

import { loadCasesForRun } from './case-loader'
import { LAB_DIR } from './evidence-path'
import type { CatalogCase } from './live'

export interface RunnerPreset {
  readonly id: string
  readonly note: string
  readonly source: string
}

const PRESETS: readonly { id: string; file: string; note: string }[] = [
  { id: 'count-guard-v1', file: 'count_guard_v1.py', note: 'experimental count guard' },
  { id: 'positional-v0', file: 'positional_v0.py', note: 'original positional parser' },
  { id: 'keyed-v2', file: 'keyed_v2.py', note: 'the proposed contract' },
]

export async function loadRunnerPresets(labDir: string = LAB_DIR): Promise<RunnerPreset[]> {
  return Promise.all(
    PRESETS.map(async (p) => ({
      id: p.id,
      note: p.note,
      source: await readFile(join(labDir, 'contract', 'versions', p.file), 'utf8'),
    })),
  )
}

export async function loadCaseCatalog(labDir: string = LAB_DIR): Promise<CatalogCase[]> {
  const cases = await loadCasesForRun(labDir)
  return cases.map((c) => ({ case_id: c.case_id, origin: c.origin, protocol: c.protocol, why: c.expectation.why }))
}
