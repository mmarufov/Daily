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
import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs'
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
const OUT = join(ROOT, 'web', 'public', 'lab-artifacts')

function sha256(text: string): string {
  return createHash('sha256').update(text).digest('hex')
}

/**
 * THE EXPORT READS NO GIT, AND HASHES ONLY WHAT IT READ.
 *
 * Two bugs, same class: a committed export has to be a pure function of
 * committed bytes, and twice it was not.
 *
 *  1. Provenance came from `git log --format=%h`, and the embedded patch
 *     carried git's `index <blob>..<blob>` line. Both honour `core.abbrev`,
 *     which defaults to `auto` and is derived from a clone's object count — so
 *     the same tree exported to different bytes in CI than locally.
 *  2. The replacement hashed a directory *walk*, which swept up
 *     `__pycache__/*.pyc` and the gitignored `runs/*.records.json`. Those
 *     exist on a machine that has run the harness and not in a fresh CI
 *     checkout, so the hash moved again.
 *
 * The fix for (2) is to stop discovering inputs and start recording them:
 * every file the export reads goes through `readInput`, and `inputs_sha256`
 * is a hash over exactly that set. A stray file cannot enter a hash of reads
 * it was never part of, and a new input cannot be forgotten, because reading
 * it is what registers it.
 */
type Reads = Map<string, string>

/** Every read, for the manifest. */
const ALL_READS: Reads = new Map()

/** Reads belonging to the run currently being built, if one is. */
let currentScope: Reads | null = null

function readInput(relPath: string): string {
  const text = readFileSync(join(ROOT, relPath), 'utf8')
  const digest = sha256(text)
  ALL_READS.set(relPath, digest)
  currentScope?.set(relPath, digest)
  return text
}

function digestOf(reads: ReadonlyMap<string, string>): string {
  return sha256(
    [...reads.entries()]
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([path, digest]) => `${path}:${digest}`)
      .join('\n'),
  ).slice(0, 16)
}

/**
 * Run `fn` while recording which files it reads, and give it the live set so
 * it can hash exactly its own inputs.
 *
 * Scoping this per run is not decoration: a run's provenance should move when
 * that run's evidence moves and stay put otherwise. A single global hash
 * meant adding an eighth run rewrote the provenance of the other seven.
 */
function recordingReads<T>(seed: ReadonlyMap<string, string>, fn: (reads: Reads) => T): T {
  const outer = currentScope
  const mine: Reads = new Map(seed)
  currentScope = mine
  try {
    return fn(mine)
  } finally {
    currentScope = outer
  }
}

/**
 * The trusted grader, hashed by content.
 *
 * Restricted to `.ts` so an editor artefact or a `.DS_Store` cannot change
 * what the artifact claims about the evaluator.
 */
function hashEvaluator(): string {
  const dir = join(ROOT, 'web', 'lib', 'lab')
  const parts = readdirSync(dir)
    .filter((f) => f.endsWith('.ts'))
    .sort()
    .map((f) => `${f}:${sha256(readFileSync(join(dir, f), 'utf8'))}`)
  return sha256(parts.join('\n')).slice(0, 16)
}

/** Every candidate is expressed as a change to the historical parser. */
const BASELINE_PATH = 'backend/lab/contract/versions/positional_v0.py'

