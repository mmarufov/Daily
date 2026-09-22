/**
 * Display names for the ten reader fixtures.
 *
 * The fixture **key** is an internal identifier and deliberately stays as it
 * is. `evals/fake_db.py:29` derives the synthetic user id from it
 * (`uuid5(EVAL_NS, "persona:" + key)`), and that id is what
 * `feed_service.get_personalized_feed` receives — so renaming a key changes
 * retrieval and changes the measured run. Verified, not assumed: renaming the
 * five keys moved a replay from 42 model calls to 24.
 *
 * The **name** is presentation and reaches no replayed prompt (0 of 460
 * non-labeling cached prompts contain a persona name; the 1,709 that do are
 * labeling calls, and labels are read from disk during a replay). Changing it
 * leaves every metric identical — only wall-clock timings move.
 *
 * So the URL, the artifacts, the labels and the scorecards keep the key; the
 * page shows the name. `tests/unit/personas.test.ts` reads the fixture files
 * and fails if this table drifts from them.
 */

export interface PersonaDisplay {
  /** Internal identifier. Appears in URLs, artifacts, labels and scorecards. */
  readonly key: string
  /** First name shown in the interface. */
  readonly name: string
  /** Where the reader is. Part of the adversarial axis, so it never changes. */
  readonly place: string
  /** The failure mode this fixture exists to provoke. */
  readonly axis: string
}

export const PERSONAS: readonly PersonaDisplay[] = [
  { key: 'aisha', name: 'Anna', place: 'Singapore', axis: 'life-context / need-to-know reader' },
  { key: 'cold', name: 'Cold start', place: 'no preferences', axis: 'a reader who gave nothing to work with' },
  { key: 'dilshod', name: 'Daniel', place: 'Tashkent', axis: 'non-English-named entities and places' },
  { key: 'farrukh', name: 'Frank', place: 'Dushanbe, Tajikistan', axis: 'multi-region geopolitics and trade' },
  { key: 'lena', name: 'Lena', place: 'Berlin', axis: 'follows one developing story' },
  { key: 'maya', name: 'Maya', place: 'London', axis: 'broad “keep me informed” reader' },
  { key: 'priya', name: 'Paula', place: 'Toronto', axis: 'interests that collide with exclusions' },
  { key: 'ray', name: 'Ray', place: 'Newark, New Jersey', axis: 'hyper-local plus named entities' },
  { key: 'tom', name: 'Tom', place: 'Boston', axis: 'primary topic plus a background sports fan' },
  { key: 'wei', name: 'Will', place: 'Singapore', axis: 'professional/technical plus geographic' },
]

const BY_KEY = new Map(PERSONAS.map((p) => [p.key, p]))

/** The name to print. Falls back to the key rather than inventing one. */
export function personaName(key: string): string {
  return BY_KEY.get(key)?.name ?? key
}

/** `Daniel — Tashkent`, for places with room for it. */
export function personaLabel(key: string): string {
  const p = BY_KEY.get(key)
  return p === undefined ? key : `${p.name} — ${p.place}`
}

export function personaAxis(key: string): string | undefined {
  return BY_KEY.get(key)?.axis
}

export function personaDisplay(key: string): PersonaDisplay | undefined {
  return BY_KEY.get(key)
}
