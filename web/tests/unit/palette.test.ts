import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

// Verify the actual shared tokens, including secondary text and semantic states.
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

  it('holds text contrast on the page', () => {
    const page = get('--d-paper')
    expect(contrast(get('--d-ink'), page)).toBeGreaterThanOrEqual(7)
    expect(contrast(get('--d-signal'), page)).toBeGreaterThanOrEqual(4.5)
    for (const token of ['--d-unknown', '--d-ink-58', '--d-ink-38', '--d-success', '--d-caution']) {
      expect(contrast(get(token), page), token).toBeGreaterThanOrEqual(4.5)
    }
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

  it('keeps status symbols readable on filled, empty, and excluded cells', () => {
    for (const [foreground, background] of [
      ['--d-paper', '--d-success'], ['--d-paper', '--d-signal'],
      ['--d-ink-58', '--d-paper-2'], ['--d-ink-38', '--d-paper'],
      ['--d-signal', '--d-paper'],
    ] as const) {
      expect(contrast(get(foreground), get(background)), `${foreground} on ${background}`).toBeGreaterThanOrEqual(3)
    }
  })

})
