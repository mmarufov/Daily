import { describe, expect, it } from 'vitest'

import { checkPatchScope, MAX_PATCH_BYTES } from '@/lib/lab/scope'
import { ALLOWED_PATCH_PATHS } from '@/lib/lab/spec'

const ALLOWED = ALLOWED_PATCH_PATHS[0]!
const file = (path: string, content = 'def parse(a, r):\n    return {"ok": False}\n') => ({ path, content })

describe('checkPatchScope — what it allows', () => {
  it('accepts the one allowed path', () => {
    expect(checkPatchScope([file(ALLOWED)]).allowed).toBe(true)
  })
})

describe('checkPatchScope — traversal', () => {
  const traversals = [
    '../etc/passwd',
    'backend/lab/contract/../../../etc/passwd',
    'backend/lab/contract/../../evals/labels/2026-09-02/ray.jsonl',
    './backend/lab/contract/candidate.py',
    'backend/lab/contract//candidate.py',
    'backend/./lab/contract/candidate.py',
  ]
  for (const path of traversals) {
    it(`rejects ${path}`, () => {
      const result = checkPatchScope([file(path)])
      expect(result.allowed).toBe(false)
      expect(['traversal', 'not-allowed', 'forbidden-area']).toContain(result.rejection)
    })
  }

  it('rejects an absolute path', () => {
    expect(checkPatchScope([file('/etc/passwd')]).rejection).toBe('absolute-path')
  })

  it('rejects a NUL byte and a backslash', () => {
    expect(checkPatchScope([file(`${ALLOWED}\0.txt`)]).rejection).toBe('null-byte')
    expect(checkPatchScope([file('backend\\lab\\candidate.py')]).rejection).toBe('backslash')
  })
})

describe('checkPatchScope — symlinks', () => {
  it('rejects an allowed path that resolves elsewhere', () => {
    const realpaths = new Map([[ALLOWED, 'backend/evals/labels/2026-09-02/ray.jsonl']])
    const result = checkPatchScope([file(ALLOWED)], realpaths)
    expect(result.allowed).toBe(false)
    expect(result.rejection).toBe('symlink')
    expect(result.detail).toMatch(/resolves to/)
  })

  it('accepts an allowed path that resolves to itself', () => {
    expect(checkPatchScope([file(ALLOWED)], new Map([[ALLOWED, ALLOWED]])).allowed).toBe(true)
  })
})

describe('checkPatchScope — the areas a candidate must never reach', () => {
  const forbidden: readonly [string, string][] = [
    ['web/lib/lab/evaluator.ts', 'the evaluator'],
    ['web/lib/lab/spec.ts', 'the thresholds'],
    ['backend/lab/cases/synthetic.json', 'the cases'],
    ['backend/lab/harness.py', 'the harness'],
    ['backend/evals/labels/2026-09-02/ray.jsonl', 'the labels'],
    ['backend/tests/test_lab_contract.py', 'the tests'],
    ['.github/workflows/evidence-publish.yml', 'publishing'],
    ['web/package.json', 'dependencies'],
    ['backend/requirements.txt', 'dependencies'],
  ]
  for (const [path, what] of forbidden) {
    it(`rejects ${what} (${path})`, () => {
      const result = checkPatchScope([file(path)])
      expect(result.allowed).toBe(false)
      expect(result.rejection).toBe('forbidden-area')
      expect(result.detail.length).toBeGreaterThan(10)
    })
  }

  it('rejects an unrelated in-repo file that is merely not allowed', () => {
    expect(checkPatchScope([file('README.md')]).rejection).toBe('not-allowed')
  })
})

describe('checkPatchScope — bounds', () => {
  it('rejects an empty patch', () => {
    expect(checkPatchScope([]).rejection).toBe('empty-patch')
  })

  it('rejects more files than the scope permits', () => {
    expect(checkPatchScope([file(ALLOWED), file('README.md')]).rejection).toBe('too-many-files')
  })

  it('rejects a duplicate path', () => {
    // Only reachable when the scope permits more than one file; asserted via
    // a scope of size one by submitting the same path twice.
    const result = checkPatchScope([file(ALLOWED), file(ALLOWED)])
    expect(result.allowed).toBe(false)
  })

  it('rejects an oversized file', () => {
    const result = checkPatchScope([file(ALLOWED, 'x'.repeat(MAX_PATCH_BYTES + 1))])
    expect(result.rejection).toBe('too-large')
  })
})
