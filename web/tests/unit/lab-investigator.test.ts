import { describe, expect, it } from 'vitest'

import {
  BUDGET,
  ProposePatchInput,
  ReadSourceInput,
  readiness,
  TOOLS,
  validateProposal,
} from '@/lib/lab/investigator'
import { ALLOWED_PATCH_PATHS } from '@/lib/lab/spec'

const ALLOWED = ALLOWED_PATCH_PATHS[0]!
const proposal = (over: Record<string, unknown> = {}) => ({
  path: ALLOWED,
  content: 'def parse(articles, response):\n    return {"ok": False, "refusal": {"kind": "malformed_json"}}\n',
  hypothesis: 'The parser associates by position, so a short response shifts every later verdict.',
  evidence: ['observed-2026-09-02-000', 'backend/app/services/openai_service.py:653'],
  ...over,
})

describe('readiness — no mock, no demo mode', () => {
  it('reports missing credentials rather than falling back', () => {
    const result = readiness({})
    expect(result.ready).toBe(false)
    if (result.ready) return
    expect(result.reason).toBe('missing-credentials')
    expect(result.needs.join(' ')).toMatch(/AI_GATEWAY_API_KEY/)
  })

  it('still refuses with a key but no spending limit', () => {
    const result = readiness({ AI_GATEWAY_API_KEY: 'k' })
    expect(result.ready).toBe(false)
    if (result.ready) return
    expect(result.reason).toBe('missing-budget')
  })

  it('is ready only with both', () => {
    const result = readiness({ AI_GATEWAY_API_KEY: 'k', LAB_MAX_USD: '0.25' })
    expect(result.ready).toBe(true)
  })

  it('is not ready in this environment, which is why no agent trace is published', () => {
    expect(readiness().ready).toBe(false)
  })
})

describe('the budget is one proposal', () => {
  it('caps proposals, calls and spend', () => {
    expect(BUDGET.max_proposals).toBe(1)
    expect(BUDGET.max_model_calls).toBeLessThanOrEqual(6)
    expect(BUDGET.max_usd).toBeLessThanOrEqual(1)
    expect(BUDGET.wall_clock_seconds).toBeLessThanOrEqual(600)
  })
})

describe('tool inputs are narrow', () => {
  it('exposes exactly four tools', () => {
    expect(TOOLS.map((t) => t.name)).toEqual([
      'inspect_failure',
      'read_source_excerpt',
      'propose_patch',
      'request_evaluation',
    ])
  })

  it('refuses to read a file outside the allowlist', () => {
    expect(
      ReadSourceInput.safeParse({ path: 'web/lib/lab/evaluator.ts', start_line: 1, line_count: 10 }).success,
    ).toBe(false)
    expect(
      ReadSourceInput.safeParse({ path: 'backend/evals/labels/2026-09-02/ray.jsonl', start_line: 1, line_count: 10 }).success,
    ).toBe(false)
  })

  it('bounds an excerpt so the repository cannot be read out', () => {
    expect(
      ReadSourceInput.safeParse({
        path: 'backend/app/services/openai_service.py',
        start_line: 1,
        line_count: 5000,
      }).success,
    ).toBe(false)
  })

  it('requires a grounded hypothesis', () => {
    expect(ProposePatchInput.safeParse(proposal({ hypothesis: 'looks wrong' })).success).toBe(false)
    expect(ProposePatchInput.safeParse(proposal({ evidence: [] })).success).toBe(false)
    expect(ProposePatchInput.safeParse(proposal()).success).toBe(true)
  })
})

describe('validateProposal — the same gate a human patch faces', () => {
  it('accepts an in-scope proposal', () => {
    const outcome = validateProposal(proposal())
    expect(outcome.accepted).toBe(true)
    expect(outcome.files).toHaveLength(1)
  })

  it('refuses a patch aimed at the evaluator', () => {
    const outcome = validateProposal(proposal({ path: 'web/lib/lab/evaluator.ts' }))
    expect(outcome.accepted).toBe(false)
    // Rejected by the schema before the scope gate even sees it.
    expect(outcome.reason).toMatch(/schema/)
  })

  it('refuses a symlinked allowlisted path', () => {
    const outcome = validateProposal(
      proposal(),
      new Map([[ALLOWED, 'backend/evals/labels/2026-09-02/ray.jsonl']]),
    )
    expect(outcome.accepted).toBe(false)
    expect(outcome.reason).toMatch(/symlink/)
  })

  it('never grades the hypothesis', () => {
    // A confident, wrong justification changes nothing: acceptance here means
    // "in scope", and the verdict comes from the evaluator.
    const outcome = validateProposal(
      proposal({ hypothesis: 'This patch is definitely correct and all tests will pass.' }),
    )
    expect(outcome.accepted).toBe(true)
    expect(outcome.reason).toMatch(/queued for sandboxed evaluation/)
  })
})
