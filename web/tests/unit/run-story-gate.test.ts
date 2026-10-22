import { describe, expect, it } from 'vitest'
import { StoryGate, normalizeStoryDelta } from '../../lib/run-story-gate'

describe('controlled story input', () => {
  it('accumulates a deliberate pull and starts only the adjacent chapter', () => {
    const gate = new StoryGate()
    gate.enter(0)
    expect(gate.input(100, 0)).toEqual({ consume: true })
    expect(gate.input(59, 10)).toEqual({ consume: true })
    expect(gate.stage).toBe(0)
    expect(gate.input(5000, 20)).toEqual({ consume: true, moveTo: 1 })
    expect(gate.phase).toBe('transitioning')
    expect(gate.stage).toBe(1)
    expect(gate.visual).toBe(0.08)
  })

  it('starts a new pull when the direction changes', () => {
    const gate = new StoryGate()
    gate.enter(2)
    gate.input(159, 0)
    expect(gate.input(-100, 10)).toEqual({ consume: true })
    expect(gate.input(-60, 20)).toEqual({ consume: true, moveTo: 1 })
  })

  it('allows native input outside the sequence and after bypass', () => {
    const gate = new StoryGate()
    expect(gate.input(5000, 0)).toEqual({ consume: false })
    gate.enter(1)
    gate.bypass()
    expect(gate.input(5000, 1)).toEqual({ consume: false })
    expect(gate.visual).toBe(0.32)
    gate.leave(3)
    expect(gate.phase).toBe('outside')
    expect(gate.visual).toBe(0.92)
  })

  it.each([[0, -1], [3, 1]])('releases a qualifying pull beyond chapter %s', (stage, direction) => {
    const gate = new StoryGate()
    gate.enter(stage)
    expect(gate.input(direction * 159, 0)).toEqual({ consume: true })
    expect(gate.input(direction, 1)).toEqual({ consume: false })
    expect(gate.phase).toBe('bypass')
    expect(gate.stage).toBe(stage)
  })

  it.each([[10, 0, 900, 10], [-10, 1, 900, -160], [2, 2, 900, 1800]])(
    'normalizes wheel delta %s in mode %s', (delta, mode, height, expected) => {
      expect(normalizeStoryDelta(delta, mode, height)).toBe(expected)
    },
  )

  it('keeps small pulls through zero-delta events without accepting invalid input', () => {
    const gate = new StoryGate()
    gate.enter(1)
    gate.input(100, 0)
    for (const delta of [0, Number.NaN, Infinity, -Infinity]) {
      expect(gate.input(delta, 1)).toEqual({ consume: false })
    }
    expect(gate.input(60, 2)).toEqual({ consume: true, moveTo: 2 })
  })
})

function frames(gate: StoryGate, start: number, end: number) {
  for (let now = start; now <= end; now += 50) gate.tick(now)
}

describe('controlled story transitions', () => {
  it('finishes one second of motion before a 150ms settled beat', () => {
    const gate = new StoryGate()
    gate.enter(0)
    gate.input(160, 0)
    frames(gate, 50, 500)
    expect(gate.visual).toBeCloseTo(0.2)
    expect(gate.phase).toBe('transitioning')
    frames(gate, 550, 1000)
    expect(gate.visual).toBe(0.32)
    expect(gate.phase).toBe('settling')
    gate.tick(1149)
    expect(gate.phase).toBe('settling')
    expect(gate.tick(1150)).toBe(false)
    expect(gate.phase).toBe('ready')
    expect(gate.tick(1500)).toBe(false)
    expect(gate.phase).toBe('ready')
  })

  it('discards excess input during motion and settlement with no queued chapters', () => {
    const gate = new StoryGate()
    gate.enter(0)
    gate.input(5000, 0)
    for (let now = 50; now <= 1100; now += 50) {
      expect(gate.input(now % 100 ? 5000 : -5000, now)).toEqual({ consume: true })
    }
    gate.tick(1150)
    expect(gate.stage).toBe(1)
    expect(gate.phase).toBe('ready')
    expect(gate.input(159, 1160)).toEqual({ consume: true })
    expect(gate.stage).toBe(1)
    expect(gate.input(1, 1170)).toEqual({ consume: true, moveTo: 2 })
  })

  it('limits resumed frame motion instead of skipping over a long stall', () => {
    const gate = new StoryGate()
    gate.enter(0)
    gate.input(160, 0)
    gate.tick(500)
    expect(gate.visual).toBeCloseTo(0.09536)
    gate.tick(516)
    expect(gate.visual).toBeCloseTo(0.0992)
    expect(gate.phase).toBe('transitioning')
  })

  it('releases interception at the deadline even when no animation frames ran', () => {
    const gate = new StoryGate()
    gate.enter(1)
    gate.input(160, 50)
    expect(gate.tick(1549)).toBe(false)
    expect(gate.tick(1550)).toBe(true)
    expect(gate.phase).toBe('bypass')
    expect(gate.visual).toBe(0.59)
    expect(gate.input(5000, 1551)).toEqual({ consume: false })
  })

  it('checks the deadline before consuming the next input', () => {
    const gate = new StoryGate()
    gate.enter(2)
    gate.input(-160, 0)
    expect(gate.input(5000, 1500)).toEqual({ consume: false })
    expect(gate.phase).toBe('bypass')
    expect(gate.visual).toBe(0.32)
  })

  it('includes the settled beat in the transition deadline', () => {
    const gate = new StoryGate()
    gate.enter(0)
    gate.input(160, 0)
    gate.tick(400)
    frames(gate, 450, 1400)
    expect(gate.phase).toBe('settling')
    expect(gate.tick(1500)).toBe(true)
    expect(gate.phase).toBe('bypass')
    expect(gate.visual).toBe(0.32)
  })

  it('settles direct selections and drops the previous transition and pull', () => {
    const gate = new StoryGate()
    gate.enter(0)
    gate.input(160, 0)
    gate.tick(50)
    gate.enter(2)
    expect(gate.phase).toBe('ready')
    expect(gate.visual).toBe(0.59)
    expect(gate.tick(5000)).toBe(false)
    gate.input(159, 5001)
    gate.bypass()
    gate.enter(2)
    expect(gate.input(1, 5002)).toEqual({ consume: true })
    expect(gate.stage).toBe(2)
    expect(gate.input(159, 5003)).toEqual({ consume: true, moveTo: 3 })
    gate.leave()
    expect(gate.phase).toBe('outside')
    expect(gate.visual).toBe(0.92)
    expect(gate.tick(10000)).toBe(false)
  })
})