/**
 * A unified diff, in the format a reviewer already knows and `git apply`
 * already accepts.
 *
 * `git diff --no-index` writes an `index <blob>..<blob>` line naming blobs of
 * two temp files that exist nowhere, abbreviated by `core.abbrev` — which is
 * `auto` by default and varies with a clone's object count. Embedding it put
 * an environment-dependent string into all seven committed runs at once, which
 * is exactly why CI reported every file stale while every local check passed.
 * It is dropped: it carries nothing a reader can use, and `git apply` does not
 * need it.
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
      return out
        .split(`a${a}`)
        .join(`a/${fromPath}`)
        .split(`b${b}`)
        .join(`b/${toPath}`)
        .split('\n')
        .filter((line) => !line.startsWith('index '))
        .join('\n')
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
  executed_at_revision?: string
  python?: string
}

function readEvents(relPath: string): EventRecord[] {
  if (!existsSync(join(ROOT, relPath))) return []
  return readInput(relPath)
    .split('\n')
    .filter((l) => l.trim() !== '')
    .map((l) => JSON.parse(l) as EventRecord)
}

function loadCases(): { cases: Case[]; refs: LabRun['provenance']['case_suites']; reads: Reads } {
  const cases: Case[] = []
  const refs: LabRun['provenance']['case_suites'] = []
  const reads: Reads = new Map()
  for (const group of ['observed', 'synthetic'] as const) {
    const rel = `backend/lab/cases/${group}.json`
    const text = readInput(rel)
    reads.set(rel, sha256(text))
    const parsed = parseCaseSuite(JSON.parse(text))
    if (!parsed.ok) throw new Error(`invalid case suite ${group}: ${parsed.issues.join('; ')}`)
    cases.push(...parsed.value.cases)
    refs.push({
      group,
      path: rel,
      sha256: sha256(text),
      n_cases: parsed.value.cases.length,
      generated_from: parsed.value.generated_from,
    })
  }
  return { cases, refs, reads }
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
    // Always the committed bundle, never the one sitting in `runs/`.
    //
    // Re-running the harness drops `runs/<candidate>-<tag>.records.json`
    // beside the event log, and `backend/.gitignore` excludes it. This used to
    // prefer it when present, so a machine that had run the harness exported
    // from evidence no reviewer could see. The two agree on every field that
    // means anything -- the measured diff was ten `ms` timings, microsecond
    // scheduling noise -- but "agrees today" is not the property wanted here.
    // A committed artifact has to be a function of committed bytes.
    inputs.push({
      candidate_id: candidate,
      tag,
      bundlePath: `backend/lab/records/${candidate}.json`,
      eventsPath: `backend/lab/runs/${file}`,
    })
  }
  return inputs
}

function buildRun(
  input: RunInput,
  cases: Case[],
  refs: LabRun['provenance']['case_suites'],
  caseReads: ReadonlyMap<string, string>,
): LabRun {
  return recordingReads(caseReads, (reads) => buildRunInScope(input, cases, refs, reads))
}

function buildRunInScope(
  input: RunInput,
  cases: Case[],
  refs: LabRun['provenance']['case_suites'],
  reads: Reads,
): LabRun {
  const known = KNOWN_IMPLEMENTATIONS.find((k) => k.candidate_id === input.candidate_id)
  if (known === undefined) throw new Error(`no known implementation for ${input.candidate_id}`)

  const sourceText = readInput(known.path)
  const baselineText = readInput(BASELINE_PATH)
  const events = readEvents(input.eventsPath)
  const created = events.find((e) => e.type === 'created')
  const runIdFromLog = (created as { run_id?: string } | undefined)?.run_id

  let bundle: RecordBundle | null = null
  let failure: string | undefined
  if (existsSync(join(ROOT, input.bundlePath))) {
    const parsed = parseRecordBundle(JSON.parse(readInput(input.bundlePath)))
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
      // Recorded by the orchestrator at the moment the harness ran, not
      // re-derived here. Carries `+dirty` when the tree was edited.
      //
      // Deriving it here from `rev-parse HEAD` is the obvious choice and it
      // breaks the staleness gate permanently: this export is committed, so
      // committing it moves HEAD, which changes the next export, which never
      // matches the commit. CI then fails forever with "run export:lab and
      // commit the result", and committing the result does not help.
      executed_at_revision: created?.executed_at_revision ?? UNKNOWN,
      // Every byte this run was built from. Digested after the reads above,
      // so it cannot silently omit one.
      inputs_sha256: digestOf(reads),
      executed_at: created?.at ?? UNKNOWN,
      evaluator_sha256: hashEvaluator(),
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

/**
 * The gate with teeth: every byte this export consumed must be a byte a
 * reviewer can see.
 *
 * `inputs_sha256` makes an uncommitted input *detectable* -- CI rebuilds from
 * a fresh checkout, the hash moves, the check fails. It does not make it
 * *legible*: what CI printed was seven identical hash mismatches, which is
 * true and says nothing about why. This is the same property stated directly,
 * so the failure arrives as the name of the offending file.
 *
 * Git appears here and nowhere else. It decides whether to *accept* the
 * export; it contributes nothing to what the export says, which is the
 * distinction the first version of this file got wrong.
 */
