/**
 * Run one real investigation, end to end.
 *
 *   npm run lab:agent            # investigate, propose, sandbox, evaluate
 *   npm run lab:agent -- --sandbox-only <file.py>   # boundary only, no model
 *
 * Configuration, all optional:
 *
 *   LAB_MODEL          a gateway `provider/model` (default: DEFAULT_MODEL)
 *   LAB_BUDGET         JSON overrides of the investigation budget (see
 *                      investigator.ts); max_proposals is not overridable
 *   LAB_BUDGET_LABEL   the name recorded for an overridden budget
 *   LAB_CANDIDATE_ID   `agent-<id>`, so a series of runs does not overwrite
 *                      one another's evidence (default: agent-001)
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
import { appendFileSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
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

  const candidateId = process.env.LAB_CANDIDATE_ID ?? 'agent-001'
  if (!/^agent-[a-z0-9-]{1,40}$/.test(candidateId)) {
    throw new Error(`LAB_CANDIDATE_ID must match ^agent-[a-z0-9-]{1,40}$, got ${candidateId}`)
  }
  const tag = 'sandbox'
  mkdirSync(RUNS, { recursive: true })
  const events = join(RUNS, `${candidateId}-${tag}.events.jsonl`)
  if (existsSync(events)) {
    // Evidence of a run already made is not overwritten by the next one.
    throw new Error(`${candidateId} already has an event log; choose another LAB_CANDIDATE_ID`)
  }
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
  let evaluationRequestedBy: 'agent' | 'harness' | null = null

  /**
   * One sandbox execution and the tally the agent is allowed to see.
   *
   * Shared by the agent's `request_evaluation` and by the harness, which runs
   * an accepted proposal the agent never asked to have evaluated -- a
   * human-authored candidate is always executed, and the same path means the
   * same path. That is not a retry: it happens at most once per candidate,
   * after the loop has ended, and nothing it produces reaches the model.
   */
  const runEvaluation = async (source: string, by: 'agent' | 'harness'): Promise<string> => {
    attempt += 1
    evaluationRequestedBy ??= by
    const attemptId = `${EXPERIMENT.experiment_id}__${candidateId}#${String(attempt).padStart(2, '0')}`
    log(events, { type: 'attempt-started', attempt_id: attemptId, runner: 'vercel-sandbox' })
    try {
      const outcome = await executeInSandbox(source, (s) => console.log(`    sandbox: ${s}`))
      execution = outcome.execution
      bundleJson = outcome.bundleJson
      failure = outcome.failure
      // Isolation first, as orchestration.ts does: records from a microVM
      // that did not isolate are evidence about nothing and are not kept.
      const breached = outcome.execution.isolation.filter((p) => !p.held)
      if (breached.length > 0) {
        bundleJson = null
        failure = `isolation probes failed: ${breached.map((p) => p.name).join(', ')}`
      }
      log(events, {
        type: 'attempt-ended',
        attempt_id: attemptId,
        status: failure === null ? 'succeeded' : 'failed',
        note:
          (failure ??
            `sandbox ${outcome.execution.sandbox_id} in ${outcome.execution.region}, exit 0 in ${outcome.execution.wall_clock_ms}ms`) +
          (by === 'harness' ? '; run by the harness after the loop ended, because the agent did not request evaluation' : ''),
      })
      if (bundleJson !== null) {
        log(events, { type: 'records-received', attempt_id: attemptId, n_records: cases.length })
      }
    } catch (error) {
      failure = error instanceof Error ? error.message : String(error)
      log(events, { type: 'attempt-ended', attempt_id: attemptId, status: 'failed', note: failure })
    }

    // What the agent is told: what the records showed. Not the verdict, not
    // the criteria, not whether it passed. Returning the verdict would let a
    // second proposal be tuned against the grader, and there is no second
    // proposal precisely so that this stays true.
    if (bundleJson === null) return `the run did not produce records: ${failure}`
    const parsed = parseRecordBundle(JSON.parse(bundleJson))
    if (!parsed.ok) return `the record bundle did not validate: ${parsed.issues.join('; ')}`
    const tally = parsed.value.records.reduce<Record<string, number>>((acc, r) => {
      acc[r.outcome] = (acc[r.outcome] ?? 0) + 1
      return acc
    }, {})
    return `${parsed.value.records.length} records: ${Object.entries(tally)
      .map(([k, v]) => `${v} ${k}`)
      .join(', ')}.`
  }

  const result = await investigate({
    candidateId,
    cases,
    readSource,
    onProgress: (s) => console.log(`  ${s}`),
    onScopeDecision: ({ accepted, path, reason }) =>
      log(events, { type: 'scope-checked', allowed: accepted, detail: `${path} — ${reason}` }),
    evaluateCandidate: async (_id, source) => ({ summary: await runEvaluation(source, 'agent'), evaluation: null }),
  })

  if (!result.ok && result.reason !== 'call-failed') {
    // Refused before anything ran, so there is nothing to record and the
    // empty log would otherwise be exported as a run that never happened.
    rmSync(events, { force: true })
    console.error(`the investigation did not start: ${result.reason}`)
    for (const need of result.needs) console.error(`  needs ${need}`)
    return 2
  }

  // A failed call still produced a trace, and spend: it is recorded like any
  // other run rather than dropped, which would bias every rate computed from
  // the committed set towards the runs that finished.
  const trace = result.trace
  if (!result.ok) console.error(`the investigation stopped early: ${result.needs.join('; ')}`)

  if (trace.proposal?.scope_accepted === true && attempt === 0) {
    console.log('  the agent did not request evaluation; the harness runs the accepted proposal once')
    await runEvaluation(trace.proposal.content, 'harness')
  }

  console.log(
    `\nmodel ${trace.model} · budget ${trace.budget_label} · ${trace.model_calls_made} model calls · ` +
      `${trace.tool_calls_made} tool calls · ${trace.tokens_used} tokens · ` +
      `$${trace.cost_usd ?? '?'} · stop ${trace.stop_cause}`,
  )

  writeArtifacts({ candidateId, tag, events, trace, execution, bundleJson, failure, evaluationRequestedBy })
  return 0
}

