import { readFile } from 'node:fs/promises'
import { join } from 'node:path'

import { parseDemoBundle, type DemoBundle } from './demo'

export type DemoLoad =
  | { readonly ok: true; readonly bundle: DemoBundle }
  | { readonly ok: false; readonly issues: readonly string[] }

/**
 * The demo bundle is committed, so this never touches the network and never
 * needs a provider key. A malformed bundle is reported rather than partly
 * rendered.
 */
export async function loadDemo(): Promise<DemoLoad> {
  try {
    const text = await readFile(join(process.cwd(), 'public', 'demo', 'editions.json'), 'utf8')
    const parsed = parseDemoBundle(JSON.parse(text))
    if (parsed.ok) return { ok: true, bundle: parsed.value }
    return { ok: false, issues: parsed.issues }
  } catch (error) {
    return { ok: false, issues: [error instanceof Error ? error.message : String(error)] }
  }
}
