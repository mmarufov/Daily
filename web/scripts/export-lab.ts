/**
 * Build the committed Lab artifact set from real run evidence.
 *
 *   npm run export:lab            # write web/public/lab/
 *   npm run export:lab -- --check # validate without writing
 *
 * Every field is derived from something on disk: the case suites, the record
 * bundles the harness produced, and the event logs the orchestrator persisted.
 * Nothing is authored here, and anything that cannot be established is written
 * as the literal string `unknown` — the same rule `scripts/export-artifacts.ts`
 * follows for the evaluation artifacts.
 *
 * The verdict is computed *here*, by the trusted evaluator, from the records.
 * It is never read from the candidate's output.
 */

import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'

import { evaluate } from '../lib/lab/evaluator'
import {
  parseCaseSuite,
  parseRecordBundle,
  type Case,
  type RecordBundle,
} from '../lib/lab/records'
import { EXPERIMENT, specHash } from '../lib/lab/spec'
import { KNOWN_IMPLEMENTATIONS, SANDBOX_LIMITS } from '../lib/lab/runner'
import {
  LAB_ARTIFACT_VERSION,
  parseLabManifest,
  parseLabRun,
  UNKNOWN,
  VERDICT_SCOPE,
  type LabManifest,
  type LabRun,
} from '../lib/lab/artifact'

const CHECK_ONLY = process.argv.includes('--check')

function repoRoot(): string {
  let dir = process.cwd()
  for (let i = 0; i < 6; i += 1) {
    if (existsSync(join(dir, 'backend')) && existsSync(join(dir, 'web'))) return dir
    dir = dirname(dir)
  }
  throw new Error('could not locate the repository root')
}

const ROOT = repoRoot()
const LAB = join(ROOT, 'backend', 'lab')
// NOT `public/lab`: a static directory of that name shadows the /lab
// route in production, which 404s the index while the children resolve.
const OUT = join(ROOT, 'web', 'public', 'lab-artifacts')

function sha256(text: string): string {
  return createHash('sha256').update(text).digest('hex')
}

