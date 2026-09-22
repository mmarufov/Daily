/**
 * Run one real investigation, end to end.
 *
 *   npm run lab:agent            # investigate, propose, sandbox, evaluate
 *   npm run lab:agent -- --sandbox-only <file.py>   # boundary only, no model
 *
 * This is the script that turns three schemas into three exercised systems.
 * It writes the same evidence shape the Python orchestrator writes -- an
 * append-only event log, a record bundle -- so `export-lab.ts` picks the run
 * up with no special case, and the agent's candidate is graded by the same
 * evaluator, against the same frozen suite, under the same spec hash as the
 * six hand-written ones.
 *
 * Nothing here decides anything. The model proposes, the scope gate admits or
 * refuses, the sandbox executes, and the evaluator judges. The script's only
 * job is to make sure each of those hears about the previous one.
 */

import { execFileSync } from 'node:child_process'
import { appendFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { investigate, type InvestigationTrace } from '../lib/lab/agent'
import { evaluate } from '../lib/lab/evaluator'
import { parseCaseSuite, parseRecordBundle, type Case } from '../lib/lab/records'
import { KNOWN_IMPLEMENTATIONS, selectRunner, sha256 } from '../lib/lab/runner'
import { runInSandbox, sandboxCredentials, type SandboxExecution } from '../lib/lab/sandbox'
import { uploadSet } from '../lib/lab/upload-set'
import { EXPERIMENT, specHash } from '../lib/lab/spec'

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
const RUNS = join(LAB, 'runs')

function loadCases(): Case[] {
  const cases: Case[] = []
  for (const group of ['observed', 'synthetic'] as const) {
    const parsed = parseCaseSuite(JSON.parse(readFileSync(join(LAB, 'cases', `${group}.json`), 'utf8')))
    if (!parsed.ok) throw new Error(`invalid case suite ${group}: ${parsed.issues.join('; ')}`)
    cases.push(...parsed.value.cases)
  }
  return cases
}

/** Bounded reader for the four allowlisted paths. Cannot enumerate anything. */
function readSource(path: string, startLine: number, lineCount: number): string {
  const abs = join(ROOT, path)
  if (!existsSync(abs)) throw new Error(`${path} does not exist in this checkout`)
  const lines = readFileSync(abs, 'utf8').split('\n')
  return lines
    .slice(startLine - 1, startLine - 1 + lineCount)
    .map((l, i) => `${startLine + i}\t${l}`)
    .join('\n')
}

/**
 * The revision this run executed at, recorded now rather than derived later.
 *
 * `+dirty` when the tree was edited, because a run from an edited tree is not
 * a run at that commit. Same rule `orchestrate.py` follows, and the export
 * copies this through instead of re-deriving it -- see the comment there
 * about why `rev-parse HEAD` at export time makes the staleness gate
 * permanently unpassable.
 */
function revision(): string {
  try {
    const sha = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: ROOT, encoding: 'utf8' }).trim()
    const dirty = execFileSync('git', ['status', '--porcelain'], { cwd: ROOT, encoding: 'utf8' }).trim()
    return `${sha}${dirty === '' ? '' : '+dirty'}`
  } catch {
    return 'unknown'
  }
}

function log(runsFile: string, event: Record<string, unknown>): void {
  appendFileSync(runsFile, `${JSON.stringify({ ...event, at: new Date().toISOString() })}\n`)
}

/* -------------------------------------------------- sandbox execution --- */

interface SandboxOutcome {
  readonly execution: SandboxExecution
  readonly bundleJson: string | null
  readonly failure: string | null
}

async function executeInSandbox(source: string, onProgress: (s: string) => void): Promise<SandboxOutcome> {
  const credentials = sandboxCredentials()
  if ('missing' in credentials) {
    throw new Error(
      `the sandbox cannot run: missing ${credentials.missing.join(', ')}. ` +
        'Refusing to fall back to local execution — an unknown candidate running locally is the ' +
        'one outcome selectRunner exists to prevent.',
    )
  }

  // The routing decision, made from bytes and asserted rather than assumed.
  const known = new Map(
    KNOWN_IMPLEMENTATIONS.map((k) => [k.candidate_id, sha256(readFileSync(join(ROOT, k.path), 'utf8'))]),
  )
  const decision = selectRunner(source, known)
  if (decision.runner !== 'vercel-sandbox') {
    throw new Error(
      `this candidate is byte-identical to ${decision.known?.candidate_id}, so it routes to ` +
        'local-known and would not exercise the boundary. Supply a candidate that is not already committed.',
    )
  }

  const execution = await runInSandbox({ candidateSource: source, files: await uploadSet(LAB), credentials, onProgress })
  if (execution.exit_code !== 0 || execution.records_json === null) {
    return {
      execution,
      bundleJson: null,
      failure: `the harness exited ${execution.exit_code} in the sandbox: ${execution.stderr.slice(0, 400) || '(no stderr)'}`,
    }
  }
  return { execution, bundleJson: execution.records_json, failure: null }
}

