/**
 * Server-side loading for the Lab.
 *
 * The committed export under `public/lab/` is the source. Unlike the
 * evaluation artifacts there is no Blob fallback yet, and saying so is cheaper
 * than pretending: a publication path that has never run is not a feature.
 *
 * A malformed run is surfaced as an error rather than skipped. A quietly
 * missing run is how a results page starts showing five verdicts where six
 * were computed.
 */

import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

import {
  parseLabManifest,
  parseLabRun,
  type LabManifest,
  type LabRun,
} from './artifact'

const DIR = join(process.cwd(), 'public', 'lab-artifacts')

export interface LabIndex {
  readonly manifest: LabManifest | null
  readonly issues: readonly string[]
}

export async function loadLabIndex(): Promise<LabIndex> {
  try {
    const raw = JSON.parse(await readFile(join(DIR, 'manifest.json'), 'utf8')) as unknown
    const parsed = parseLabManifest(raw)
    if (parsed.ok) return { manifest: parsed.value, issues: [] }
    return { manifest: null, issues: parsed.issues }
  } catch (error) {
    return { manifest: null, issues: [error instanceof Error ? error.message : String(error)] }
  }
}

export async function loadLabRun(file: string): Promise<LabRun | null> {
  try {
    const raw = JSON.parse(await readFile(join(DIR, file), 'utf8')) as unknown
    const parsed = parseLabRun(raw)
    return parsed.ok ? parsed.value : null
  } catch {
    return null
  }
}

export async function loadOffendingCase(): Promise<import('@/components/LabOffendingCase').OffendingCase | null> {
  const { OffendingCaseSchema } = await import('@/components/LabOffendingCase')
  try {
    const raw = JSON.parse(await readFile(join(DIR, 'offending-case.json'), 'utf8')) as unknown
    const parsed = OffendingCaseSchema.safeParse(raw)
    return parsed.success ? parsed.data : null
  } catch {
    return null
  }
}

/** The three published walkthroughs, in the order they should be read. */
export interface Walkthrough {
  readonly slug: string
  readonly file: string
  readonly title: string
  readonly blurb: string
}

export function walkthroughs(manifest: LabManifest): readonly Walkthrough[] {
  const find = (candidate: string, tag: string) =>
    manifest.entries.find((e) => e.file === `${candidate}-${tag}.json`)

  const out: Walkthrough[] = []
  const pass = find('keyed-v2', 'clean')
  if (pass) {
    out.push({
      slug: 'accepted',
      file: pass.file,
      title: 'A candidate that passes the stated checks',
      blurb:
        'Every verdict names its article. The association survives all 720 orderings of the same response.',
    })
  }
  const reject = find('control-lenient-keyed', 'clean')
  if (reject) {
    out.push({
      slug: 'rejected',
      file: reject.file,
      title: 'A defective candidate the checks reject',
      blurb:
        'A seeded control that keeps the last verdict when an article is judged twice. Rejected on a case with a named counterexample.',
    })
  }
  const resumed = find('keyed-v2', 'interrupted')
  if (resumed) {
    out.push({
      slug: 'interrupted',
      file: resumed.file,
      title: 'An interrupted execution that resumes',
      blurb:
        'The orchestrator was SIGKILLed with an attempt in flight. Recovery resolved it as unknown-outcome and finished the work.',
    })
  }
  return out
}

/** Runs that are not one of the three walkthroughs, for the full table. */
export function otherRuns(manifest: LabManifest, shown: readonly Walkthrough[]) {
  const seen = new Set(shown.map((w) => w.file))
  return manifest.entries.filter((e) => !seen.has(e.file))
}