function git(...args: string[]): string | null {
  try {
    return execFileSync('git', args, { cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim()
  } catch {
    return null
  }
}

/**
 * The revision of the evidence, not of HEAD.
 *
 * Same reasoning as the evaluation export: this artifact is committed, so
 * anchoring to HEAD would make every commit invalidate the next check. It is
 * anchored to the inputs instead, which is the more useful statement anyway.
 */
const EVIDENCE_PATHS = ['backend/lab/contract', 'backend/lab/cases', 'backend/lab/records', 'backend/lab/runs']

/** The code whose execution produced a run: candidates, harness, orchestrator. */
const EXECUTED_PATHS = ['backend/lab']

/** The trusted grader that computed the verdict. */
const EVALUATOR_PATHS = ['web/lib/lab']

/** Every candidate is expressed as a change to the historical parser. */
const BASELINE_PATH = 'backend/lab/contract/versions/positional_v0.py'

/**
 * A unified diff, computed with the repository's own `git diff --no-index`.
 *
 * Shelling out to git rather than hand-rolling an LCS: the output is the
 * format a reviewer already knows and `git apply` already accepts, which is
 * what makes the downloadable patch on the run page actually usable.
 */
function unifiedDiff(fromPath: string, fromText: string, toPath: string, toText: string): string {
  if (fromPath === toPath) return ''
  const tmp = mkdtempSync(join(tmpdir(), 'lab-diff-'))
  try {
    const a = join(tmp, 'baseline.py')
    const b = join(tmp, 'candidate.py')
    writeFileSync(a, fromText)
    writeFileSync(b, toText)
    try {
      execFileSync('git', ['diff', '--no-index', '--no-color', '--unified=3', a, b], {
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
      })
      return ''
    } catch (error) {
      // `git diff --no-index` exits 1 when the files differ, which is the
      // normal path here; the diff is on stdout.
      const out = (error as { stdout?: string }).stdout ?? ''
      // git prints the temp paths with its own a/ and b/ prefixes already
      // attached, so swap the whole prefixed form rather than the bare path.
      return out.split(`a${a}`).join(`a/${fromPath}`).split(`b${b}`).join(`b/${toPath}`)
    }
  } finally {
    rmSync(tmp, { recursive: true, force: true })
  }
}

interface EventRecord {
  type: string
  at?: string
  attempt_id?: string
  runner?: string
  status?: string
  note?: string
  n_records?: number
  detail?: string
  allowed?: boolean
}

function readEvents(path: string): EventRecord[] {
  if (!existsSync(path)) return []
  return readFileSync(path, 'utf8')
    .split('\n')
    .filter((l) => l.trim() !== '')
    .map((l) => JSON.parse(l) as EventRecord)
}

function loadCases(): { cases: Case[]; refs: LabRun['provenance']['case_suites'] } {
  const cases: Case[] = []
  const refs: LabRun['provenance']['case_suites'] = []
  for (const group of ['observed', 'synthetic'] as const) {
    const path = join(LAB, 'cases', `${group}.json`)
    const text = readFileSync(path, 'utf8')
    const parsed = parseCaseSuite(JSON.parse(text))
    if (!parsed.ok) throw new Error(`invalid case suite ${group}: ${parsed.issues.join('; ')}`)
    cases.push(...parsed.value.cases)
    refs.push({
      group,
      path: `backend/lab/cases/${group}.json`,
      sha256: sha256(text),
      n_cases: parsed.value.cases.length,
      generated_from: parsed.value.generated_from,
    })
  }
  return { cases, refs }
}

interface RunInput {
  readonly candidate_id: string
  readonly tag: string
  readonly bundlePath: string
  readonly eventsPath: string
}

function discoverRuns(): RunInput[] {
  const runsDir = join(LAB, 'runs')
  const inputs: RunInput[] = []
  for (const file of readdirSync(runsDir).sort()) {
    const match = /^(.+)-([a-z]+)\.events\.jsonl$/.exec(file)
    if (match === null) continue
    const [, candidate, tag] = match
    if (candidate === undefined || tag === undefined) continue
    // A clean run reuses the committed record bundle; a tagged run has its own.
    const tagged = join(runsDir, `${candidate}-${tag}.records.json`)
    const committed = join(LAB, 'records', `${candidate}.json`)
    inputs.push({
      candidate_id: candidate,
      tag,
      bundlePath: existsSync(tagged) ? tagged : committed,
      eventsPath: join(runsDir, file),
    })
  }
  return inputs
}

function buildRun(input: RunInput, cases: Case[], refs: LabRun['provenance']['case_suites']): LabRun {
  const known = KNOWN_IMPLEMENTATIONS.find((k) => k.candidate_id === input.candidate_id)
  if (known === undefined) throw new Error(`no known implementation for ${input.candidate_id}`)

  const sourceText = readFileSync(join(ROOT, known.path), 'utf8')
  const baselineText = readFileSync(join(ROOT, BASELINE_PATH), 'utf8')
  const events = readEvents(input.eventsPath)
  const created = events.find((e) => e.type === 'created')
  const runIdFromLog = (created as { run_id?: string } | undefined)?.run_id

  let bundle: RecordBundle | null = null
  let failure: string | undefined
  if (existsSync(input.bundlePath)) {
    const parsed = parseRecordBundle(JSON.parse(readFileSync(input.bundlePath, 'utf8')))
    if (parsed.ok) bundle = parsed.value
    else failure = `record bundle did not validate: ${parsed.issues.join('; ')}`
  } else {
    failure = 'no record bundle was produced'
  }

  const evaluation =
    failure === undefined ? evaluate(cases, bundle) : evaluate(cases, null, { failure })

  const attempts: LabRun['attempts'] = events
    .filter((e) => e.type === 'attempt-started')
    .map((start) => {
      const end = events.find(
        (e) => e.type === 'attempt-ended' && e.attempt_id === start.attempt_id,
      )
      const reported = end?.status
      // An attempt with no completion event is one the orchestrator never saw
      // finish. That is `unknown-outcome`, not `failed`: whether the work
      // completed is genuinely not knowable from the log.
      const status: LabRun['attempts'][number]['status'] =
        reported === 'succeeded' || reported === 'failed' || reported === 'cancelled'
          ? reported
          : 'unknown-outcome'
      return {
        attempt_id: start.attempt_id ?? UNKNOWN,
        started_at: start.at ?? UNKNOWN,
        ended_at: end?.at ?? UNKNOWN,
        status,
        runner: start.runner === 'vercel-sandbox' ? ('vercel-sandbox' as const) : ('local-known' as const),
        note: end?.note ?? 'no completion event was persisted for this attempt',
      }
    })

  const faultInjected = events.some((e) => (e.note ?? '').includes('orchestrator died'))

  const notes: LabRun['provenance']['notes'] = [
    {
      severity: 'info',
      message:
        'Every case ran offline against responses already committed to this repository. No inference call was made and no provider was charged.',
      source: 'backend/evals/.cache/llm',
    },
    {
      severity: 'caution',
      message:
        'The case suite is public. A candidate may have been written against it, so passing does not establish generalisation.',
      source: 'backend/lab/cases/',
    },
  ]
  if (known.kind === 'seeded-control') {
    notes.unshift({
      severity: 'warning',
      message: `This is a seeded control with a deliberate defect. ${known.description}`,
      source: known.path,
    })
  }
  if (input.candidate_id === 'keyed-v2') {
    notes.push({
      severity: 'caution',
      message:
        'Association correctness is measured; relevance quality under keyed-v2 is not. Sending article ids changes the request, which invalidates every recorded response for this runner — new budgeted recordings would be required and none exist.',
      source: 'backend/evals/llm_cache.py:133',
    })
  }
  if (faultInjected) {
    notes.unshift({
      severity: 'info',
      message:
        'A fault was deliberately injected into this run: the orchestrator was SIGKILLed with an attempt in flight. The recovery that follows is real.',
      source: 'backend/lab/orchestrate.py --kill-after',
    })
  }

  const artifactRevision = git('log', '-1', '--format=%h', '--', ...EVIDENCE_PATHS) ?? UNKNOWN
  const builtAt = git('log', '-1', '--format=%cI', '--', ...EVIDENCE_PATHS) ?? new Date().toISOString()

  return {
    lab_artifact_version: LAB_ARTIFACT_VERSION,
    // The orchestrator's run id is deterministic in (candidate, source, spec),
    // so a *retry* reconciles onto the same run. These are two separate
    // executions of the same work, so the tag distinguishes them.
    run_id: `${runIdFromLog ?? `${EXPERIMENT.experiment_id}__${input.candidate_id}`}__${input.tag}`,
    experiment_id: EXPERIMENT.experiment_id,
    candidate: {
      candidate_id: known.candidate_id,
      kind: known.kind,
      description: known.description,
      declared_protocol: known.declared_protocol,
      source_path: known.path,
      source_sha256: sha256(sourceText),
      source_bytes: Buffer.byteLength(sourceText),
      transcribed_from: known.transcribed_from,
      patch: unifiedDiff(BASELINE_PATH, baselineText, known.path, sourceText),
      patch_base: BASELINE_PATH,
    },
    provenance: {
      // Anchored to the code that ran, NOT to HEAD.
      //
      // `rev-parse HEAD` is the obvious choice and it breaks the staleness
      // gate permanently: this export is committed, so committing it moves
      // HEAD, which changes the next export, which never matches the commit.
      // CI then fails forever with "run export:lab and commit the result" and
      // committing the result does not help.
      //
      // The comment this replaces already conceded the harness ran from a
      // working tree rather than "at this commit", so the last commit to touch
      // the executed code is both stable and the more accurate claim. Same
      // reasoning for the evaluator. A commit that changes either of those
      // paths does require a follow-up regeneration commit -- that is the
      // gate working, not the gate broken.
      executed_at_revision: git('log', '-1', '--format=%h', '--', ...EXECUTED_PATHS) ?? UNKNOWN,
      artifact_revision: artifactRevision,
      artifact_built_at: builtAt,
      executed_at: created?.at ?? UNKNOWN,
      evaluator_revision: git('log', '-1', '--format=%h', '--', ...EVALUATOR_PATHS) ?? UNKNOWN,
      spec_hash: specHash(),
      spec_version: EXPERIMENT.spec_version,
      execution_mode: 'offline-replay',
      execution_mode_basis:
        'The harness reads committed responses from disk and makes no network call. The candidate imports nothing beyond the standard library.',
      python: bundle?.python ?? UNKNOWN,
      case_suites: refs,
      notes,
    },
    verdict: evaluation.verdict,
    verdict_reason: evaluation.reason,
    verdict_scope: VERDICT_SCOPE,
    criteria: evaluation.criteria.map((c) => ({ ...c })),
    outcomes: evaluation.outcomes.map((o) => ({
      ...o,
      expected_refusal_kinds: [...o.expected_refusal_kinds],
    })),
    counts: { ...evaluation.counts },
    smallest_counterexample: evaluation.smallest_counterexample,
    usage: {
      model_calls: 0,
      replay_spend_usd: 0,
      recording_cost_usd: UNKNOWN,
      provider_reported: UNKNOWN,
      basis:
        'Offline replay of committed recordings. Actual provider spend for this run is $0. What the original recordings cost is not attributed per batch anywhere in this repository, so it is left unknown rather than estimated.',
    },
    attempts,
  }
}

/**
 * One real batch, exported so the site can show the failure rather than
 * describe it.
 *
 * Chosen by rule, not by taste: the observed case with the largest gap between
 * verdicts returned and articles sent. Article bodies are not republished —
 * only the id, title and source that the prompt already carried — and the
 * response is the recorded bytes, truncated for the page with the full length
 * stated.
 */
function buildOffendingCase(cases: Case[]): unknown {
  const mismatches = cases
    .filter((c) => c.group === 'observed' && c.expectation.refusal_kinds.includes('count_mismatch'))
    .map((c) => {
      const parsed = JSON.parse(c.response.content ?? '{}') as { results?: unknown[] }
      const returned = Array.isArray(parsed.results) ? parsed.results.length : 0
      return { kase: c, returned, gap: Math.abs(returned - c.articles.length) }
    })
    .sort((a, b) => b.gap - a.gap)

  const worst = mismatches[0]
  if (worst === undefined) return null
  const { kase, returned } = worst
  const content = kase.response.content ?? ''
  const parsed = JSON.parse(content) as { results?: { reason?: string }[] }
  const verdicts = (parsed.results ?? []).slice(0, 6).map((r, i) => ({
    position: i,
    reason: String(r.reason ?? '').slice(0, 220),
  }))

  return {
    case_id: kase.case_id,
    snapshot: kase.snapshot ?? UNKNOWN,
    articles_sent: kase.articles.length,
    verdicts_returned: returned,
    // The first six of each side, which is enough to see that position is the
    // only thing tying them together.
    articles: kase.articles.slice(0, 6).map((a, i) => ({ position: i, ...a })),
    verdicts,
    response_bytes: Buffer.byteLength(content),
    response_head: content.slice(0, 600),
    finish_reason: kase.response.finish_reason ?? UNKNOWN,
    note:
      'Recorded during an offline replay of the production runner. No article identifier appears anywhere in the request or the response: position is the only thing associating a verdict with an article.',
    source: 'backend/evals/.cache/llm',
  }
}

function main(): void {
  const { cases, refs } = loadCases()
  const inputs = discoverRuns()
  if (inputs.length === 0) throw new Error('no run event logs found under backend/lab/runs/')

  const written: { file: string; json: string; run: LabRun }[] = []
  for (const input of inputs) {
    const run = buildRun(input, cases, refs)
    const validated = parseLabRun(run)
    if (!validated.ok) {
      throw new Error(`built an invalid run artifact for ${input.candidate_id}: ${validated.issues.join('; ')}`)
    }
    const file = `${input.candidate_id}-${input.tag}.json`
    written.push({ file, json: `${JSON.stringify(validated.value, null, 1)}\n`, run: validated.value })
  }

  const manifest: LabManifest = {
    lab_manifest_version: LAB_ARTIFACT_VERSION,
    experiment_id: EXPERIMENT.experiment_id,
    spec_hash: specHash(),
    artifact_revision: git('log', '-1', '--format=%h', '--', ...EVIDENCE_PATHS) ?? UNKNOWN,
    built_at: git('log', '-1', '--format=%cI', '--', ...EVIDENCE_PATHS) ?? new Date().toISOString(),
    complete: true,
    entries: written.map((w) => ({
      run_id: w.run.run_id,
      file: w.file,
      candidate_id: w.run.candidate.candidate_id,
      kind: w.run.candidate.kind,
      verdict: w.run.verdict,
      spec_hash: w.run.provenance.spec_hash,
      sha256: sha256(w.json),
      bytes: Buffer.byteLength(w.json),
    })),
    notes: [
      {
        severity: 'info',
        message: `Sandbox limits for untrusted candidates: ${SANDBOX_LIMITS.image}, network ${SANDBOX_LIMITS.network}, ${SANDBOX_LIMITS.wall_clock_seconds}s wall clock, ${SANDBOX_LIMITS.secrets} secrets.`,
        source: 'web/lib/lab/runner.ts',
      },
      {
        severity: 'caution',
        message:
          'Every run in this set executed locally, because each candidate is byte-identical to an implementation committed in this repository. Nothing novel has been executed.',
        source: 'web/lib/lab/runner.ts selectRunner',
      },
    ],
  }

  const offendingJson = `${JSON.stringify(buildOffendingCase(cases), null, 1)}\n`

  const manifestValidated = parseLabManifest(manifest)
  if (!manifestValidated.ok) throw new Error(`invalid manifest: ${manifestValidated.issues.join('; ')}`)
  const manifestJson = `${JSON.stringify(manifestValidated.value, null, 1)}\n`

  if (CHECK_ONLY) {
    const problems: string[] = []
    for (const w of written) {
      const path = join(OUT, w.file)
      if (!existsSync(path)) problems.push(`${w.file} is missing from the committed export`)
      else if (readFileSync(path, 'utf8') !== w.json) problems.push(`${w.file} is stale`)
    }
    const offendingPath = join(OUT, 'offending-case.json')
    if (!existsSync(offendingPath)) problems.push('offending-case.json is missing')
    else if (readFileSync(offendingPath, 'utf8') !== offendingJson) problems.push('offending-case.json is stale')
    const manifestPath = join(OUT, 'manifest.json')
    if (!existsSync(manifestPath)) problems.push('manifest.json is missing')
    else if (readFileSync(manifestPath, 'utf8') !== manifestJson) problems.push('manifest.json is stale')
    if (problems.length > 0) {
      console.error(`lab export is out of date:\n  ${problems.join('\n  ')}`)
      console.error('run `npm run export:lab` and commit the result')
      process.exitCode = 1
      return
    }
    console.log(`validated ${written.length} lab runs + manifest (no files written)`)
    return
  }

  rmSync(OUT, { recursive: true, force: true })
  mkdirSync(OUT, { recursive: true })
  for (const w of written) writeFileSync(join(OUT, w.file), w.json)
  writeFileSync(join(OUT, 'offending-case.json'), offendingJson)
  // Manifest last: it asserts that everything it lists is present.
  writeFileSync(join(OUT, 'manifest.json'), manifestJson)

  console.log(`wrote ${written.length} runs + manifest to web/public/lab/`)
  for (const w of written) {
    console.log(`  ${w.run.candidate.candidate_id.padEnd(24)} ${w.run.verdict}`)
  }
}

main()
