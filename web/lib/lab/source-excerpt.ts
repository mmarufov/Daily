/**
 * The only way the investigator reads this repository.
 *
 * Bounded by line range and restricted to an allowlist enforced by the tool
 * schema, so the agent cannot enumerate the tree, cannot reach the evaluator,
 * the criteria, the labels or the case expectations, and cannot read a file
 * by claiming a path that merely looks allowed. Its own module because both
 * the CLI and the workflow step need it and neither should grow its own copy.
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

/** Repository root, relative to the Next.js working directory (`web/`). */
const ROOT = join(process.cwd(), '..')

export function readSourceExcerpt(path: string, startLine: number, lineCount: number): string {
  // `path` has already been narrowed to a literal union by the tool schema;
  // this is the second check, because a single point of failure between a
  // model and the filesystem is one too few.
  if (path.includes('..') || path.startsWith('/')) throw new Error('unreadable path')
  const lines = readFileSync(join(ROOT, path), 'utf8').split('\n')
  return lines
    .slice(startLine - 1, startLine - 1 + lineCount)
    .map((l, i) => `${startLine + i}\t${l}`)
    .join('\n')
}
