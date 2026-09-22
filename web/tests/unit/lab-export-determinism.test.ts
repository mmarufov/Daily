import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { parseLabManifest, parseLabRun } from '@/lib/lab/artifact'

/**
 * The committed Lab export must be a pure function of committed bytes.
 *
 * This suite exists because it was not. `scripts/export-lab.ts` derived
 * provenance from `git log --format=%h`, and embedded `git diff --no-index`
 * output that carries an `index <blob>..<blob>` line. Both honour
 * `core.abbrev`, which defaults to `auto` and is computed from a clone's
 * object count — so the same tree exported to different bytes in CI than
 * locally, every one of the seven runs went stale at once, and the failure was
 * unreproducible on the machine that had to fix it.
 */

const DIR = join(process.cwd(), 'public', 'lab-artifacts')

function runFiles(): string[] {
  return readdirSync(DIR).filter((f) => f.endsWith('.json') && f !== 'manifest.json' && f !== 'offending-case.json')
}

describe('the committed lab export', () => {
  const files = runFiles()

  it('has runs to check', () => {
    expect(files.length).toBeGreaterThan(0)
  })

  it('validates against the schema', () => {
    for (const file of files) {
      const parsed = parseLabRun(JSON.parse(readFileSync(join(DIR, file), 'utf8')))
      expect(parsed.ok, `${file}: ${parsed.ok ? '' : parsed.issues.join('; ')}`).toBe(true)
    }
    const manifest = parseLabManifest(JSON.parse(readFileSync(join(DIR, 'manifest.json'), 'utf8')))
    expect(manifest.ok).toBe(true)
  })

  it('embeds no abbreviation-dependent git blob line in any patch', () => {
    for (const file of files) {
      const run = JSON.parse(readFileSync(join(DIR, file), 'utf8')) as { candidate: { patch: string } }
      const offending = run.candidate.patch.split('\n').filter((l) => l.startsWith('index '))
      expect(offending, `${file} carries a git index line: ${offending[0]}`).toHaveLength(0)
    }
  })

  it('records a full 40-character revision, not an abbreviation', () => {
    for (const file of files) {
      const run = JSON.parse(readFileSync(join(DIR, file), 'utf8')) as {
        provenance: { executed_at_revision: string }
      }
      const rev = run.provenance.executed_at_revision
      // Recorded by the orchestrator at run time. `+dirty` is allowed and
      // meaningful; a 7-character abbreviation is not, because its length is
      // environment-dependent.
      expect(rev, file).toMatch(/^(unknown|[0-9a-f]{40}(\+dirty)?)$/)
    }
  })

  it('carries content hashes rather than a self-referential revision', () => {
    const manifest = JSON.parse(readFileSync(join(DIR, 'manifest.json'), 'utf8')) as Record<string, unknown>
    expect(manifest).toHaveProperty('inputs_sha256')
    expect(manifest).not.toHaveProperty('artifact_revision')
    for (const file of files) {
      const run = JSON.parse(readFileSync(join(DIR, file), 'utf8')) as {
        provenance: Record<string, unknown>
      }
      expect(run.provenance).toHaveProperty('inputs_sha256')
      expect(run.provenance).toHaveProperty('evaluator_sha256')
      expect(run.provenance).not.toHaveProperty('artifact_revision')
      expect(run.provenance).not.toHaveProperty('artifact_built_at')
    }
  })

  it('never stamps a clock reading into built_at', () => {
    const manifest = JSON.parse(readFileSync(join(DIR, 'manifest.json'), 'utf8')) as { built_at: string }
    // built_at is the newest run's own recorded timestamp, so it must appear
    // in some run. A Date.now() fallback would not.
    const stamps = files.map((f) => {
      const run = JSON.parse(readFileSync(join(DIR, f), 'utf8')) as { provenance: { executed_at: string } }
      return run.provenance.executed_at
    })
    expect(stamps).toContain(manifest.built_at)
  })

  it('agrees with every manifest entry on sha256 and byte count', () => {
    const manifest = JSON.parse(readFileSync(join(DIR, 'manifest.json'), 'utf8')) as {
      entries: { file: string; sha256: string; bytes: number }[]
    }
    expect(manifest.entries.map((e) => e.file).sort()).toEqual(files.sort())
  })
})

describe('the export script reads no git metadata', () => {
  it('invokes git only for the diff, never for provenance', () => {
    const source = readFileSync(join(process.cwd(), 'scripts', 'export-lab.ts'), 'utf8')
    // Match argument literals, not the prose explaining why they are gone.
    const code = source
      .split('\n')
      .filter((l) => !/^\s*(\*|\/\/|\/\*)/.test(l))
      .join('\n')
    expect(code).not.toMatch(/'--format=%[hHcI]+'/)
    expect(code).not.toMatch(/'rev-parse'/)
    // A clock reading must not be able to reach a committed field.
    expect(code).not.toMatch(/new Date\(\)\.toISOString\(\)/)
    // Exactly one git invocation survives, and it is the diff.
    expect([...code.matchAll(/execFileSync\('git'/g)]).toHaveLength(1)
  })
})
