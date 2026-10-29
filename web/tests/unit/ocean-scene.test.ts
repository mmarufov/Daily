import { afterEach, describe, expect, it, vi } from 'vitest'
import { createOceanScene, OceanClock, resizeOceanScene } from '../../lib/ocean-scene'

afterEach(() => vi.restoreAllMocks())

function seededRandom() {
  let state = 1
  vi.spyOn(Math, 'random').mockImplementation(() => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0
    return state / 4294967296
  })
}

describe('ocean scene integration', () => {
  it('starts with a recognizable shark in the water above the desktop content', () => {
    const world = createOceanScene(1440, 823, 12, 18)
    const top = world.sharks.find(shark => shark.nodes[1]! < 120)!
    expect(top).toBeDefined()
    expect(top.length).toBeGreaterThan(250)
    expect(top.nodes[0]! - top.nodes[top.nodes.length - 2]!).toBeGreaterThan(250)
    for (let n = 0; n < top.nodes.length; n += 2) {
      expect(top.nodes[n]).toBeGreaterThan(0)
      expect(top.nodes[n]).toBeLessThan(700)
      expect(top.nodes[n + 1]).toBeGreaterThan(35)
      expect(top.nodes[n + 1]).toBeLessThan(120)
    }
    expect(world.fish.length).toBeLessThanOrEqual(160)
  })

  it('travels visibly within five seconds using the upstream steering', () => {
    seededRandom()
    const world = createOceanScene(1440, 823, 12, 18)
    const starts = world.sharks.map(shark => [shark.nodes[0]!, shark.nodes[1]!] as const)
    for (let i = 0; i < 300; i++) world.step(1 / 60)
    const distances = world.sharks.map((shark, i) => Math.hypot(shark.nodes[0]! - starts[i]![0], shark.nodes[1]! - starts[i]![1]))
    expect(Math.max(...distances)).toBeGreaterThan(150)
    expect(Math.min(...distances)).toBeGreaterThan(60)
    expect(world.pointer.active).toBe(false)
    for (const shark of world.sharks) expect(Array.from(shark.nodes).every(Number.isFinite)).toBe(true)
  })

  it('maps existing actors into a narrow viewport while changing the roster and keeping simulation time', () => {
    seededRandom()
    const world = createOceanScene(1440, 823, 12, 18)
    for (let i = 0; i < 120; i++) world.step(1 / 60)
    const head = world.sharks.find(shark => shark.id === 1)!.nodes.slice(0, 2)
    const resized = resizeOceanScene(world, 390, 1050, 8, 12)
    expect(resized.sharks).toHaveLength(2)
    expect(resized.fish.length).toBeLessThanOrEqual(70)
    expect(resized.time).toBe(world.time)
    const retained = resized.sharks.find(shark => shark.id === 1)!
    expect(retained.nodes[0]).toBeCloseTo(head[0]! / 1440 * 390, 3)
    expect(retained.nodes[1]).toBeCloseTo(head[1]! / 823 * 1050, 3)
    expect(retained.length).toBeGreaterThan(200)
    expect(retained.length).toBeLessThan(300)
    for (const shark of resized.sharks) expect(Array.from(shark.nodes).every(Number.isFinite)).toBe(true)
    const wide = resizeOceanScene(resized, 1440, 823, 12, 18)
    expect(wide.sharks).toHaveLength(4)
    expect(wide.time).toBe(world.time)
  })
})

describe('ocean frame clock', () => {
  it('renders at 30fps while advancing a full second of 60Hz simulation', () => {
    const clock = new OceanClock()
    let renders = 0, steps = 0
    for (let i = 0; i <= 120; i++) {
      const next = clock.advance(i * 1000 / 120)
      if (next !== null) { renders++; steps += next }
    }
    expect(renders).toBeLessThanOrEqual(31)
    expect(renders).toBeGreaterThanOrEqual(30)
    expect(steps).toBeGreaterThanOrEqual(59)
    expect(steps).toBeLessThanOrEqual(60)
  })

  it('discards inactive time and bounds work after a stalled frame', () => {
    const clock = new OceanClock()
    clock.advance(0)
    expect(clock.advance(34)).toBe(2)
    clock.reset()
    expect(clock.advance(60_000)).toBe(0)
    expect(clock.advance(60_016)).toBeNull()
    expect(clock.advance(60_034)).toBe(2)
    expect(clock.advance(120_000)).toBe(4)
    expect(clock.advance(120_034)).toBe(2)
  })
})