/* ------------------------------------------------------------- main ---- */

async function main(): Promise<number> {
  const argv = process.argv.slice(2)
  const sandboxOnlyAt = argv.indexOf('--sandbox-only')
  const cases = loadCases()

  if (sandboxOnlyAt !== -1) {
    const file = argv[sandboxOnlyAt + 1]
    if (file === undefined) throw new Error('--sandbox-only needs a path to a candidate file')
    return runSandboxOnly(file, cases)
  }

  const candidateId = 'agent-001'
  const tag = 'sandbox'
  mkdirSync(RUNS, { recursive: true })
  const events = join(RUNS, `${candidateId}-${tag}.events.jsonl`)
  writeFileSync(events, '')
  log(events, {
    type: 'created',
    run_id: `${EXPERIMENT.experiment_id}__${candidateId}`,
    candidate_id: candidateId,
    spec_hash: specHash(),
    executed_at_revision: revision(),
  })

  let execution: SandboxExecution | null = null
  let bundleJson: string | null = null
  let failure: string | null = null
  let attempt = 0

  const result = await investigate({
    cases,
    readSource,
    onProgress: (s) => console.log(`  ${s}`),
    onScopeDecision: ({ accepted, path, reason }) =>
      log(events, { type: 'scope-checked', allowed: accepted, detail: `${path} — ${reason}` }),
    evaluateCandidate: async (id, source) => {
      attempt += 1
      const attemptId = `${EXPERIMENT.experiment_id}__${candidateId}#${String(attempt).padStart(2, '0')}`
      log(events, { type: 'attempt-started', attempt_id: attemptId, runner: 'vercel-sandbox' })
      try {
        const outcome = await executeInSandbox(source, (s) => console.log(`    sandbox: ${s}`))
        execution = outcome.execution
        bundleJson = outcome.bundleJson
        failure = outcome.failure
        log(events, {
          type: 'attempt-ended',
          attempt_id: attemptId,
          status: outcome.failure === null ? 'succeeded' : 'failed',
          note:
            outcome.failure ??
            `sandbox ${outcome.execution.sandbox_id} in ${outcome.execution.region}, exit 0 in ${outcome.execution.wall_clock_ms}ms`,
        })
      } catch (error) {
        failure = error instanceof Error ? error.message : String(error)
        log(events, { type: 'attempt-ended', attempt_id: attemptId, status: 'failed', note: failure })
      }

      // What the agent is told: what the records showed. Not the verdict, not
      // the criteria, not whether it passed. Returning the verdict would let a
      // second proposal be tuned against the grader, and there is no second
      // proposal precisely so that this stays true.
      if (bundleJson === null) return { summary: `the run did not produce records: ${failure}`, evaluation: null }
      const parsed = parseRecordBundle(JSON.parse(bundleJson))
      if (!parsed.ok) return { summary: `the record bundle did not validate: ${parsed.issues.join('; ')}`, evaluation: null }
      const tally = parsed.value.records.reduce<Record<string, number>>((acc, r) => {
        acc[r.outcome] = (acc[r.outcome] ?? 0) + 1
        return acc
      }, {})
      return {
        summary: `${parsed.value.records.length} records: ${Object.entries(tally)
          .map(([k, v]) => `${v} ${k}`)
          .join(', ')}.`,
        evaluation: null,
      }
    },
  })

  if (!result.ok) {
    console.error(`the investigation did not start: ${result.reason}`)
    for (const need of result.needs) console.error(`  needs ${need}`)
    return 2
  }

  const trace = result.trace
  console.log(
    `\nmodel ${trace.model} · ${trace.tool_calls_made} tool calls · ` +
      `${trace.usage.total_tokens ?? '?'} tokens · finish ${trace.finish_reason}`,
  )

  writeArtifacts({ candidateId, tag, events, trace, execution, bundleJson, failure })
  return 0
}