function uncommittedInputs(): string[] {
  let tracked: Set<string>
  try {
    tracked = new Set(
      execFileSync('git', ['ls-files', '-z', '--', ...ALL_READS.keys()], {
        cwd: ROOT,
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore'],
      })
        .split('\0')
        .filter((p) => p !== ''),
    )
  } catch {
    // No git, or not a repository. The hash comparison below still catches
    // this; it just cannot name the file.
    return []
  }
  return [...ALL_READS.keys()]
    .filter((p) => !tracked.has(p))
    .sort()
    .map(
      (p) =>
        `${p} is read by the export but is not committed, so this artifact is not reproducible from the repository`,
    )
}

function main(): void {
  const { cases, refs, reads: caseReads } = loadCases()
  const inputs = discoverRuns()
  if (inputs.length === 0) throw new Error('no run event logs found under backend/lab/runs/')

  const written: { file: string; json: string; run: LabRun }[] = []
  for (const input of inputs) {
    const run = buildRun(input, cases, refs, caseReads)
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
    inputs_sha256: digestOf(ALL_READS),
    // The newest run's own timestamp, out of the committed logs. Never "now":
    // a clock reading would make every regeneration differ from the last.
    built_at: written.map((w) => w.run.provenance.executed_at).sort().at(-1) ?? UNKNOWN,
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
    const problems: string[] = [...uncommittedInputs()]
    // "stale" on its own is not a diagnosis. When the committed bytes and the
    // regenerated bytes disagree, say which line and show both sides --
    // otherwise a failure that only reproduces in CI is unfixable from here.
    const describe = (file: string, committed: string, rebuilt: string): string => {
      const a = committed.split('\n')
      const b = rebuilt.split('\n')
      for (let i = 0; i < Math.max(a.length, b.length); i += 1) {
        if (a[i] === b[i]) continue
        return [
          `${file} differs at line ${i + 1}`,
          `    committed: ${JSON.stringify(a[i] ?? '<absent>').slice(0, 160)}`,
          `    rebuilt:   ${JSON.stringify(b[i] ?? '<absent>').slice(0, 160)}`,
        ].join('\n')
      }
      return `${file} differs in length only (${a.length} vs ${b.length} lines)`
    }
    for (const w of written) {
      const path = join(OUT, w.file)
      if (!existsSync(path)) problems.push(`${w.file} is missing from the committed export`)
      else {
        const committed = readFileSync(path, 'utf8')
        if (committed !== w.json) problems.push(describe(w.file, committed, w.json))
      }
    }
    const offendingPath = join(OUT, 'offending-case.json')
    if (!existsSync(offendingPath)) problems.push('offending-case.json is missing')
    else if (readFileSync(offendingPath, 'utf8') !== offendingJson) {
      problems.push(describe('offending-case.json', readFileSync(offendingPath, 'utf8'), offendingJson))
    }
    const manifestPath = join(OUT, 'manifest.json')
    if (!existsSync(manifestPath)) problems.push('manifest.json is missing')
    else {
      const committed = readFileSync(manifestPath, 'utf8')
      if (committed !== manifestJson) problems.push(describe('manifest.json', committed, manifestJson))
    }
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

  console.log(`wrote ${written.length} runs + manifest to web/public/lab-artifacts/`)
  for (const w of written) {
    console.log(`  ${w.run.candidate.candidate_id.padEnd(24)} ${w.run.verdict}`)
  }
}

main()
