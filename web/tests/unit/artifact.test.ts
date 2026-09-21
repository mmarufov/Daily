import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { parseArtifact, parseManifest, UNKNOWN } from '@/lib/artifact'
import { assessCompatibility } from '@/lib/compare'
import { parseScorecard } from '@/lib/scorecard'

const ARTIFACTS = join(import.meta.dirname, '..', '..', 'public', 'artifacts')

function loadAll() {
  const manifestRaw: unknown = JSON.parse(readFileSync(join(ARTIFACTS, 'manifest.json'), 'utf8'))
  const manifest = parseManifest(manifestRaw)
  if (!manifest.ok) throw new Error(`manifest invalid: ${manifest.issues.join('; ')}`)
  const artifacts = manifest.value.entries.map((entry) => {
    const raw: unknown = JSON.parse(readFileSync(join(ARTIFACTS, entry.file), 'utf8'))
    const parsed = parseArtifact(raw)
    if (!parsed.ok) throw new Error(`${entry.file} invalid: ${parsed.issues.join('; ')}`)
    return parsed.value
  })
  return { manifest: manifest.value, artifacts }
}

describe('exported artifacts', () => {
  const { manifest, artifacts } = loadAll()

  it('has a complete manifest listing every artifact file', () => {
    expect(manifest.complete).toBe(true)
    const files = readdirSync(ARTIFACTS).filter((f) => f !== 'manifest.json')
    expect(files.sort()).toEqual(manifest.entries.map((e) => e.file).sort())
  })

  it('validates every artifact against the schema', () => {
    expect(artifacts.length).toBe(manifest.entries.length)
    expect(artifacts.length).toBeGreaterThan(0)
  })

  it('records every artifact as an import, never as a run this pipeline executed', () => {
    for (const artifact of artifacts) {
      expect(artifact.origin).toBe('imported-historical')
    }
  })

  it('keeps the executing, storing and artifact revisions distinct fields', () => {
    for (const artifact of artifacts) {
      const p = artifact.provenance
      expect(p.eval_revision).not.toBe('')
      // The stored scorecards were executed off-mainline, so the revision that
      // ran them is not reachable from the current branch. Stamping today's
      // commit onto these numbers is exactly what this field prevents.
      expect(p.eval_revision).not.toBe(p.artifact_revision)
    }
  })

  it('reports protocol as unknown for scorecards that predate the field', () => {
    for (const artifact of artifacts) {
      const p = artifact.provenance
      if (p.protocol_source === 'absent-in-source') {
        expect(p.protocol).toBe(UNKNOWN)
        expect(p.notes.some((n) => n.message.includes('no protocol identifier'))).toBe(true)
      }
    }
  })

  it('never claims an execution mode it cannot establish', () => {
    for (const artifact of artifacts) {
      expect(artifact.provenance.execution_mode).toBe(UNKNOWN)
      expect(artifact.provenance.execution_mode_basis).toContain('cache-miss')
    }
  })

  it('flags the baseline whose stored thresholds disagree with its run', () => {
    const suspect = artifacts.filter((a) => a.baseline.disagrees_with_run.length > 0)
    // Detected from the data, not hardcoded: exactly one baseline in the
    // committed set was re-recorded after the timestamps embedded in it.
    expect(suspect.length).toBe(1)
    const [only] = suspect
    expect(only?.provenance.runner).toBe('prod-llm')
    expect(only?.baseline.disagrees_with_run).toEqual(['2026-09-02'])
    expect(only?.provenance.timestamps_trustworthy).toBe(false)
  })

  it('trusts the timestamps of baselines that agree with their runs', () => {
    const agreeing = artifacts.filter(
      (a) => a.baseline.is_baseline && a.baseline.disagrees_with_run.length === 0,
    )
    expect(agreeing.length).toBeGreaterThan(0)
    for (const artifact of agreeing) {
      expect(artifact.provenance.timestamps_trustworthy).toBe(true)
    }
  })

  it('preserves a missing metric as null rather than zero', () => {
    const prodLlm = artifacts.find(
      (a) => a.provenance.runner === 'prod-llm' && a.provenance.snapshot.name === '2026-09-02',
    )
    const ray = prodLlm?.personas.find((p) => p.key === 'ray')
    // judge_precision is genuinely absent for this fixture in this run.
    expect(ray?.metrics.judge_precision).toBeNull()
    expect(ray?.metrics.recall_at_k).toBeTypeOf('number')
  })

  it('carries snapshot content hashes and article counts', () => {
    for (const artifact of artifacts) {
      const snapshot = artifact.provenance.snapshot
      expect(snapshot.sha256).not.toBe(UNKNOWN)
      expect(snapshot.n_articles).toBeGreaterThan(1000)
    }
  })

  it('reports label provenance as provisional, never as human ground truth', () => {
    for (const artifact of artifacts) {
      const labels = artifact.provenance.labels
      expect(labels).not.toBeNull()
      expect(labels?.status).toBe('provisional-model-and-agent')
      // Pairs and distinct articles are different quantities and both recorded.
      expect(labels?.rows).toBeGreaterThan(labels?.unique_articles ?? 0)
    }
  })

  it('warns that the prototype runner name does not validate the corrected pipeline', () => {
    const proto = artifacts.filter((a) => a.provenance.runner === 'proto-hybrid-judge-events')
    expect(proto.length).toBeGreaterThan(0)
    for (const artifact of proto) {
      expect(
        artifact.provenance.notes.some((n) => n.message.includes('proto-s0-legacy-v1')),
      ).toBe(true)
    }
  })
})