/**
 * Exercise the boundary with no model in the loop.
 *
 * The agent path and the sandbox path are separable on purpose: evidence that
 * the isolation boundary works should not depend on a model having behaved a
 * particular way that day. This run is deterministic given a committed
 * candidate, so it can be reproduced by anyone with a Vercel token.
 */
async function runSandboxOnly(file: string, cases: Case[]): Promise<number> {
  const source = readFileSync(file, 'utf8')
  const candidateId = 'keyed-fallback-v1'
  const tag = 'sandbox'
  console.log(`sandbox-only: ${file} (${source.length} bytes, sha256 ${sha256(source).slice(0, 16)})`)

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
  log(events, {
    type: 'scope-checked',
    allowed: true,
    detail: 'backend/lab/contract/candidate.py — within the allowed patch scope',
  })

  const attemptId = `${EXPERIMENT.experiment_id}__${candidateId}#01`
  log(events, { type: 'attempt-started', attempt_id: attemptId, runner: 'vercel-sandbox' })
  const outcome = await executeInSandbox(source, (s) => console.log(`  ${s}`))
  const e = outcome.execution

  console.log(`\nsandbox ${e.sandbox_id} · ${e.region} · exit ${e.exit_code}`)
  console.log(`boot ${e.boot_ms}ms · run ${e.wall_clock_ms}ms · egress ${e.egress_bytes ?? '?'} bytes (control plane included)`)
  console.log(`network policy the platform applied: ${e.network_policy}`)
  for (const probe of e.isolation) {
    console.log(`  ${probe.held ? 'held  ' : 'FAILED'} ${probe.name}: ${probe.observed.slice(0, 110)}`)
  }

  const isolated = e.isolation.every((p) => p.held)
  log(events, {
    type: 'attempt-ended',
    attempt_id: attemptId,
    status: outcome.failure === null && isolated ? 'succeeded' : 'failed',
    note: outcome.failure ?? `sandbox ${e.sandbox_id} in ${e.region}, exit ${e.exit_code} in ${e.wall_clock_ms}ms`,
  })

  if (!isolated) {
    // A microVM that did not isolate produces evidence about nothing.
    console.error('\nrefusing to record this run: an isolation probe did not hold')
    return 1
  }

  // A descriptor, because this candidate is deliberately not in
  // KNOWN_IMPLEMENTATIONS and the export must not invent what it is.
  writeFileSync(
    join(RUNS, `${candidateId}-${tag}.candidate.json`),
    `${JSON.stringify(
      {
        kind: 'human-authored',
        source_path: 'backend/lab/contract/candidates/keyed_fallback_v1.py',
        declared_protocol: 'keyed-v2',
        description:
          'Keyed association with a positional fallback: prefers article ids when the response carries them, and associates by position when it does not. Written for this experiment to be plausible rather than correct.',
        transcribed_from: 'unknown',
      },
      null,
      1,
    )}\n`,
  )

  const { stdout, stderr, records_json, candidate_sha256, ...evidence } = e
  void stdout
  void stderr
  void records_json
  void candidate_sha256
  writeFileSync(join(RUNS, `${candidateId}-${tag}.sandbox.json`), `${JSON.stringify(evidence, null, 1)}\n`)

  if (outcome.bundleJson !== null) {
    log(events, { type: 'records-received', attempt_id: attemptId, n_records: cases.length })
    writeFileSync(join(LAB, 'records', `${candidateId}.json`), outcome.bundleJson)
    const parsed = parseRecordBundle(JSON.parse(outcome.bundleJson))
    if (parsed.ok) {
      const result = evaluate(cases, parsed.value)
      console.log(`\nevaluator: ${result.verdict} — ${result.reason}`)
      for (const c of result.criteria) {
        console.log(`  ${c.passed ? 'pass' : 'FAIL'}  ${c.id.padEnd(28)} ${c.satisfied}/${c.applicable}`)
      }
      log(events, { type: 'evaluated', verdict: result.verdict, reason: result.reason })
    }
  }
  console.log(`\nwrote backend/lab/runs/${candidateId}-${tag}.*`)
  return 0
}

