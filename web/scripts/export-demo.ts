/**
 * Build the reader demo's frozen editions.
 *
 *   npm run export:demo
 *
 * Reads an exported evaluation artifact for the delivered order, and the
 * harness's label and needle files for publisher links. Exports headline,
 * publication and link only — no article body or summary is republished.
 *
 * A delivered story with no recorded link is exported with `url: null` and
 * shown as such, rather than being dropped or given a guessed URL.
 */

import { existsSync, readFileSync, readdirSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

import { parseArtifact } from '../lib/artifact'
import { DEMO_VERSION, mastheadFor, parseDemoBundle, type DemoBundle, type DemoEdition, type DemoStory } from '../lib/demo'

function findRepoRoot(): string {
  const starts: string[] = []
  const metaUrl: string | undefined = typeof import.meta.url === 'string' ? import.meta.url : undefined
  if (metaUrl !== undefined) starts.push(dirname(fileURLToPath(metaUrl)))
  starts.push(process.cwd())
  for (const start of starts) {
    let current = resolve(start)
    for (let depth = 0; depth < 8; depth += 1) {
      if (existsSync(join(current, 'backend', 'evals', 'results'))) return current
      const parent = dirname(current)
      if (parent === current) break
      current = parent
    }
  }
  throw new Error('Could not locate the repository root.')
}

const REPO = findRepoRoot()
const LABELS = join(REPO, 'backend', 'evals', 'labels')
const ARTIFACTS = join(REPO, 'web', 'public', 'artifacts')
const OUT = join(REPO, 'web', 'public', 'demo')

/**
 * The edition the demo replays. The production LLM pipeline on the most recent
 * non-quiet corpus: what a reader would actually have received, rather than the
 * prototype's better numbers, which never served anyone.
 */
const RUN_ID = process.env.DEMO_RUN_ID ?? 'prod-llm__2026-09-02__47edb50'

function git(...args: readonly string[]): string {
  try {
    return execFileSync('git', args, { cwd: REPO, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  } catch {
    return 'unknown'
  }
}

interface UrlIndex {
  readonly byId: ReadonlyMap<string, string>
  readonly synthetic: ReadonlySet<string>
}

function loadUrls(snapshot: string): UrlIndex {
  const dir = join(LABELS, snapshot)
  const byId = new Map<string, string>()
  const synthetic = new Set<string>()
  if (!existsSync(dir)) return { byId, synthetic }

  for (const file of readdirSync(dir).filter((f) => f.endsWith('.jsonl'))) {
    for (const line of readFileSync(join(dir, file), 'utf8').split('\n')) {
      const trimmed = line.trim()
      if (trimmed === '') continue
      const row = JSON.parse(trimmed) as { article_id?: string; url?: string | null }
      // A label row may carry `url: null`. Storing that would put a null into a
      // Map typed as string and then report it as a link, so require a string.
      if (row.article_id !== undefined && typeof row.url === 'string' && row.url !== '') {
        byId.set(row.article_id, row.url)
      }
    }
  }

  const needlesPath = join(dir, 'needles.json')
  if (existsSync(needlesPath)) {
    const needles = JSON.parse(readFileSync(needlesPath, 'utf8')) as Record<string, unknown>
    for (const [key, value] of Object.entries(needles)) {
      if (key.startsWith('_') || value === null || typeof value !== 'object') continue
      for (const group of ['plant', 'lookalikes'] as const) {
        const items = (value as Record<string, unknown>)[group]
        if (!Array.isArray(items)) continue
        // Needle articles are authored for the harness and carry no publisher
        // URL at all, which is why they are exported as synthetic with a null
        // link rather than being dropped from the edition.
        for (const item of items as { id?: string; url?: string | null }[]) {
          if (item.id === undefined) continue
          synthetic.add(item.id)
          if (typeof item.url === 'string' && item.url !== '') byId.set(item.id, item.url)
        }
      }
    }
  }

  return { byId, synthetic }
}

function main(): void {
  const artifactPath = join(ARTIFACTS, `${RUN_ID}.json`)
  if (!existsSync(artifactPath)) {
    throw new Error(`No exported artifact at ${artifactPath}. Run npm run export:artifacts first.`)
  }
  const parsed = parseArtifact(JSON.parse(readFileSync(artifactPath, 'utf8')))
  if (!parsed.ok) throw new Error(`Artifact invalid: ${parsed.issues.join('; ')}`)
  const artifact = parsed.value

  const snapshot = artifact.provenance.snapshot
  const frozenAt = snapshot.frozen_now === 'unknown' ? snapshot.built_at : snapshot.frozen_now
  if (frozenAt === 'unknown') {
    throw new Error('The corpus records no frozen timestamp, so the demo cannot date its editions.')
  }

  const urls = loadUrls(snapshot.name)
  let missingLinks = 0

  const editions: DemoEdition[] = artifact.personas.map((persona) => {
    const stories: DemoStory[] = persona.stories
      .filter((story) => story.rank !== null)
      .sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0))
      .map((story) => {
        const url = urls.byId.get(story.id) ?? null
        if (url === null) missingLinks += 1
        return {
          id: story.id,
          position: story.rank ?? 0,
          headline: story.title ?? story.id,
          publication: story.source,
          url,
          synthetic: urls.synthetic.has(story.id),
        }
      })
    return { persona: persona.key, masthead: mastheadFor(persona.key, frozenAt), stories }
  })

  const bundle: DemoBundle = {
    demo_version: DEMO_VERSION,
    run_id: artifact.run_id,
    runner: artifact.provenance.runner,
    snapshot: snapshot.name,
    snapshot_sha256: snapshot.sha256,
    frozen_at: frozenAt,
    n_articles_in_corpus: snapshot.n_articles,
    // Commit time, not wall-clock time: see the note in export-artifacts.ts.
    built_at: git('show', '-s', '--format=%cI', 'HEAD'),
    artifact_revision: git('rev-parse', '--short', 'HEAD'),
    editions,
  }

  const validated = parseDemoBundle(bundle)
  if (!validated.ok) throw new Error(`Demo bundle invalid: ${validated.issues.join('; ')}`)

  mkdirSync(OUT, { recursive: true })
  writeFileSync(join(OUT, 'editions.json'), `${JSON.stringify(validated.value, null, 1)}\n`, 'utf8')

  const total = editions.reduce((sum, e) => sum + e.stories.length, 0)
  console.log(
    `wrote web/public/demo/editions.json — ${editions.length} editions, ${total} stories, ` +
      `${missingLinks} without a recorded link`,
  )
}

main()
