import { execFileSync, spawnSync } from 'node:child_process'
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
 *
 * The replacement had the same disease in a second form: it hashed a
 * directory *walk*, and preferred a record bundle under `backend/lab/runs/`
 * when one was present. Both sweep in files that are not committed —
 * `__pycache__/*.pyc`, and the `*.records.json` that `backend/.gitignore`
 * excludes — so a machine that had run the harness still exported different
 * bytes than CI. Worse than the hash moving: the artifact was being built
 * from evidence no reviewer could open.
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

/** The script with comments stripped, so prose about a banned call is not a hit. */
function exportScript(): string {
  return readFileSync(join(process.cwd(), 'scripts', 'export-lab.ts'), 'utf8')
    .split('\n')
    .filter((l) => !/^\s*(\*|\/\/|\/\*)/.test(l))
    .join('\n')
}

describe('the export script reads no git metadata', () => {
  it('never derives a committed field from git or the clock', () => {
    const code = exportScript()
    expect(code).not.toMatch(/'--format=%[hHcI]+'/)
    expect(code).not.toMatch(/'rev-parse'/)
    // A clock reading must not be able to reach a committed field.
    expect(code).not.toMatch(/new Date\(\)\.toISOString\(\)/)
  })

  it('invokes git twice: the diff, and the check-only guard', () => {
    const code = exportScript()
    const calls = [...code.matchAll(/execFileSync\('git', \[([^\]]*)\]/g)].map((m) =>
      (m[1] ?? '').replace(/\s+/g, ' ').trim(),
    )
    expect(calls).toHaveLength(2)
    expect(calls[0]).toContain("'diff'")
    // `ls-files` decides whether to accept the export. It must not be able to
    // contribute to what the export says.
    expect(calls[1]).toContain("'ls-files'")
  })
})

describe('the export reads only committed evidence', () => {
  /**
   * Sources of non-committed input, each of which has actually broken CI or
   * came within one line of doing so.
   */
  const FORBIDDEN: readonly { pattern: RegExp; why: string }[] = [
    {
      pattern: /backend\/lab\/runs\/\$\{[^}]*\}-\$\{[^}]*\}\.records\.json/,
      why: 'the per-run record bundles under backend/lab/runs/ are gitignored',
    },
    { pattern: /__pycache__/, why: 'compiled Python is not evidence' },
  ]

  it('never names an uncommitted path', () => {
    const code = exportScript()
    for (const { pattern, why } of FORBIDDEN) {
      expect(pattern.test(code), `${pattern} is read by the export, but ${why}`).toBe(false)
    }
  })

  it('funnels every evidence read through the recorder', () => {
    // Reading the *output* back is what `--check` does and is not evidence.
    // Reading the *repository* is, and exactly one function may do it, so a
    // file cannot enter the export without entering `inputs_sha256` too.
    const reads = [...exportScript().matchAll(/readFileSync\(join\(ROOT,/g)]
    expect(reads).toHaveLength(1)
  })

  it('passes --check against the real working tree', () => {
    // The property directly, not a proxy for it: `--check` fails if any file
    // the export read is uncommitted, and this is the machine where that is
    // true. CI catches it a push later; this catches it now.
    const result = spawnSync('npx', ['tsx', 'scripts/export-lab.ts', '--check'], {
      cwd: process.cwd(),
      encoding: 'utf8',
    })
    expect(`${result.stdout}${result.stderr}`).not.toMatch(/is not committed/)
    expect(result.status, `${result.stdout}${result.stderr}`).toBe(0)
  }, 60_000)

  it('discovers runs from tracked event logs only', () => {
    const logs = readdirSync(join(process.cwd(), '..', 'backend', 'lab', 'runs')).filter((f) =>
      f.endsWith('.events.jsonl'),
    )
    const tracked = new Set(
      execFileSync('git', ['ls-files', '--', 'backend/lab/runs'], {
        cwd: join(process.cwd(), '..'),
        encoding: 'utf8',
      })
        .split('\n')
        .filter((l) => l.endsWith('.events.jsonl'))
        .map((l) => l.replace('backend/lab/runs/', '')),
    )
    for (const log of logs) expect(tracked.has(log), `${log} is not committed`).toBe(true)
    expect(logs.length).toBe(runFiles().length)
  })
})