interface WriteArgs {
  candidateId: string
  tag: string
  events: string
  trace: InvestigationTrace
  execution: SandboxExecution | null
  bundleJson: string | null
  failure: string | null
  evaluationRequestedBy: 'agent' | 'harness' | null
}

function writeArtifacts(args: WriteArgs): void {
  const { candidateId, tag, trace, execution, bundleJson, evaluationRequestedBy } = args
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
  const sourcePath = `backend/lab/contract/candidates/${candidateId.replace(/-/g, '_')}.py`
  // Written for every run, proposal or not: a run that ended without one is a
  // result, and leaving it out of the committed set would count only the runs
  // that got far enough to be graded.
  writeFileSync(
    `${base}.investigation.json`,
    `${JSON.stringify(
      {
        model: trace.model,
        gateway: trace.gateway,
        gateway_auth: trace.gateway_auth,
        started_at: trace.started_at,
        wall_clock_ms: trace.wall_clock_ms,
        finish_reason: trace.finish_reason,
        stop_cause: trace.stop_cause,
        tool_calls_made: trace.tool_calls_made,
        max_tool_calls: trace.budget.max_tool_calls,
        model_calls_made: trace.model_calls_made,
        budget_label: trace.budget_label,
        budget: trace.budget,
        budget_ceiling_usd: trace.budget_ceiling_usd,
        usage: {
          input_tokens: trace.usage.input_tokens ?? 'unknown',
          output_tokens: trace.usage.output_tokens ?? 'unknown',
          total_tokens: trace.usage.total_tokens ?? 'unknown',
        },
        tokens_used: trace.tokens_used,
        cost_usd: trace.cost_usd ?? 'unknown',
        proposed: proposal !== null,
        evaluation_requested_by: evaluationRequestedBy ?? 'unknown',
        hypothesis: proposal?.hypothesis ?? 'unknown',
        evidence: proposal?.evidence ?? [],
        scope_accepted: proposal?.scope_accepted ?? false,
        scope_reason: proposal?.scope_reason ?? 'no proposal was made',
        trace_path: `backend/lab/runs/${candidateId}-${tag}.trace.json`,
        n_trace_steps: trace.steps.length,
      },
      null,
      1,
    )}\n`,
  )

  // The descriptor the export requires of any candidate that is not a known
  // implementation. The protocol is the one the records declare, read off the
  // bundle rather than asked of the model.
  let declared: string = 'unknown'
  if (bundleJson !== null) {
    const parsed = parseRecordBundle(JSON.parse(bundleJson))
    if (parsed.ok) declared = parsed.value.declared_protocol
  }
  writeFileSync(
    `${base}.candidate.json`,
    `${JSON.stringify(
      {
        kind: 'agent-authored',
        source_path: proposal !== null ? sourcePath : 'unknown',
        declared_protocol: declared,
        description: proposal?.hypothesis ?? 'The investigation ended without a proposal.',
        transcribed_from: 'unknown',
      },
      null,
      1,
    )}\n`,
  )

  if (proposal !== null) {
    // The candidate itself is committed so the patch on the page is the bytes
    // that ran, not a re-rendering of them.
    mkdirSync(join(LAB, 'contract', 'candidates'), { recursive: true })
    writeFileSync(join(ROOT, sourcePath), proposal.content)
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
  console.log(`spec ${specHash()}`)
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error(error instanceof Error ? error.stack : String(error))
    process.exit(1)
  })
