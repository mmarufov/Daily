import { describe, expect, it } from 'vitest'
import { buildContrastPaths } from '../../lib/hero-contrast'

const empty = 'path("M0 0")'
const pixels = (...grays: number[]) => new Uint8ClampedArray(grays.flatMap(gray => [gray, gray, gray, 255]))
const paper = [250, 250, 249] as const
const ink = [82, 82, 82] as const

describe('hero text contrast masks', () => {
  it('leaves readable text unchanged over clear light water', () => {
    expect(buildContrastPaths(pixels(0), 1, 1, 2, 2, paper, ink, false)).toEqual({ light: empty, dark: empty })
  })

  it('uses light text over a dark shark in the light theme', () => {
    expect(buildContrastPaths(pixels(230), 1, 1, 2, 2, paper, ink, false)).toEqual({ light: 'path("M0 0h2v2h-2Z")', dark: empty })
  })

  it('uses dark text when medium gray makes the original gray text unreadable', () => {
    expect(buildContrastPaths(pixels(100), 1, 1, 2, 2, paper, ink, false)).toEqual({ light: empty, dark: 'path("M0 0h2v2h-2Z")' })
  })

  it('composes the screen blend in dark mode and preserves clear water', () => {
    expect(buildContrastPaths(pixels(0, 200), 2, 1, 4, 2, [23, 23, 23], [170, 170, 170], true)).toEqual({ light: empty, dark: 'path("M2 0h2v2h-2Z")' })
  })

  it('merges adjacent samples into one rectangle per row and keeps separated runs apart', () => {
    expect(buildContrastPaths(pixels(230, 230, 0, 230, 0, 100, 100, 0), 4, 2, 8, 4, paper, ink, false)).toEqual({
      light: 'path("M0 0h4v2h-4ZM6 0h2v2h-2Z")', dark: 'path("M2 2h4v2h-4Z")',
    })
  })

  it('handles transparent samples as paper and preserves fractional dimensions', () => {
    expect(buildContrastPaths(new Uint8ClampedArray([255, 255, 255, 0]), 1, 1, 1.5, 1.75, paper, ink, false)).toEqual({ light: empty, dark: empty })
    expect(buildContrastPaths(pixels(230), 1, 1, 1.5, 1.75, paper, ink, false).light).toBe('path("M0 0h1.5v1.75h-1.5Z")')
  })

  it.each([false, true])('keeps chosen black or white ink above 4.5:1 across every gray sample (dark=%s)', darkTheme => {
    const backgroundPaper = darkTheme ? [23, 23, 23] as const : paper
    const originalInk = darkTheme ? [170, 170, 170] as const : ink
    const luminance = (channels: readonly number[]) => channels.reduce((total, value, index) => {
      const channel = value / 255
      const linear = channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4
      return total + linear * [.2126, .7152, .0722][index]!
    }, 0)
    for (let source = 0; source <= 255; source++) {
      const result = buildContrastPaths(pixels(source), 1, 1, 2, 2, backgroundPaper, originalInk, darkTheme)
      const background = luminance(backgroundPaper.map(channel => Math.round(darkTheme
        ? source + channel * (1 - source / 255) : channel * (1 - source / 255))))
      const foreground = result.light !== empty ? 1 : result.dark !== empty ? 0 : luminance(originalInk)
      const contrast = (Math.max(background, foreground) + .05) / (Math.min(background, foreground) + .05)
      expect(contrast, `source=${source}`).toBeGreaterThanOrEqual(4.5)
    }
  })
})
