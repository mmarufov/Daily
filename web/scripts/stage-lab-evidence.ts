/**
 * Copy the evidence a deployed Lab function reads into the project root.
 *
 *   npm run stage:lab       # run automatically before dev, test and build
 *
 * The functions need the case suite, the harness and a few allowlisted
 * sources at *runtime*. All of them live in `backend/`, outside `web/`, which
 * is the Vercel Root Directory — and Next's file tracing refuses a glob that
 * navigates out of the project root, while moving the tracing root to the
 * repository breaks Turbopack's own module resolution. Reaching up is simply
 * not available.
 *
 * So the files are staged into `web/lab-evidence/` and everything reads from
 * there, in every environment, by one path. The directory is gitignored and
 * rebuilt from `backend/` on each run: a second committed copy of the case
 * suite would be a second thing that can disagree with the first, in a
 * repository whose central claim is that its evidence is one set of bytes.
 *
 * This existed because the deployed route answered `ENOENT` while every local
 * check passed — the failure mode of reading a path that happens to exist on
 * the machine you are developing on.
 */

import { cpSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { dirname, join } from 'node:path'

function repoRoot(): string {
  let dir = process.cwd()
  for (let i = 0; i < 6; i += 1) {
    if (existsSync(join(dir, 'backend')) && existsSync(join(dir, 'web'))) return dir
    dir = dirname(dir)
  }
  throw new Error('could not locate the repository root')
}

const ROOT = repoRoot()
const OUT = join(ROOT, 'web', 'lab-evidence')

/**
 * Exactly what a function may read, and nothing adjacent.
 *
 * A directory copy would sweep in `__pycache__`, the seeded controls and
 * anything else that lands in `contract/` later. This repository has already
 * been bitten once by a directory walk that quietly widened.
 */
const STAGE: readonly string[] = [
  'backend/lab/__init__.py',
  'backend/lab/harness.py',
  'backend/lab/cases/observed.json',
  'backend/lab/cases/synthetic.json',
  'backend/lab/contract/types.py',
  'backend/lab/contract/versions/positional_v0.py',
  'backend/lab/contract/versions/count_guard_v1.py',
  'backend/app/services/openai_service.py',
  'backend/app/services/ranking_contract.py',
]

function main(): void {
  rmSync(OUT, { recursive: true, force: true })
  const digests: string[] = []
  for (const rel of STAGE) {
    const from = join(ROOT, rel)
    if (!existsSync(from)) throw new Error(`cannot stage ${rel}: it does not exist`)
    const to = join(OUT, rel)
    mkdirSync(dirname(to), { recursive: true })
    cpSync(from, to)
    digests.push(`${rel}:${createHash('sha256').update(readFileSync(from)).digest('hex')}`)
  }
  // A manifest, so a function can state what it was given rather than assume.
  writeFileSync(join(OUT, 'STAGED.txt'), `${digests.join('\n')}\n`)
  console.log(`staged ${STAGE.length} files into web/lab-evidence/`)
}

main()
