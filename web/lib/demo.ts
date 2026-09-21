/**
 * The reader demo's data contract.
 *
 * The demo replays an edition the evaluation harness actually produced for one
 * reader fixture against one dated, content-hashed corpus. It is a
 * demonstration of the product surface, not evidence of readership, and it
 * deliberately carries no reader-visible scores or labels: Daily's design rule
 * is that personalization is felt, not displayed.
 *
 * Only headline, publication and outbound link are exported. No article body
 * or summary is republished here.
 */

import { z } from 'zod'

export const DEMO_VERSION = 1 as const

export const DemoStorySchema = z.object({
  id: z.string(),
  /** 1-indexed position in the edition as assembled. */
  position: z.number().int(),
  headline: z.string(),
  publication: z.string().nullable(),
  /** Publisher link, or null when the corpus did not record one. */
  url: z.string().nullable(),
  /** True for an article authored for the harness rather than ingested. */
  synthetic: z.boolean(),
})
export type DemoStory = z.infer<typeof DemoStorySchema>

export const DemoEditionSchema = z.object({
  persona: z.string(),
  /** Masthead line, e.g. "SEP 2 · RAY EDITION". */
  masthead: z.string(),
  stories: z.array(DemoStorySchema),
})
export type DemoEdition = z.infer<typeof DemoEditionSchema>

export const DemoBundleSchema = z.object({
  demo_version: z.literal(DEMO_VERSION),
  /** The run these editions were assembled by. */
  run_id: z.string(),
  runner: z.string(),
  snapshot: z.string(),
  snapshot_sha256: z.string(),
  /** The instant the corpus was frozen; the demo shows this, never "today". */
  frozen_at: z.string(),
  n_articles_in_corpus: z.number().int().nullable(),
  built_at: z.string(),
  artifact_revision: z.string(),
  editions: z.array(DemoEditionSchema),
})
export type DemoBundle = z.infer<typeof DemoBundleSchema>

export type ParseResult<T> =
  | { readonly ok: true; readonly value: T }
  | { readonly ok: false; readonly issues: readonly string[] }

export function parseDemoBundle(input: unknown): ParseResult<DemoBundle> {
  const result = DemoBundleSchema.safeParse(input)
  if (result.success) return { ok: true, value: result.data }
  return {
    ok: false,
    issues: result.error.issues.map((i) => `${i.path.join('.') || '<root>'}: ${i.message}`),
  }
}

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']

/** DESIGN.md's edition stamp: `SEP 2 · RAY EDITION`. */
export function mastheadFor(persona: string, frozenAt: string): string {
  const date = new Date(frozenAt)
  if (Number.isNaN(date.getTime())) return `${persona.toUpperCase()} EDITION`
  const month = MONTHS[date.getUTCMonth()] ?? ''
  return `${month} ${date.getUTCDate()} · ${persona.toUpperCase()} EDITION`
}
