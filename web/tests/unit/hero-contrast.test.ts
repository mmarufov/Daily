import { describe, expect, it } from 'vitest'
import { buildOverlapPath } from '../../lib/hero-contrast'

const empty = 'path("M0 0")'
const pixels = (...grays: number[]) => new Uint8ClampedArray(grays.flatMap(gray => [gray, gray, gray, 255]))

describe('hero accent overlap mask', () => {
  it('leaves clear water and the permanent grid unchanged', () => {
    expect(buildOverlapPath(pixels(0, 7, 14, 18), 4, 1, 8, 2)).toBe(empty)
  })

  it('reacts to the first visible shading without waiting for low contrast', () => {
    expect(buildOverlapPath(pixels(19, 32), 2, 1, 4, 2)).toBe('path("M0 0h4v2h-4Z")')
  })

  it('uses the same mask for pale, middle and deep shark cells', () => {
    expect(buildOverlapPath(pixels(32, 128, 255), 3, 1, 6, 2)).toBe('path("M0 0h6v2h-6Z")')
  })

  it('detects restrained colored accents without requiring gray pixels', () => {
    expect(buildOverlapPath(new Uint8ClampedArray([0, 0, 90, 255]), 1, 1, 2, 2)).toBe('path("M0 0h2v2h-2Z")')
  })

  it('merges neighboring samples and preserves clear gaps', () => {
    expect(buildOverlapPath(pixels(230, 230, 0, 230, 0, 100, 100, 0), 4, 2, 8, 4)).toBe(
      'path("M0 0h4v2h-4ZM6 0h2v2h-2ZM2 2h4v2h-4Z")')
  })

  it('ignores transparent pixels and preserves fractional dimensions', () => {
    expect(buildOverlapPath(new Uint8ClampedArray([255, 255, 255, 0]), 1, 1, 1.5, 1.75)).toBe(empty)
    expect(buildOverlapPath(pixels(230), 1, 1, 1.5, 1.75)).toBe('path("M0 0h1.5v1.75h-1.5Z")')
  })

  it('restores normal ink on the next frame without retaining the previous mask', () => {
    expect(buildOverlapPath(pixels(100), 1, 1, 2, 2)).not.toBe(empty)
    expect(buildOverlapPath(pixels(0), 1, 1, 2, 2)).toBe(empty)
  })
})
