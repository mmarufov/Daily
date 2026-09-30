import { describe, expect, it } from 'vitest'

import { capForModel, investigate } from '@/lib/lab/agent'
import { BUDGET, readiness, resolveInvestigationBudget } from '@/lib/lab/investigator'

/**
 * A budget other than the default, passed as configuration.
 *
 * The experiment this exists for varies the budget with the model held fixed.
 * What it must not do is loosen the one property the loop protects: one
 * proposal, graded by code the model never sees, with no retry.
 */

const deps = {
  cases: [],
  readSource: () => '',
  evaluateCandidate: async () => ({ summary: '', evaluation: null }),
}

describe('resolveInvestigationBudget', () => {
  it('is the default budget, unchanged, when nothing is configured', () => {
    const r = resolveInvestigationBudget({})
    expect(r.ok && r.budget).toBe(BUDGET)
    expect(r.ok && r.label).toBe('default')
  })

  it('leaves the default constant exactly as it was', () => {
    // The override is configuration. If this moves, someone edited the
    // default to get a different cell, which changes what every run means.
    expect(BUDGET).toEqual({
      max_proposals: 1,
      max_tool_calls: 12,
      max_model_calls: 6,
      max_output_tokens: 4096,
      max_total_tokens: 150_000,
      max_tool_result_chars: 8_000,
      max_usd: 0.75,
      wall_clock_seconds: 180,
    })
  })

  it('applies the overridden fields and keeps the rest', () => {
    const r = resolveInvestigationBudget({
      LAB_BUDGET: '{"max_model_calls":3,"max_tool_calls":6,"max_total_tokens":60000}',
      LAB_BUDGET_LABEL: 'tight',
    })
    expect(r.ok).toBe(true)
    if (!r.ok) return
    expect(r.budget).toEqual({ ...BUDGET, max_model_calls: 3, max_tool_calls: 6, max_total_tokens: 60_000 })
    expect(r.label).toBe('tight')
    expect(r.overridden).toEqual(['max_model_calls', 'max_tool_calls', 'max_total_tokens'])
  })

  it('refuses to override the one-proposal rule, rather than ignoring the attempt', () => {
    // A second proposal is a retry. Silently dropping the key would let an
    // operator believe they had configured one.
    const r = resolveInvestigationBudget({ LAB_BUDGET: '{"max_proposals":3}' })
    expect(r.ok).toBe(false)
    expect(!r.ok && r.needs.join(' ')).toMatch(/max_proposals/)
  })

  it('refuses unknown keys, bad JSON, non-integers and out-of-range values', () => {
    for (const raw of [
      '{"max_tool_call":6}',
      'tight',
      '[]',
      '{"max_model_calls":2.5}',
      '{"max_model_calls":0}',
      '{"max_total_tokens":100000000}',
      '{"max_usd":-1}',
    ]) {
      expect(resolveInvestigationBudget({ LAB_BUDGET: raw }).ok, raw).toBe(false)
    }
  })

  it('refuses a label that could not be a file-safe cell name', () => {
    const r = resolveInvestigationBudget({ LAB_BUDGET: '{"max_model_calls":3}', LAB_BUDGET_LABEL: 'Tight Budget!' })
    expect(r.ok).toBe(false)
  })

  it('calls an unlabelled override custom, never default', () => {
    const r = resolveInvestigationBudget({ LAB_BUDGET: '{"max_model_calls":3}' })
    expect(r.ok && r.label).toBe('custom')
  })
})

describe('investigate refuses a bad budget before it spends', () => {
  it('returns invalid-budget with no trace, because nothing ran', async () => {
    const result = await investigate(deps, {
      AI_GATEWAY_API_KEY: 'k',
      LAB_MAX_USD: '1',
      LAB_BUDGET: '{"max_proposals":2}',
    })
    expect(result.ok).toBe(false)
    expect(result.ok === false && result.reason).toBe('invalid-budget')
    expect('trace' in result).toBe(false)
  })
})

describe('capForModel honours the budget it is given', () => {
  it('truncates at the configured limit, not the default', () => {
    const value = { text: 'x'.repeat(2_000) }
    const capped = capForModel(value, 1_000) as { truncated?: boolean; head?: string }
    expect(capped.truncated).toBe(true)
    expect(capped.head?.length).toBe(1_000)
    expect(capForModel(value)).toEqual(value)
  })
})

describe('readiness accepts the credential the gateway provider accepts', () => {
  it('is ready on a Vercel OIDC token, and records that it was one', () => {
    const r = readiness({ VERCEL_OIDC_TOKEN: 'oidc', LAB_MAX_USD: '0.25' })
    expect(r.ready).toBe(true)
    expect(r.ready && r.gateway).toBe('vercel-ai-gateway')
    expect(r.ready && r.auth).toBe('oidc')
  })

  it('reports the API key when both are present, because that is what the provider uses', () => {
    const r = readiness({ AI_GATEWAY_API_KEY: 'k', VERCEL_OIDC_TOKEN: 'oidc', LAB_MAX_USD: '0.25' })
    expect(r.ready && r.auth).toBe('api-key')
  })

  it('still needs an explicit spending limit', () => {
    const r = readiness({ VERCEL_OIDC_TOKEN: 'oidc' })
    expect(r.ready === false && r.reason).toBe('missing-budget')
  })
})
