/**
 * Publish validated artifacts to Vercel Blob.
 *
 *   BLOB_READ_WRITE_TOKEN=... npx tsx scripts/publish-artifacts.ts
 *
 * Rules this enforces:
 *
 *  - Nothing is uploaded unless every artifact and the manifest validate first.
 *  - The manifest is uploaded LAST, because it asserts completeness. A reader
 *    that sees the manifest can rely on everything it lists being present.
 *  - Artifacts are published under a revision-scoped prefix, so a preview
 *    deployment cannot silently consume an unrelated "latest" run. The mutable
 *    pointer is only written when PUBLISH_AS_LATEST is set, which the trusted
 *    workflow does only for the default branch.
 *  - Absent a token the script exits 0 without publishing, so pull requests
 *    from forks run the same pipeline without needing credentials.
 */

import { createHash } from 'node:crypto'
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { parseArtifact, parseManifest } from '../lib/artifact'

function findWebRoot(): string {
  const starts: string[] = []
  const metaUrl: string | undefined = typeof import.meta.url === 'string' ? import.meta.url : undefined
  if (metaUrl !== undefined) starts.push(dirname(fileURLToPath(metaUrl)))
  starts.push(process.cwd())
  for (const start of starts) {
    let current = resolve(start)
    for (let depth = 0; depth < 8; depth += 1) {
      if (existsSync(join(current, 'public', 'artifacts'))) return current
      const parent = dirname(current)
      if (parent === current) break
      current = parent
    }
  }
  throw new Error('Could not locate web/public/artifacts.')
}

const ARTIFACTS = join(findWebRoot(), 'public', 'artifacts')

/** A git sha, and nothing that could be a path or a pointer name. */
const REVISION = /^[0-9a-f]{7,40}$/
/** A plain file name: no directories, no traversal, no leading dot. */
const FILE_NAME = /^[A-Za-z0-9][A-Za-z0-9._-]*\.json$/

async function main(): Promise<void> {
  const token = process.env.BLOB_READ_WRITE_TOKEN
  if (token === undefined || token.trim() === '') {
    console.log('BLOB_READ_WRITE_TOKEN is not set; skipping publication. The committed export is still used by the app.')
    return
  }

  const manifestPath = join(ARTIFACTS, 'manifest.json')
  if (!existsSync(manifestPath)) throw new Error('No manifest to publish.')

  const manifestText = readFileSync(manifestPath, 'utf8')
  const manifest = parseManifest(JSON.parse(manifestText))
  if (!manifest.ok) throw new Error(`Refusing to publish an invalid manifest: ${manifest.issues.join('; ')}`)

  // Validate everything BEFORE uploading anything.
  //
  // Schema conformance is not integrity. The manifest records a sha256 and a
  // byte count for each artifact; until now neither was ever recompared, so a
  // file could be swapped after export and still publish. Both are checked
  // here, against the exact bytes about to be uploaded.
  const payloads: { name: string; body: string }[] = []
  for (const entry of manifest.value.entries) {
    if (!FILE_NAME.test(entry.file)) {
      throw new Error(`Refusing to publish: ${entry.file} is not a plain artifact file name.`)
    }
    const path = join(ARTIFACTS, entry.file)
    if (!existsSync(path)) throw new Error(`Manifest lists ${entry.file} but it is missing on disk.`)
    const body = readFileSync(path, 'utf8')
    const parsed = parseArtifact(JSON.parse(body))
    if (!parsed.ok) throw new Error(`Refusing to publish invalid artifact ${entry.file}: ${parsed.issues.join('; ')}`)

    const bytes = Buffer.byteLength(body)
    if (bytes !== entry.bytes) {
      throw new Error(`Integrity check failed for ${entry.file}: manifest says ${entry.bytes} bytes, file is ${bytes}.`)
    }
    const digest = createHash('sha256').update(body).digest('hex')
    if (digest !== entry.sha256) {
      throw new Error(`Integrity check failed for ${entry.file}: sha256 ${digest} does not match the manifest.`)
    }
    payloads.push({ name: entry.file, body })
  }

  const orphans = readdirSync(ARTIFACTS)
    .filter((f) => f !== 'manifest.json')
    .filter((f) => !manifest.value.entries.some((e) => e.file === f))
  if (orphans.length > 0) {
    throw new Error(`Refusing to publish: files not listed in the manifest: ${orphans.join(', ')}`)
  }

  // The revision becomes part of a blob key, so its shape is checked rather
  // than assumed. `artifact_revision` is `unknownable(z.string())` in the
  // schema, which means a manifest declaring "latest" would have written
  // straight to the mutable pointer that the deployed explorer reads — with no
  // PUBLISH_AS_LATEST involved at all. A value containing `..` would have been
  // equally unconstrained.
  const revision = manifest.value.artifact_revision
  if (!REVISION.test(revision)) {
    throw new Error(`Refusing to publish under revision "${revision}": expected a git sha.`)
  }
  const prefixes = [`evidence/${revision}`]
  if (process.env.PUBLISH_AS_LATEST === 'true') prefixes.push('evidence/latest')

  const { put } = (await import('@vercel/blob')) as typeof import('@vercel/blob')

  for (const prefix of prefixes) {
    for (const payload of payloads) {
      await put(`${prefix}/${payload.name}`, payload.body, {
        access: 'public',
        contentType: 'application/json',
        addRandomSuffix: false,
        allowOverwrite: true,
        cacheControlMaxAge: 31536000,
        token,
      })
    }
    // Manifest last: it is the completeness assertion.
    const result = await put(`${prefix}/manifest.json`, manifestText, {
      access: 'public',
      contentType: 'application/json',
      addRandomSuffix: false,
      allowOverwrite: true,
      // Short max-age on the pointer so a new publication is picked up, while
      // the artifacts it names stay immutable for a year.
      cacheControlMaxAge: 60,
      token,
    })
    console.log(`published ${payloads.length + 1} objects under ${prefix}/ -> ${result.url}`)
  }
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : String(error))
  process.exitCode = 1
})
