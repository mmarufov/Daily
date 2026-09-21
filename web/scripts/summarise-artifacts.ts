/**
 * Render a readable comparison summary from the exported artifacts.
 *
 *   npx tsx scripts/summarise-artifacts.ts >> "$GITHUB_STEP_SUMMARY"
 *
 * Comparisons are only emitted for pairs the compatibility rules accept, and
 * every emitted pair states what was held fixed. An incompatible pair is listed
 * with the reason rather than shown with improvement arrows.
 */

import { existsSync, readFileSync, readdirSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { parseArtifact, parseManifest, UNKNOWN, type Artifact } from '../lib/artifact'
import { assessCompatibility } from '../lib/compare'
import { computeDelta, formatValue } from '../lib/format'
import { HEADLINE_METRICS, summaryValue } from '../lib/aggregate'
import { resolveMetric } from '../lib/metrics'

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
const out: string[] = []
const say = (line = '') => out.push(line)

function main(): void {
  const manifestPath = join(ARTIFACTS, 'manifest.json')
  if (!existsSync(manifestPath)) {
    say('## Evaluation artifacts')
    say()
    say('No manifest was produced, so no artifacts are published.')
    console.log(out.join('\n'))
    process.exitCode = 1
    return
  }

  const manifest = parseManifest(JSON.parse(readFileSync(manifestPath, 'utf8')))
  if (!manifest.ok) {
    say('## Evaluation artifacts')
    say()
    say('The manifest failed validation and is **not** safe to publish:')
    for (const issue of manifest.issues) say(`- \`${issue}\``)
    console.log(out.join('\n'))
    process.exitCode = 1
    return
  }

  const files = readdirSync(ARTIFACTS).filter((f) => f !== 'manifest.json')
  const listed = new Set(manifest.value.entries.map((e) => e.file))
  const orphans = files.filter((f) => !listed.has(f))

  const artifacts = new Map<string, Artifact>()
  const invalid: string[] = []
  for (const entry of manifest.value.entries) {
    const path = join(ARTIFACTS, entry.file)
    if (!existsSync(path)) {
      invalid.push(`${entry.file}: listed in the manifest but missing on disk`)
      continue
    }
    const parsed = parseArtifact(JSON.parse(readFileSync(path, 'utf8')))
    if (!parsed.ok) {
      invalid.push(`${entry.file}: ${parsed.issues.join('; ')}`)
      continue
    }
    artifacts.set(entry.run_id, parsed.value)
  }

  say('## Evaluation artifacts')
  say()
  say(
    `Exported **${manifest.value.entries.length}** artifacts at \`${manifest.value.artifact_revision}\`. ` +
      `Every entry is an import of a stored scorecard, not a run executed by this job.`,
  )
  say()

  if (invalid.length > 0) {
    say('### Validation failures')
    say()
    for (const issue of invalid) say(`- \`${issue}\``)
    say()
    process.exitCode = 1
  }
  if (orphans.length > 0) {
    say(`> Files present but not listed in the manifest: ${orphans.map((o) => `\`${o}\``).join(', ')}`)
    say()
  }

  say('### Runs')
  say()
  say('| Run | Protocol | Evaluated at | Reachable | Timestamps | Baseline |')
  say('|---|---|---|---|---|---|')
  for (const entry of manifest.value.entries) {
    const artifact = artifacts.get(entry.run_id)
    const p = artifact?.provenance
    say(
      `| \`${entry.run_id}\` | ${p?.protocol ?? UNKNOWN} | \`${entry.eval_revision}\` | ` +
        `${p?.eval_revision_reachable === false ? 'no' : p?.eval_revision_reachable === true ? 'yes' : 'unknown'} | ` +
        `${p?.timestamps_trustworthy === false ? '**contradicted**' : 'consistent'} | ` +
        `${entry.is_baseline ? 'yes' : 'no'} |`,
    )
  }
  say()

  // Same corpus, same k, different pipeline: the only comparison this data
  // actually supports. A same-runner pair across revisions would be a
  // regression check, but every stored scorecard shares one revision.
  const runs = [...artifacts.values()].filter((a) => !a.baseline.is_baseline)
  const pairs: [Artifact, Artifact][] = []
  for (let i = 0; i < runs.length; i += 1) {
    for (let j = i + 1; j < runs.length; j += 1) {
      const a = runs[i]
      const b = runs[j]
      if (a === undefined || b === undefined) continue
      if (a.provenance.snapshot.name !== b.provenance.snapshot.name) continue
      if (a.provenance.runner === b.provenance.runner) continue
      pairs.push([a, b])
    }
  }

  if (pairs.length === 0) {
    say('### Comparisons')
    say()
    say('No two runs shared a corpus and differed in pipeline, so no comparison is meaningful.')
  }

  for (const [a, b] of pairs) {
    const compatibility = assessCompatibility(a, b)
    say(`### ${a.provenance.runner} vs ${b.provenance.runner} — ${a.provenance.snapshot.name}`)
    say()
    say(`**${compatibility.headline}**`)
    say()
    for (const issue of compatibility.issues) {
      say(`- ${issue.severity === 'blocking' ? '**blocking**' : 'caveat'} (\`${issue.field}\`): ${issue.message}`)
    }
    say()

    if (!compatibility.showDirectionalDeltas) {
      say('Per-metric differences are withheld: the runs are not comparable.')
      say()
      continue
    }

    say('| Metric | ' + a.provenance.runner + ' | ' + b.provenance.runner + ' | Difference | |')
    say('|---|---:|---:|---:|---|')
    for (const metric of HEADLINE_METRICS) {
      const def = resolveMetric(metric)
      const va = summaryValue(a, metric, 'mean')
      const vb = summaryValue(b, metric, 'mean')
      if (va === null && vb === null) continue
      const delta = computeDelta(va, vb, metric)
      const mark =
        delta.verdict === 'better'
          ? 'better'
          : delta.verdict === 'worse'
            ? 'worse'
            : delta.verdict === 'not-computable'
              ? 'not computable'
              : ''
      say(
        `| ${def.label} | ${formatValue(va, def.kind)} | ${formatValue(vb, def.kind)} | ` +
          `${delta.display} | ${mark}${delta.material ? ' (material)' : ''} |`,
      )
    }
    say()
    say(
      '_Differences in percentage points. "Material" means the harness’s fixed ±0.02 cutoff, ' +
        'which is a chosen threshold and not a significance test._',
    )
    say()
  }

  console.log(out.join('\n'))
}

main()
