import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * The palette's rule, enforced: an instrument is grey, only its readings have
 * colour.
 *
 * Contrast checks are blind to hue, so the old warm palette shipped a violet
 * ground twice with every ratio passing. The same blindness would let a tint
 * creep back into the chrome now. So this parses the real stylesheet and
 * asserts two things a contrast check cannot see: every chrome token is
 * exactly neutral, and every reading token sits in its own hue family.
 */

const CSS = readFileSync(join(process.cwd(), 'app/globals.css'), 'utf8')

/** Everything inside the first `:root { ... }`, up to the dark-scheme media query. */
function lightTokens(): Map<string, string> {
  const start = CSS.indexOf(':root {')
  const end = CSS.indexOf('@media (prefers-color-scheme: dark)')
  return parse(CSS.slice(start, end))
}

/** The `:root` block nested inside the dark-scheme media query. */
function darkTokens(): Map<string, string> {
  const at = CSS.indexOf('@media (prefers-color-scheme: dark)')
  const open = CSS.indexOf(':root {', at)
  const end = CSS.indexOf('\n  }', open)
  return parse(CSS.slice(open, end))
}

function parse(block: string): Map<string, string> {
  const out = new Map<string, string>()
  for (const m of block.matchAll(/(--[a-z0-9-]+)\s*:\s*(#[0-9a-fA-F]{6})\s*;/g)) {
    out.set(m[1] as string, (m[2] as string).toLowerCase())
  }
  return out
}

function channels(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255) as [number, number, number]
}

function luminance(hex: string): number {
  const [r, g, b] = channels(hex).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * (r as number) + 0.7152 * (g as number) + 0.0722 * (b as number)
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}

/** Hue in degrees, and saturation as a percentage. */
function hue(hex: string): { h: number; s: number } {
  const [r, g, b] = channels(hex)
  const max = Math.max(r, g, b)
  const min = Math.min(r, g, b)
  const d = max - min
  if (d === 0) return { h: 0, s: 0 }
  const h = 60 * (max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4)
  const l = (max + min) / 2
  return { h, s: (d / (1 - Math.abs(2 * l - 1))) * 100 }
}

/** The only tokens allowed a hue: a measured loss, and a measurement that could not be made. */
const READINGS = ['--d-signal', '--d-loss', '--d-loss-2', '--d-loss-3', '--d-signal-wash', '--d-unknown']

/** Red, either side of zero. */
function isRed(h: number): boolean {
  return h >= 350 || h <= 8
}

describe.each([
  ['light', lightTokens()],
  ['dark', darkTokens()],
])('%s scheme', (_scheme, tokens) => {
  const get = (name: string): string => {
    const v = tokens.get(name)
    expect(v, `${name} is missing or is not a 6-digit hex`).toBeTypeOf('string')
    return v as string
  }

  it('parses a palette at all', () => {
    expect(tokens.size).toBeGreaterThan(14)
  })

  it('keeps every chrome token exactly neutral', () => {
    const chrome = [...tokens].filter(([name]) => !READINGS.includes(name))
    expect(chrome.length).toBeGreaterThan(8)
    const tinted = chrome.filter(([, value]) => {
      const [r, g, b] = channels(value)
      return r !== g || g !== b
    })
    expect(tinted, `chrome tokens with a hue: ${JSON.stringify(tinted)}`).toEqual([])
  })

  it('keeps every loss reading in one red family', () => {
    const off = ['--d-signal', '--d-loss', '--d-loss-2', '--d-loss-3', '--d-signal-wash']
      .map((name) => ({ name, ...hue(get(name)) }))
      .filter(({ h }) => !isRed(h))
    expect(off).toEqual([])
  })

  it('leans the unknown slate cool, but not far enough to shout', () => {
    const { h, s } = hue(get('--d-unknown'))
    expect(h).toBeGreaterThan(180)
    expect(h).toBeLessThan(240)
    expect(s).toBeLessThan(13)
  })

  it('holds text contrast on every surface text sits on', () => {
    for (const surface of ['--d-paper', '--d-sheet', '--d-paper-2']) {
      const bg = get(surface)
      expect(contrast(get('--d-ink'), bg), `ink on ${surface}`).toBeGreaterThanOrEqual(7)
      expect(contrast(get('--d-ink-58'), bg), `ink-58 on ${surface}`).toBeGreaterThanOrEqual(4.5)
      expect(contrast(get('--d-ink-38'), bg), `ink-38 on ${surface}`).toBeGreaterThanOrEqual(4.5)
      expect(contrast(get('--d-signal'), bg), `signal on ${surface}`).toBeGreaterThanOrEqual(4.5)
      expect(contrast(get('--d-unknown'), bg), `unknown on ${surface}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('keeps loss text readable on its own wash', () => {
    expect(contrast(get('--d-signal'), get('--d-signal-wash'))).toBeGreaterThanOrEqual(4.5)
  })

  it('keeps a removed cell distinguishable from a survivor and from the ground', () => {
    const ghost = get('--d-ghost')
    // Dying (loss) against removed (ghost) is the pair the sieve depends on.
    expect(contrast(get('--d-loss'), ghost)).toBeGreaterThanOrEqual(3)
    expect(contrast(get('--d-ink'), ghost)).toBeGreaterThanOrEqual(3)
    expect(contrast(get('--d-loss'), get('--d-sheet'))).toBeGreaterThanOrEqual(3)
  })

  it('marks a control boundary at 3:1', () => {
    expect(contrast(get('--d-control'), get('--d-sheet'))).toBeGreaterThanOrEqual(3)
  })

  it('steps the loss ramp away from the mark red', () => {
    const page = get('--d-paper')
    const c = [get('--d-loss'), get('--d-loss-2'), get('--d-loss-3')].map((v) => contrast(v, page))
    expect(c[0]).toBeGreaterThan(c[1] as number)
    expect(c[1]).toBeGreaterThan(c[2] as number)
  })
})
