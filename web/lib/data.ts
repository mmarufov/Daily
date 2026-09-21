/**
 * Server-side artifact loading.
 *
 * Artifacts are read from one of two places, in this order:
 *
 *   1. A Vercel Blob base URL, when ARTIFACTS_BLOB_BASE_URL is configured.
 *      This is how a deployment consumes runs published by CI.
 *   2. The bundled export under web/public/artifacts/, which is committed.
 *      This is what makes local development and the demo work with no
 *      credentials and no network.
 *
 * Every document is validated before use. A malformed artifact is surfaced as
 * a load error rather than silently skipped, because a quietly missing run is
 * how a dashboard starts showing a comparison against the wrong thing.
 */

import { readFile, readdir } from 'node:fs/promises'
import { join } from 'node:path'

import {
  parseArtifact,
  parseManifest,
  type Artifact,
  type Manifest,
  type ManifestEntry,
} from './artifact'

export type ArtifactSource = 'blob' | 'bundled'

export interface LoadError {
  readonly where: string
  readonly issues: readonly string[]
}

export interface ArtifactIndex {
  readonly manifest: Manifest | null
  readonly entries: readonly ManifestEntry[]
  readonly source: ArtifactSource
  readonly errors: readonly LoadError[]
  /** Set when the manifest is present but not marked complete. */
  readonly incomplete: boolean
}

const BUNDLED_DIR = join(process.cwd(), 'public', 'artifacts')

function blobBase(): string | null {
  const raw = process.env.ARTIFACTS_BLOB_BASE_URL
  if (raw === undefined || raw.trim() === '') return null
  return raw.replace(/\/+$/, '')
}

async function fetchJson(url: string): Promise<unknown> {
  // Public artifacts are immutable and content-addressed by run id, so they are
  // safe to cache for a long time. A stale manifest is the failure we care
  // about, so it is revalidated more aggressively by its own caller.
  const response = await fetch(url, { next: { revalidate: 3600, tags: ['artifacts'] } })
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText} for ${url}`)
  }
  return response.json()
}

async function readBundledJson(name: string): Promise<unknown> {
  const text = await readFile(join(BUNDLED_DIR, name), 'utf8')
  return JSON.parse(text)
}

/** Load the manifest and the list of available runs. */
export async function loadIndex(): Promise<ArtifactIndex> {
  const errors: LoadError[] = []
  const base = blobBase()

  if (base !== null) {
    try {
      const raw = await fetchJson(`${base}/manifest.json`)
      const parsed = parseManifest(raw)
      if (parsed.ok) {
        return {
          manifest: parsed.value,
          entries: parsed.value.entries,
          source: 'blob',
          errors,
          incomplete: false,
        }
      }
      errors.push({ where: `${base}/manifest.json`, issues: parsed.issues })
    } catch (error) {
      errors.push({
        where: `${base}/manifest.json`,
        issues: [error instanceof Error ? error.message : String(error)],
      })
    }
    // Fall through to the bundled export rather than rendering nothing, and
    // keep the error so the UI can say the published set was unreachable.
  }

  try {
    const raw = await readBundledJson('manifest.json')
    const parsed = parseManifest(raw)
    if (parsed.ok) {
      return {
        manifest: parsed.value,
        entries: parsed.value.entries,
        source: 'bundled',
        errors,
        incomplete: false,
      }
    }
    errors.push({ where: 'public/artifacts/manifest.json', issues: parsed.issues })
  } catch (error) {
    errors.push({
      where: 'public/artifacts/manifest.json',
      issues: [error instanceof Error ? error.message : String(error)],
    })
  }

  // Last resort: enumerate whatever artifacts exist without a manifest, and
  // mark the index incomplete so nothing claims a verified published set.
  try {
    const files = (await readdir(BUNDLED_DIR)).filter(
      (f) => f.endsWith('.json') && f !== 'manifest.json',
    )
    if (files.length > 0) {
      return { manifest: null, entries: [], source: 'bundled', errors, incomplete: true }
    }
  } catch {
    // Nothing to enumerate.
  }

  return { manifest: null, entries: [], source: 'bundled', errors, incomplete: true }
}

export type ArtifactLoad =
  | { readonly ok: true; readonly artifact: Artifact; readonly source: ArtifactSource }
  | { readonly ok: false; readonly error: LoadError }

export async function loadArtifact(entry: ManifestEntry): Promise<ArtifactLoad> {
  const base = blobBase()
  const attempts: { where: string; read: () => Promise<unknown> }[] = []
  if (base !== null) {
    attempts.push({ where: `${base}/${entry.file}`, read: () => fetchJson(`${base}/${entry.file}`) })
  }
  attempts.push({
    where: `public/artifacts/${entry.file}`,
    read: () => readBundledJson(entry.file),
  })

  const issues: string[] = []
  for (const attempt of attempts) {
    try {
      const raw = await attempt.read()
      const parsed = parseArtifact(raw)
      if (parsed.ok) {
        return {
          ok: true,
          artifact: parsed.value,
          source: attempt.where.startsWith('http') ? 'blob' : 'bundled',
        }
      }
      issues.push(`${attempt.where}: ${parsed.issues.join('; ')}`)
    } catch (error) {
      issues.push(`${attempt.where}: ${error instanceof Error ? error.message : String(error)}`)
    }
  }

  return { ok: false, error: { where: entry.file, issues } }
}

export function findEntry(
  entries: readonly ManifestEntry[],
  runId: string | undefined,
): ManifestEntry | undefined {
  if (runId === undefined) return undefined
  return entries.find((e) => e.run_id === runId)
}

/**
 * The run the explorer opens on when no URL state is supplied.
 *
 * Preference order is deliberate: the production LLM pipeline on the most
 * recent non-quiet corpus, excluding baselines. That is the run that describes
 * what a reader would actually have received, which is the useful thing to see
 * first. Baselines are gate thresholds, not results, so they never preselect.
 */
export function defaultEntry(entries: readonly ManifestEntry[]): ManifestEntry | undefined {
  const candidates = entries.filter((e) => !e.is_baseline)
  if (candidates.length === 0) return entries[0]
  const preferred = candidates
    .filter((e) => e.runner === 'prod-llm' && !e.snapshot.endsWith('-quiet'))
    .sort((a, b) => b.snapshot.localeCompare(a.snapshot))
  return preferred[0] ?? candidates[0]
}

/**
 * The run to compare the default against: the same corpus and k, a different
 * pipeline. That is an algorithm comparison and the UI labels it as one.
 */
export function defaultComparison(
  entries: readonly ManifestEntry[],
  primary: ManifestEntry | undefined,
): ManifestEntry | undefined {
  if (primary === undefined) return undefined
  return entries.find(
    (e) =>
      !e.is_baseline &&
      e.run_id !== primary.run_id &&
      e.snapshot === primary.snapshot &&
      e.k === primary.k &&
      e.runner !== primary.runner,
  )
}
