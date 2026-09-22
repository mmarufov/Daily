/**
 * The patch scope gate.
 *
 * A candidate may rewrite exactly one file. Everything else — the evaluator,
 * the cases, the labels, the tests, the thresholds, the dependencies, the
 * publishing workflow — is outside its reach, and this module is where that is
 * enforced rather than merely intended.
 *
 * The gate is deliberately an **allowlist of exact paths**, not a denylist of
 * bad ones. A denylist has to anticipate every encoding of "escape the
 * directory"; an allowlist has to recognise one string. The forbidden-prefix
 * list exists only so a refusal can explain *which* boundary was crossed, and
 * is checked after the allowlist has already decided.
 */

import { isAbsolute, normalize } from 'node:path'

import { ALLOWED_PATCH_PATHS, FORBIDDEN_PATCH_PREFIXES } from './spec'

/** A candidate may not submit a file larger than this. */
export const MAX_PATCH_BYTES = 64 * 1024

export interface PatchFile {
  readonly path: string
  readonly content: string
}

export type ScopeRejection =
  | 'empty-patch'
  | 'too-many-files'
  | 'absolute-path'
  | 'traversal'
  | 'null-byte'
  | 'backslash'
  | 'not-allowed'
  | 'forbidden-area'
  | 'too-large'
  | 'duplicate-path'
  | 'symlink'

export interface ScopeResult {
  readonly allowed: boolean
  readonly rejection: ScopeRejection | null
  readonly detail: string
  /** The offending path, when a single file is to blame. */
  readonly path: string | null
}

const ALLOWED = new Set(ALLOWED_PATCH_PATHS)

function allow(): ScopeResult {
  return { allowed: true, rejection: null, detail: 'within the allowed patch scope', path: null }
}

function deny(rejection: ScopeRejection, detail: string, path: string | null = null): ScopeResult {
  return { allowed: false, rejection, detail, path }
}

/**
 * Validate a proposed patch.
 *
 * `realpaths` is supplied by the caller (which has filesystem access) mapping
 * each declared path to what it actually resolves to. A path that resolves
 * somewhere else is a symlink pointing out of scope, and is refused even
 * though its literal string is on the allowlist — the check that a denylist
 * would miss.
 */
export function checkPatchScope(
  files: readonly PatchFile[],
  realpaths: ReadonlyMap<string, string> = new Map(),
): ScopeResult {
  if (files.length === 0) return deny('empty-patch', 'a patch must change at least one file')
  if (files.length > ALLOWED.size) {
    return deny('too-many-files', `${files.length} files proposed; at most ${ALLOWED.size} allowed`)
  }

  const seen = new Set<string>()
  for (const file of files) {
    const path = file.path

    if (path.includes('\0')) return deny('null-byte', 'path contains a NUL byte', path)
    // Windows separators are not a valid way to spell a repository path, and
    // normalize() would not collapse them on POSIX.
    if (path.includes('\\')) return deny('backslash', 'path contains a backslash', path)
    if (isAbsolute(path)) return deny('absolute-path', 'paths must be repository-relative', path)

    // Check the raw string *and* the normalised form: `a/../../b` normalises
    // to `../b`, and `./backend/..%2f` never normalises at all.
    if (path.split('/').includes('..')) return deny('traversal', 'path escapes the repository', path)
    const normalised = normalize(path)
    if (normalised.startsWith('..')) return deny('traversal', 'path escapes the repository', path)
    if (normalised !== path) {
      return deny('traversal', `path is not in normal form (normalises to ${normalised})`, path)
    }

    if (seen.has(path)) return deny('duplicate-path', 'the same path appears twice', path)
    seen.add(path)

    if (Buffer.byteLength(file.content, 'utf8') > MAX_PATCH_BYTES) {
      return deny('too-large', `file exceeds ${MAX_PATCH_BYTES} bytes`, path)
    }

    if (!ALLOWED.has(path)) {
      const forbidden = FORBIDDEN_PATCH_PREFIXES.find((f) => path.startsWith(f.prefix))
      if (forbidden !== undefined) {
        return deny('forbidden-area', `${path} is off limits: ${forbidden.reason}`, path)
      }
      return deny(
        'not-allowed',
        `${path} is not in the allowed scope (${[...ALLOWED].join(', ')})`,
        path,
      )
    }

    const real = realpaths.get(path)
    if (real !== undefined && real !== path) {
      return deny('symlink', `${path} resolves to ${real}, which is outside the scope`, path)
    }
  }

  return allow()
}
