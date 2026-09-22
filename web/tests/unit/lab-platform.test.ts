import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { investigate } from '@/lib/lab/agent'
import { BUDGET, readiness } from '@/lib/lab/investigator'
import { authoriseOwner } from '@/lib/lab/owner'
import { recoverAttempts } from '@/lib/lab/orchestration'
import type { RunEvent } from '@/lib/lab/runstate'
import { sandboxCredentials } from '@/lib/lab/sandbox'
import { uploadSet } from '@/lib/lab/upload-set'

/**
 * The three platform integrations, tested for the properties that make them
 * worth having rather than for the fact that they are wired up.
 *
 * Every test here is about a *refusal*. That is not a stylistic choice: the
 * sandbox, the owner gate and the budget are all things whose value is
 * entirely in what they decline to do, and a suite that only exercises the
 * happy path of a security boundary has tested the least interesting half.
 */

const LAB = join(process.cwd(), '..', 'backend', 'lab')

describe('the sandbox credential check', () => {
  it('fails closed, naming what is missing', () => {
    const result = sandboxCredentials({})
    expect('missing' in result && result.missing).toEqual([
      'VERCEL_TOKEN',
      'VERCEL_TEAM_ID',
      'VERCEL_PROJECT_ID',
    ])
  })

  it('treats a partial local credential set as a misconfiguration, not a fallback', () => {
    // OIDC supplies all three at once. Having exactly one means somebody
    // half-configured this, and silently falling back would hide that.
    const result = sandboxCredentials({ VERCEL_TOKEN: 'tok', VERCEL_OIDC_TOKEN: 'oidc' })
    expect('missing' in result).toBe(true)
  })

  it('accepts OIDC alone, which is how a deployment authenticates', () => {
    const result = sandboxCredentials({ VERCEL_OIDC_TOKEN: 'oidc' })
    expect('missing' in result).toBe(false)
  })
})

describe('what the sandbox can see', () => {
  it('uploads the harness, the cases and nothing else', async () => {
    const files = (await uploadSet(LAB)).map((f) => f.path)
    expect(files.sort()).toEqual([
      'lab/__init__.py',
      'lab/cases/observed.json',
      'lab/cases/synthetic.json',
      'lab/harness.py',
    ])
  })

  it('does not send the evaluator, the criteria or the record schema', async () => {
    const payload = (await uploadSet(LAB)).map((f) => f.content.toString('utf8')).join('\n')
    // The candidate cannot read the thing that grades it because the thing
    // that grades it was never sent. That is stronger than a permission check
    // and this is the assertion that keeps it true.
    for (const marker of ['accepted-for-review', 'ACCEPTANCE', 'CriterionResult', 'threshold']) {
      expect(payload).not.toContain(marker)
    }
  })
})

describe('the owner gate', () => {
  const req = (auth?: string): Request =>
    new Request('https://example.test/api/lab/run', {
      method: 'POST',
      ...(auth === undefined ? {} : { headers: { authorization: auth } }),
    })

  it('refuses everyone when no owner is configured', () => {
    const result = authoriseOwner(req('Bearer anything'), {})
    expect(result.ok).toBe(false)
    expect(result.ok === false && result.status).toBe(503)
  })

  it('refuses a missing, wrong, or differently-lengthed token', () => {
    const env = { LAB_OWNER_TOKEN: 'correct-horse' }
    for (const header of [undefined, 'Bearer ', 'Bearer wrong', 'Bearer correct-hors', 'correct-horse']) {
      expect(authoriseOwner(req(header), env).ok, `header ${String(header)}`).toBe(false)
    }
  })

  it('accepts the owner', () => {
    expect(authoriseOwner(req('Bearer correct-horse'), { LAB_OWNER_TOKEN: 'correct-horse' }).ok).toBe(true)
  })
})

describe('the investigator refuses before it spends', () => {
  const deps = {
    cases: [],
    readSource: () => '',
    evaluateCandidate: async () => ({ summary: '', evaluation: null }),
  }

  it('will not run without a credential', async () => {
    const result = await investigate(deps, {})
    expect(result.ok).toBe(false)
    expect(result.ok === false && result.reason).toBe('missing-credentials')
  })

  it('will not run without an explicit ceiling, even with a credential', async () => {
    const result = await investigate(deps, { AI_GATEWAY_API_KEY: 'k' })
    expect(result.ok === false && result.reason).toBe('missing-budget')
  })

  it('will not accept a ceiling above the reviewed one', async () => {
    // Raising the limit has to be a commit somebody reads, not an env var
    // somebody sets. Otherwise the budget is advisory.
    const result = await investigate(deps, {
      AI_GATEWAY_API_KEY: 'k',
      LAB_MAX_USD: String(BUDGET.max_usd + 1),
    })
    expect(result.ok === false && result.reason).toBe('missing-budget')
    expect(result.ok === false && result.needs.join(' ')).toContain('reviewed commit')
  })

  it('reports which gateway a ready environment would use', () => {
    const r = readiness({ AI_GATEWAY_API_KEY: 'k', LAB_MAX_USD: '0.25' })
    expect(r.ready && r.gateway).toBe('vercel-ai-gateway')
  })
})

describe('unknown-outcome survives the port to platform durability', () => {
  const started = (id: string): RunEvent => ({
    type: 'attempt-started',
    attempt_id: id,
    runner: 'vercel-sandbox',
    at: '2026-09-22T00:00:00.000Z',
  })

  it('calls an attempt with no journaled ending unknown, never failed', () => {
    // The microVM may have run the candidate to completion a millisecond
    // before the orchestrator died. `failed` would be a claim nobody is in a
    // position to make.
    const [attempt] = recoverAttempts([started('a#01')])
    expect(attempt?.status).toBe('unknown-outcome')
    expect(attempt?.note).toContain('not knowable')
  })

  it('reports a journaled ending as itself', () => {
    const [attempt] = recoverAttempts([
      started('a#01'),
      { type: 'attempt-ended', attempt_id: 'a#01', at: '2026-09-22T00:00:01.000Z', status: 'failed', note: 'exit 1' },
    ])
    expect(attempt?.status).toBe('failed')
  })

  it('distinguishes per attempt, so one recovery does not relabel another', () => {
    const recovered = recoverAttempts([
      started('a#01'),
      { type: 'attempt-ended', attempt_id: 'a#01', at: '2026-09-22T00:00:01.000Z', status: 'succeeded', note: 'ok' },
      started('a#02'),
    ])
    expect(recovered.map((a) => a.status)).toEqual(['succeeded', 'unknown-outcome'])
  })
})

describe('the workflow is the platform’s, not a loop in this repository', () => {
  const source = readFileSync(join(process.cwd(), 'lib', 'lab', 'orchestration.ts'), 'utf8')
  /** Comments explaining why a call is absent must not read as the call. */
  const code = source
    .split('\n')
    .filter((l) => !/^\s*(\*|\/\/|\/\*)/.test(l))
    .join('\n')

  it('declares the orchestrator and its steps with the real directives', () => {
    expect(code).toMatch(/^\s*'use workflow'$/m)
    expect([...code.matchAll(/^\s*'use step'$/gm)].length).toBeGreaterThanOrEqual(3)
  })

  it('suspends with the SDK, not with setTimeout', () => {
    // `setTimeout` holds a process open for the duration, which demonstrates
    // nothing about surviving the loss of one.
    expect(code).toContain("from 'workflow'")
    expect(code).not.toMatch(/setTimeout/)
  })

  it('gates scope before it creates anything', () => {
    expect(code.indexOf('scopeStep')).toBeLessThan(code.indexOf('executeStep'))
  })
})
