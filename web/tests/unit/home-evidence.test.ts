import { describe, expect, it } from 'vitest'

import { loadHomeEvidence } from '../../lib/home'

/**
 * The homepage's sentences are written around specific recorded values. Each
 * value is read from a committed file at build time, so if the data moves,
 * the page moves with it; these pin what the data says today, so a change in
 * a source file cannot silently change the story the copy tells.
 */
describe('homepage evidence', async () => {
  const e = await loadHomeEvidence()

  it('reads the pinned run and fixture', () => {
    expect(e.run?.id).toBe('prod-llm__2026-09-02__47edb50')
    expect(e.run?.k).toBe(12)
    const steps = e.sieve?.steps ?? []
    expect(steps).toHaveLength(10)
    expect(steps[0]?.survivors).toBe(1362)
    expect(steps[steps.length - 1]?.survivors).toBe(50)
  })

  it('attributes 97 misses, 75 of them at the recency window', () => {
    expect(e.misses?.total).toBe(97)
    expect(e.misses?.stages.map((s) => [s.key, s.count])).toEqual([
      ['lookback', 75],
      ['prefilter:cap', 9],
      ['blended', 9],
      ['rank', 4],
    ])
  })

  it('reads the ladder, and finds exactly one reader at zero in this run', () => {
    expect(e.ladder?.reached.toFixed(4)).toBe('0.3211')
    expect(e.ladder?.delivered.toFixed(4)).toBe('0.2207')
    expect(e.ladder?.fixtures).toHaveLength(10)
    // The old homepage said two. In this run it is one; the two-zero figure
    // belongs to the 2026-08-31 quiet snapshot.
    expect(e.ladder?.fixtures.filter((f) => f.delivered === 0).map((f) => f.name)).toEqual(['Will'])
  })

  it('reads the defect batch from the case suite, not from a summary', () => {
    expect(e.defect?.caseId).toBe('observed-2026-09-02-040')
    expect(e.defect?.articles).toHaveLength(40)
    expect(e.defect?.returned).toBe(254)
    expect(e.defect?.loop.start).toBe(16)
    expect(e.defect?.loop.count).toBe(238)
    expect(e.defect?.distinct).toHaveLength(16)
    expect(e.defect?.finishReason).toBe('stop')
  })

  it('compares the guarded replay on identical inputs only', () => {
    const m = new Map(e.guard?.metrics.map((x) => [x.key, x]) ?? [])
    expect(e.guard?.revision).toBe('3b11a3c')
    expect(m.get('recall_at_k_mean')?.before).toBe(0.2207)
    expect(m.get('recall_at_k_mean')?.after).toBe(0.1866)
    expect(m.get('never_rate_mean')?.before).toBe(0.2694)
    expect(m.get('never_rate_mean')?.after).toBe(0.425)
    expect(m.get('recall_at_retrieval_mean')?.before).toBe(m.get('recall_at_retrieval_mean')?.after)
  })

  it('shows a recorded production run that was graded, with its microVM evidence', () => {
    const body = e.recorded?.body
    expect(body?.run_id).toBe('wrun_01M3WXWPKMF3H8Q66KZA56MZCV')
    expect(body?.outcome?.verdict).toBe('rejected')
    expect(body?.outcome?.grading?.cases).toHaveLength(64)
    expect(body?.outcome?.sandbox?.network_policy).toBe('deny-all')
    expect(body?.outcome?.sandbox?.isolation.every((p) => p.held)).toBe(true)
    expect(e.recorded?.preset).toBe('count-guard-v1')
  })

  it('counts the Lab and the corpus from their sources', () => {
    expect(e.lab?.recordedCases).toBe(42)
    expect(e.lab?.faultCases).toBe(22)
    expect(e.lab?.runs).toBe(39)
    expect(e.lab?.specHash).toBe('f027762ab4d08b35')
    expect(e.corpus).toEqual({ labels: 11413, snapshots: 3 })
  })
})
