import { describe, expect, it } from 'vitest'

import {
  acceptsNewWork,
  attemptId,
  INITIAL,
  isTerminal,
  replay,
  runId,
  type RunEvent,
} from '@/lib/lab/runstate'
import { KNOWN_IMPLEMENTATIONS, selectRunner, sha256 } from '@/lib/lab/runner'

const AT = '2026-09-21T12:00:00Z'
const RUN = 'article-to-verdict-association__keyed-v2__abc123def456__0badc0de'

const created: RunEvent = { type: 'created', run_id: RUN, candidate_id: 'keyed-v2', at: AT, spec_hash: '0badc0de' }
const started: RunEvent = { type: 'attempt-started', attempt_id: `${RUN}#01`, runner: 'vercel-sandbox', at: AT }
const ended: RunEvent = { type: 'attempt-ended', attempt_id: `${RUN}#01`, at: AT, status: 'succeeded', note: 'ok' }
const received: RunEvent = { type: 'records-received', attempt_id: `${RUN}#01`, at: AT, n_records: 64 }
const accepted: RunEvent = { type: 'evaluated', at: AT, verdict: 'accepted-for-review', reason: 'all criteria satisfied' }
const published: RunEvent = { type: 'published', at: AT, artifact_sha256: 'aaaa' }

const HAPPY: readonly RunEvent[] = [created, started, ended, received, accepted, published]

describe('replay — recovery is a fold, not a guess', () => {
  it('reaches the verdict from the full log', () => {
    const state = replay(HAPPY)
    expect(state.phase).toBe('accepted-for-review')
    expect(state.verdict).toBe('accepted-for-review')
    expect(state.published_sha256).toBe('aaaa')
    expect(state.attempts).toHaveLength(1)
    expect(state.attempts[0]?.status).toBe('succeeded')
  })

  it('resumes from any prefix to the same final state', () => {
    // This is the interrupted-execution property: whatever point the process
    // died at, replaying the persisted prefix and then the rest converges.
    for (let cut = 0; cut <= HAPPY.length; cut += 1) {
      const recovered = replay(HAPPY.slice(cut), replay(HAPPY.slice(0, cut)))
      expect(recovered).toEqual(replay(HAPPY))
    }
  })

  it('shows an interrupted run as still running, not as a verdict', () => {
    const state = replay([created, started])
    expect(state.phase).toBe('running')
    expect(state.verdict).toBeNull()
    expect(isTerminal(state.phase)).toBe(false)
    expect(acceptsNewWork(state)).toBe(true)
  })
})

describe('publication is idempotent', () => {
  it('keeps the first artifact and counts the duplicates', () => {
    const state = replay([...HAPPY, published, { ...published, artifact_sha256: 'bbbb' } as RunEvent])
    expect(state.published_sha256).toBe('aaaa')
    expect(state.duplicate_publications).toBe(2)
  })

  it('cannot produce two different finals from duplicate delivery', () => {
    const once = replay(HAPPY)
    const twice = replay([...HAPPY, published])
    expect(twice.verdict).toBe(once.verdict)
    expect(twice.published_sha256).toBe(once.published_sha256)
  })
})

describe('cancellation', () => {
  const cancel: RunEvent = { type: 'cancelled', at: AT, by: 'owner' }

  it('is terminal and stops new work', () => {
    const state = replay([created, started, cancel])
    expect(state.phase).toBe('cancelled')
    expect(acceptsNewWork(state)).toBe(false)
    expect(state.cancelled_by).toBe('owner')
  })

  it('leaves no attempt stuck in started', () => {
    const state = replay([created, started, cancel])
    expect(state.attempts.every((a) => a.status !== 'started')).toBe(true)
    expect(state.attempts[0]?.ended_at).toBe(AT)
  })

  it('cannot be overturned by work that was already in flight', () => {
    const state = replay([created, started, cancel, ended, received, accepted])
    expect(state.phase).toBe('cancelled')
    expect(state.verdict).toBe('cancelled')
    expect(state.ignored_after_terminal).toBeGreaterThan(0)
  })

  it('still records what the in-flight attempt reported', () => {
    const state = replay([created, started, cancel, ended])
    expect(state.attempts[0]?.note).toBe('ok')
    expect(state.attempts[0]?.status).toBe('cancelled')
  })
})

describe('an out-of-scope patch never reaches execution', () => {
  it('rejects at the scope check', () => {
    const state = replay([
      created,
      { type: 'scope-checked', at: AT, allowed: false, detail: 'web/lib/lab/spec.ts is off limits' },
    ])
    expect(state.phase).toBe('rejected')
    expect(state.verdict_reason).toMatch(/off limits/)
    expect(acceptsNewWork(state)).toBe(false)
  })
})

describe('uncertain attempts are recorded, not rounded off', () => {
  it('keeps unknown-outcome as its own status', () => {
    const state = replay([
      created,
      started,
      { type: 'attempt-ended', attempt_id: `${RUN}#01`, at: AT, status: 'unknown-outcome', note: 'sandbox timed out; the run may have completed remotely' },
    ])
    expect(state.attempts[0]?.status).toBe('unknown-outcome')
    expect(state.phase).toBe('running')
  })

  it('reconciles a retry onto the same run id', () => {
    const a = runId('exp', 'keyed-v2', 'abcdef123456789', 'spec1234')
    const b = runId('exp', 'keyed-v2', 'abcdef123456789', 'spec1234')
    expect(a).toBe(b)
    expect(attemptId(a, 1)).toBe(`${a}#01`)
    expect(attemptId(a, 2)).toBe(`${a}#02`)
  })

  it('forks a new run when the spec changes', () => {
    const before = runId('exp', 'keyed-v2', 'abcdef123456789', 'spec1234')
    const after = runId('exp', 'keyed-v2', 'abcdef123456789', 'spec9999')
    expect(before).not.toBe(after)
  })
})

describe('selectRunner — arbitrary code cannot run locally', () => {
  const known = new Map([['keyed-v2', sha256('# the committed source\n')]])

  it('permits a byte-exact known implementation', () => {
    const decision = selectRunner('# the committed source\n', known)
    expect(decision.runner).toBe('local-known')
    expect(decision.known?.candidate_id).toBe('keyed-v2')
  })

  it('sends anything else to the sandbox, however small the edit', () => {
    const decision = selectRunner('# the committed source\n\n', known)
    expect(decision.runner).toBe('vercel-sandbox')
    expect(decision.known).toBeNull()
  })

  it('ignores a claimed path and decides on bytes alone', () => {
    // A candidate asserting it is `keyed-v2` gets no credit for saying so.
    expect(selectRunner('import os; os.system("curl evil")', known).runner).toBe('vercel-sandbox')
  })

  it('labels every seeded control as a control', () => {
    const controls = KNOWN_IMPLEMENTATIONS.filter((i) => i.candidate_id.startsWith('control-'))
    expect(controls.length).toBeGreaterThan(0)
    expect(controls.every((i) => i.kind === 'seeded-control')).toBe(true)
    expect(controls.every((i) => i.description.includes('SEEDED DEFECT'))).toBe(true)
  })
})

describe('the initial state claims nothing', () => {
  it('starts with no verdict', () => {
    expect(INITIAL.verdict).toBeNull()
    expect(INITIAL.published_sha256).toBeNull()
    expect(isTerminal(INITIAL.phase)).toBe(false)
  })
})
