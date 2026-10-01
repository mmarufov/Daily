/**
 * What a `"use workflow"` body may touch.
 *
 * The workflow body does not run in Node. It runs in the SDK's deterministic
 * sandbox, where `process.uptime` does not exist, and nothing in this suite
 * executes a workflow body under that runtime. So a Node call in one passes
 * every local check and fails on the platform: `runCandidateWorkflow` called
 * `mark()` for one timestamp, `mark()` calls `process.uptime()`, and every
 * candidate run on production died right after its scope step.
 *
 * Steps have full Node access. Workflow bodies get what the SDK's globals
 * reference lists: `process.env` as a frozen snapshot, and nothing else of
 * `process`; no `Buffer`, no timers, no global `fetch`.
 */

import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const SOURCE = readFileSync(join(process.cwd(), 'lib', 'lab', 'orchestration.ts'), 'utf8')

/** Each function whose body declares `'use workflow'`, with comments removed. */
function workflowBodies(source: string): { name: string; body: string }[] {
  const bodies: { name: string; body: string }[] = []
  const pattern = /export async function (\w+)\([^)]*\)[^{]*\{\n\s*'use workflow'/g
  for (const match of source.matchAll(pattern)) {
    const start = match.index ?? 0
    const end = source.indexOf('\n}\n', start)
    const body = source
      .slice(start, end === -1 ? undefined : end)
      .split('\n')
      .filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line))
      .join('\n')
    bodies.push({ name: match[1] as string, body })
  }
  return bodies
}

describe('workflow bodies stay inside the workflow runtime', () => {
  const bodies = workflowBodies(SOURCE)

  it('finds both workflows', () => {
    expect(bodies.map((b) => b.name).sort()).toEqual(['investigationWorkflow', 'runCandidateWorkflow'])
  })

  it.each(bodies.map((b) => [b.name, b.body] as const))('%s uses only what the workflow runtime provides', (_name, body) => {
    expect(body).not.toMatch(/\bmark\(\)/)
    expect(body).not.toMatch(/\bprocess\.(?!env\b)/)
    expect(body).not.toMatch(/\b(Buffer|setTimeout|setInterval|setImmediate)\b/)
    expect(body).not.toMatch(/(^|[^.\w])fetch\(/m)
  })
})
