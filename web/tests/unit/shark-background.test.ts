import { describe, expect, it } from 'vitest'
import { SHARK_CELLS, getSharkScene, projectSharkCell } from '../../lib/shark-background'

describe('decorative shark geometry', () => {
  it('keeps a recognizable body, paired fins and forked tail within a bounded glyph budget', () => {
    expect(SHARK_CELLS.length).toBeGreaterThan(100)
    expect(SHARK_CELLS.length).toBeLessThanOrEqual(250)
    expect(SHARK_CELLS.some(cell => cell.x > 0.7 && Math.abs(cell.y) < 0.06)).toBe(true)
    expect(SHARK_CELLS.some(cell => cell.x > -0.4 && cell.y > 0.25)).toBe(true)
    expect(SHARK_CELLS.some(cell => cell.x > -0.4 && cell.y < -0.25)).toBe(true)
    expect(SHARK_CELLS.some(cell => cell.x < -0.8 && cell.y > 0.12)).toBe(true)
    expect(SHARK_CELLS.some(cell => cell.x < -0.8 && cell.y < -0.12)).toBe(true)
  })

  it('produces deterministic, finite frames with fewer sharks on narrow screens', () => {
    for (const [width, height, count] of [[390, 1000, 2], [1440, 650, 3], [1920, 900, 3]]) {
      const poses = getSharkScene(width!, height!, 0)
      expect(poses).toHaveLength(count!)
      expect(poses).toEqual(getSharkScene(width!, height!, 0))
      for (const pose of poses) {
        expect(pose.scale).toBeGreaterThan(60)
        expect(pose.scale).toBeLessThan(300)
        for (const cell of SHARK_CELLS) {
          const point = projectSharkCell(cell, pose, 1)
          expect(Number.isFinite(point.x) && Number.isFinite(point.y)).toBe(true)
        }
      }
    }
  })

  it('drifts continuously without a reset at the cycle boundary', () => {
    const before = getSharkScene(1440, 650, 119.999)
    const after = getSharkScene(1440, 650, 120.001)
    expect(getSharkScene(1440, 650, 0)).not.toEqual(getSharkScene(1440, 650, 10))
    for (let i = 0; i < before.length; i++) {
      expect(Math.hypot(before[i]!.x - after[i]!.x, before[i]!.y - after[i]!.y)).toBeLessThan(0.05)
      expect(Math.abs(before[i]!.angle - after[i]!.angle)).toBeLessThan(0.001)
    }
  })

  it('moves the tail while keeping the nose attached to the swimming direction', () => {
    const pose = {x: 0, y: 0, scale: 100, angle: 0, opacity: 1}
    const nose = {x: .8, y: 0, glyph: ':', alpha: 1}
    const tail = {x: -.9, y: .15, glyph: ':', alpha: 1}
    expect(projectSharkCell(nose, pose, 0)).toEqual(projectSharkCell(nose, pose, 1))
    expect(projectSharkCell(tail, pose, 0)).not.toEqual(projectSharkCell(tail, pose, 1))
  })

  it('leaves an empty surface when layout has no usable dimensions', () => {
    for (const [width, height] of [[0, 100], [100, 0], [-1, 100], [NaN, 100], [100, Infinity]]) {
      expect(getSharkScene(width!, height!, 0)).toEqual([])
    }
  })
})