async function runSandboxOnly(file: string, _cases: Case[]): Promise<number> {
  const source = readFileSync(file, 'utf8')
  console.log(`sandbox-only: ${file} (${source.length} bytes, sha256 ${sha256(source).slice(0, 16)})`)
  const outcome = await executeInSandbox(source, (s) => console.log(`  ${s}`))
  console.log(`\nsandbox ${outcome.execution.sandbox_id} · ${outcome.execution.region} · exit ${outcome.execution.exit_code}`)
  console.log(`boot ${outcome.execution.boot_ms}ms · run ${outcome.execution.wall_clock_ms}ms · egress ${outcome.execution.egress_bytes ?? '?'} bytes`)
  console.log(`network policy the platform applied: ${outcome.execution.network_policy}`)
  for (const probe of outcome.execution.isolation) {
    console.log(`  ${probe.held ? 'held  ' : 'FAILED'} ${probe.name}: ${probe.observed.slice(0, 120)}`)
  }
  if (outcome.failure !== null) console.log(`\nfailure: ${outcome.failure}`)
  return outcome.execution.isolation.every((p) => p.held) ? 0 : 1
}

interface WriteArgs {
  candidateId: string
  tag: string
  events: string
  trace: InvestigationTrace
  execution: SandboxExecution | null
  bundleJson: string | null
  failure: string | null
}

function writeArtifacts(args: WriteArgs): void {
  const { candidateId, tag, trace, execution, bundleJson } = args
  const base = join(RUNS, `${candidateId}-${tag}`)

  writeFileSync(`${base}.trace.json`, `${JSON.stringify(trace, null, 1)}\n`)

  if (execution !== null) {
    const { stdout, stderr, records_json, candidate_sha256, ...rest } = execution
    void stdout
    void stderr
    void records_json
    void candidate_sha256
    writeFileSync(`${base}.sandbox.json`, `${JSON.stringify(rest, null, 1)}\n`)
  }

  const proposal = trace.proposal
  if (proposal !== null) {
    writeFileSync(
      `${base}.investigation.json`,
      `${JSON.stringify(
        {
          model: trace.model,
          gateway: trace.gateway,
          started_at: trace.started_at,
          wall_clock_ms: trace.wall_clock_ms,
          finish_reason: trace.finish_reason,
          tool_calls_made: trace.tool_calls_made,
          max_tool_calls: trace.budget.max_tool_calls,
          budget_ceiling_usd: trace.budget_ceiling_usd,
          usage: {
            input_tokens: trace.usage.input_tokens ?? 'unknown',
            output_tokens: trace.usage.output_tokens ?? 'unknown',
            total_tokens: trace.usage.total_tokens ?? 'unknown',
          },
          hypothesis: proposal.hypothesis,
          evidence: proposal.evidence,
          scope_accepted: proposal.scope_accepted,
          scope_reason: proposal.scope_reason,
          trace_path: `backend/lab/runs/${candidateId}-${tag}.trace.json`,
          n_trace_steps: trace.steps.length,
        },
        null,
        1,
      )}\n`,
    )
    // The candidate itself is committed so the patch on the page is the bytes
    // that ran, not a re-rendering of them.
    mkdirSync(join(LAB, 'contract'), { recursive: true })
    writeFileSync(join(LAB, 'contract', 'candidate.py'), proposal.content)
  }

  if (bundleJson !== null) {
    mkdirSync(join(LAB, 'records'), { recursive: true })
    writeFileSync(join(LAB, 'records', `${candidateId}.json`), bundleJson)
    const parsed = parseRecordBundle(JSON.parse(bundleJson))
    if (parsed.ok) {
      const verdict = evaluate(loadCases(), parsed.value)
      console.log(`\nevaluator: ${verdict.verdict} — ${verdict.reason}`)
      for (const c of verdict.criteria) {
        console.log(`  ${c.passed ? 'pass' : 'FAIL'}  ${c.id}  ${c.satisfied}/${c.applicable}`)
      }
    }
  }
  console.log(`\nwrote evidence under backend/lab/runs/${candidateId}-${tag}.*`)
  console.log(`spec ${specHash()} · run `)
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error(error instanceof Error ? error.stack : String(error))
    process.exit(1)
  })