describe('artifact validation rejects malformed input', () => {
  it('rejects a missing required field', () => {
    const result = parseArtifact({ artifact_version: 1 })
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.issues.length).toBeGreaterThan(0)
  })

  it('rejects an unsupported artifact version', () => {
    const { artifacts } = loadAll()
    const [first] = artifacts
    const result = parseArtifact({ ...first, artifact_version: 99 })
    expect(result.ok).toBe(false)
  })

  it('rejects a manifest that is not marked complete', () => {
    const { manifest } = loadAll()
    expect(parseManifest({ ...manifest, complete: false }).ok).toBe(false)
  })

  it('reports the path of an invalid field', () => {
    const result = parseArtifact({
      artifact_version: 1,
      run_id: 'x',
      origin: 'imported-historical',
      provenance: 'not-an-object',
      summary: {},
      summary_loss_by_stage: {},
      personas: [],
      baseline: { is_baseline: false, snapshot_baseline_keys: [], disagrees_with_run: [] },
    })
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.issues.join(' ')).toContain('provenance')
  })

  it('accepts a scorecard with unknown extra keys, so a harness change cannot break the export', () => {
    const result = parseScorecard({
      git_sha: 'abc1234',
      runner: 'prod-llm',
      snapshot: '2026-09-02',
      k: 12,
      created_at: '2026-09-02T07:14:29+00:00',
      summary: {},
      per_persona: {},
      cache_keys: [],
      meta: { protocol: 'production-feed-v1', some_future_key: 1 },
      another_future_key: true,
    })
    expect(result.ok).toBe(true)
  })
})

describe('comparison compatibility', () => {
  const { artifacts } = loadAll()
  const find = (runner: string, snapshot: string) =>
    artifacts.find(
      (a) =>
        a.provenance.runner === runner &&
        a.provenance.snapshot.name === snapshot &&
        !a.baseline.is_baseline,
    )

  it('labels a same-corpus, different-pipeline pair as an algorithm comparison', () => {
    const prod = find('prod-llm', '2026-09-02')
    const proto = find('proto-hybrid-judge-events', '2026-09-02')
    expect(prod).toBeDefined()
    expect(proto).toBeDefined()
    const result = assessCompatibility(prod!, proto!)
    expect(result.kind).toBe('algorithm')
    expect(result.showDirectionalDeltas).toBe(true)
    expect(result.headline).toContain('Algorithm comparison')
  })

  it('blocks a cross-corpus comparison instead of showing improvement arrows', () => {
    const a = find('prod-llm', '2026-09-02')
    const b = find('prod-llm', '2026-08-31')
    const result = assessCompatibility(a!, b!)
    expect(result.kind).toBe('incompatible')
    expect(result.showDirectionalDeltas).toBe(false)
    expect(result.issues.some((i) => i.field === 'snapshot' && i.severity === 'blocking')).toBe(true)
  })

  it('caveats every stored pair because neither side records a protocol', () => {
    const prod = find('prod-llm', '2026-09-02')
    const proto = find('proto-hybrid-judge-events', '2026-09-02')
    const result = assessCompatibility(prod!, proto!)
    const protocolIssue = result.issues.find((i) => i.field === 'protocol')
    expect(protocolIssue?.severity).toBe('caveat')
    expect(protocolIssue?.message).toContain('cannot be verified')
  })

  it('blocks a comparison at a different k', () => {
    const a = find('prod-llm', '2026-09-02')!
    const b = {
      ...a,
      provenance: { ...a.provenance, k: 24, runner: 'prod-llm' },
    }
    const result = assessCompatibility(a, b)
    expect(result.kind).toBe('incompatible')
    expect(result.issues.some((i) => i.field === 'k')).toBe(true)
  })

  it('blocks a comparison where the corpus hash differs under the same name', () => {
    const a = find('prod-llm', '2026-09-02')!
    const b = {
      ...a,
      provenance: {
        ...a.provenance,
        snapshot: { ...a.provenance.snapshot, sha256: 'deadbeef' },
      },
    }
    const result = assessCompatibility(a, b)
    expect(result.kind).toBe('incompatible')
    expect(result.issues.some((i) => i.field === 'snapshot.sha256')).toBe(true)
  })

  it('calls a same-runner, same-corpus pair a regression check', () => {
    const a = find('prod-llm', '2026-09-02')!
    const b = {
      ...a,
      provenance: { ...a.provenance, eval_revision: 'other12' },
    }
    const result = assessCompatibility(a, b)
    expect(result.kind).toBe('code-regression')
  })
})
