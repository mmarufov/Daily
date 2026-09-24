import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

/**
 * The palette has now shipped a cool-hued ground twice: the dark page at
 * #232229 (hue 249) and the light band at #17161a (hue 255), both while every
 * other token in the system sat at 12-44. Warm cream type on a violet ground
 * is what reads as muddy, and neither was caught by a contrast check, because
 * both passed contrast -- contrast is blind to hue.
 *
 * So the hue is asserted, alongside the ratios that were being tuned by eye.
 * These parse the real stylesheet rather than a copy of it; a duplicated
 * palette would just be a second thing to forget to update.
 */

const CSS = readFileSync(join(process.cwd(), 'app/globals.css'), 'utf8')

/** Everything inside `:root { ... }` up to the dark-scheme media query. */
function lightTokens(): Map<string, string> {
  const start = CSS.indexOf(':root {')
  const end = CSS.indexOf('@media (prefers-color-scheme: dark)')
  return parse(CSS.slice(start, end))
}

/** The `:root` block nested inside the dark-scheme media query. */
function darkTokens(): Map<string, string> {
  const at = CSS.indexOf('@media (prefers-color-scheme: dark)')
  const open = CSS.indexOf(':root {', at)
  // The token block ends at the first line that closes `:root` at two spaces
  // of indentation -- the media query's own brace follows on the next line.
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
  const h =
    60 *
    (max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4)
  const l = (max + min) / 2
  return { h, s: (d / (1 - Math.abs(2 * l - 1))) * 100 }
}

/**
 * Every ground, rule, ink and loss value is the same paper under more or less
 * light, so they all sit in the warm quadrant. `unknown` is the single
 * exception and is asserted separately: its meaning is "we could not
 * establish this", and the absence of warmth is the point.
 */
const WARM_MIN = 5
const WARM_MAX = 50

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
    expect(tokens.size).toBeGreaterThan(15)
  })

  it('keeps every ground, ink, rule and loss value warm', () => {
    const warm = [...tokens].filter(
      ([name]) => !name.includes('unknown') && !name.includes('grain'),
    )
    // A near-neutral has no meaningful hue to police; the failure mode being
    // guarded against is a *saturated* cool cast, not an incidental one.
    const offenders = warm
      .map(([name, value]) => ({ name, value, ...hue(value) }))
      .filter(({ h, s }) => s > 3 && (h < WARM_MIN || h > WARM_MAX))
    expect(offenders, `cool-hued tokens: ${JSON.stringify(offenders)}`).toEqual([])
  })

  it('leans the slate cool, but not far enough to shout', () => {
    const { h, s } = hue(get('--d-unknown'))
    expect(h).toBeGreaterThan(180)
    expect(h).toBeLessThan(240)
    // At S15 on a dark page it was the loudest thing on screen.
    expect(s).toBeLessThan(13)
  })

  it('holds text contrast on the page', () => {
    const page = get('--d-paper')
    expect(contrast(get('--d-ink'), page)).toBeGreaterThanOrEqual(7)
    expect(contrast(get('--d-signal'), page)).toBeGreaterThanOrEqual(4.5)
    expect(contrast(get('--d-unknown'), page)).toBeGreaterThanOrEqual(4.5)
  })

  it('holds text contrast inside the band, which is dark in both schemes', () => {
    const zone = get('--d-zone')
    expect(contrast(get('--d-zone-ink'), zone)).toBeGreaterThanOrEqual(7)
    // These two exist because the page values land at 3.43:1 and 3.38:1 here.
    expect(contrast(get('--d-zone-signal'), zone)).toBeGreaterThanOrEqual(4.5)
    expect(contrast(get('--d-zone-unknown'), zone)).toBeGreaterThanOrEqual(4.5)
  })

  it('keeps a removed cell distinguishable from a survivor', () => {
    // The sieve's alive-vs-dying pair. Below 3:1 the figure stops working.
    expect(contrast(get('--d-zone-signal'), get('--d-zone-ink'))).toBeGreaterThanOrEqual(3)
  })

  it('separates the loss ramp by chroma, since luminance has no room', () => {
    const s = [get('--d-signal'), get('--d-loss-2'), get('--d-loss-3')].map((v) => hue(v).s)
    expect(s[0]).toBeGreaterThan(s[1] as number)
    expect(s[1]).toBeGreaterThan(s[2] as number)
  })
})
