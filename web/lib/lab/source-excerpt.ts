/**
 * The only way the investigator reads this repository.
 *
 * Every allowed file is a separate literal `join`, which looks repetitive and
 * is deliberate on two counts.
 *
 *  - A single check between a model and a filesystem is one too few. The tool
 *    schema narrows `path` to a literal union; this switch narrows it again,
 *    and a value surviving both is one of four strings chosen in advance.
 *  - `join(root, callerSuppliedPath)` is, to a bundler, a reference to the
 *    whole directory. Turbopack tried to resolve it, walked into
 *    `backend/venv`, and panicked on `bin/python` — a symlink pointing out of
 *    the filesystem root. Each arm here resolves to one known file, so there
 *    is nothing to walk.
 *
 * The second reason is a build detail; the first is the one that would keep
 * this shape even if bundlers stopped caring.
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { EVIDENCE_ROOT } from './evidence-path'

const ROOT = EVIDENCE_ROOT

function resolve(path: string): string | null {
  switch (path) {
    case 'backend/lab/contract/versions/positional_v0.py':
      return join(ROOT, 'backend', 'lab', 'contract', 'versions', 'positional_v0.py')
    case 'backend/lab/contract/versions/count_guard_v1.py':
      return join(ROOT, 'backend', 'lab', 'contract', 'versions', 'count_guard_v1.py')
    case 'backend/app/services/openai_service.py':
      return join(ROOT, 'backend', 'app', 'services', 'openai_service.py')
    case 'backend/app/services/ranking_contract.py':
      return join(ROOT, 'backend', 'app', 'services', 'ranking_contract.py')
    default:
      return null
  }
}

export function readSourceExcerpt(path: string, startLine: number, lineCount: number): string {
  const absolute = resolve(path)
  if (absolute === null) throw new Error(`${path} is not readable by the investigator`)
  return readFileSync(absolute, 'utf8')
    .split('\n')
    .slice(startLine - 1, startLine - 1 + lineCount)
    .map((line, i) => `${startLine + i}\t${line}`)
    .join('\n')
}
