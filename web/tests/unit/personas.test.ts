import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { PERSONAS, personaLabel, personaName } from '@/lib/personas'

/**
 * The display table is presentation, but it must not drift from the fixtures
 * it describes. These read `backend/evals/personas/*.json` directly, so
 * renaming a fixture without updating the table is a test failure rather than
 * a page that quietly shows the wrong name.
 */

const DIR = join(process.cwd(), '..', 'backend', 'evals', 'personas')

interface Fixture {
  key: string
  name: string
}

function fixtures(): Fixture[] {
  return readdirSync(DIR)
    .filter((f) => f.endsWith('.json') && f !== 'cache_keys.json')
    .map((f) => JSON.parse(readFileSync(join(DIR, f), 'utf8')) as Fixture)
}

describe('the persona display table', () => {
  const found = fixtures()

  it('covers every fixture exactly once', () => {
    expect(PERSONAS.map((p) => p.key).sort()).toEqual(found.map((f) => f.key).sort())
    expect(new Set(PERSONAS.map((p) => p.key)).size).toBe(PERSONAS.length)
  })

  it('matches the name each fixture declares', () => {
    for (const fixture of found) {
      // The fixture's `name` is "Daniel — Tashkent"; the table splits it.
      const [name, place] = fixture.name.split(' — ')
      const entry = PERSONAS.find((p) => p.key === fixture.key)
      expect(entry, `no display entry for ${fixture.key}`).toBeDefined()
      expect(entry?.name).toBe(name)
      if (place !== undefined) expect(entry?.place).toBe(place)
    }
  })

  it('keeps the key as the identifier and never as the display name', () => {
    // A key that equals its own display name is fine (ray -> Ray); a key
    // leaking into the interface where a name was expected is not.
    expect(personaName('dilshod')).toBe('Daniel')
    expect(personaLabel('dilshod')).toBe('Daniel — Tashkent')
  })

  it('falls back to the key rather than inventing a name', () => {
    expect(personaName('not-a-fixture')).toBe('not-a-fixture')
    expect(personaLabel('not-a-fixture')).toBe('not-a-fixture')
  })

  it('shows names a reader outside Central Asia will recognise', () => {
    // The point of the change: no fixture should read as an unfamiliar
    // transliteration in the interface, while its place — which is the
    // adversarial axis — stays exactly as it was.
    const names = PERSONAS.map((p) => p.name)
    for (const unfamiliar of ['Aisha', 'Dilshod', 'Farrukh', 'Priya', 'Wei']) {
      expect(names).not.toContain(unfamiliar)
    }
    expect(PERSONAS.find((p) => p.key === 'dilshod')?.place).toBe('Tashkent')
    expect(PERSONAS.find((p) => p.key === 'farrukh')?.place).toBe('Dushanbe, Tajikistan')
  })
})
