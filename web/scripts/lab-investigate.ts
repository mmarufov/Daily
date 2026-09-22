/**
 * Start one investigation on a deployment and bring its evidence home.
 *
 *   LAB_OWNER_TOKEN=… npm run lab:investigate -- --at https://daily-web-rose.vercel.app
 *
 * The paid loop runs *there*, because that is where `AI_GATEWAY_API_KEY`
 * lives and, by design, can never leave: Vercel sensitive variables are
 * write-only. The alternative -- pulling the key onto this machine to run the
 * loop locally -- would have been faster and is the exact move the access
 * model in `spec.ts` exists to rule out.
 *
 * What comes back is the evidence, which is then written into `backend/lab/`
 * in the same shape the Python orchestrator writes, so `export-lab.ts` picks
 * the run up with no special case and the artifact is a function of committed
 * bytes like every other.
 */

import { appendFileSync, existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

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

function arg(name: string, fallback?: string): string {
  const i = process.argv.indexOf(`--${name}`)
  const value = i === -1 ? undefined : process.argv[i + 1]
  if (value === undefined) {
    if (fallback !== undefined) return fallback
    throw new Error(`--${name} is required`)
  }
  return value
}

interface Outcome {
  kind: 'investigated' | 'refused'
  detail: string
  trace: {
    model: string
    gateway: string
    started_at: string
    wall_clock_ms: number
    finish_reason: string
    error?: string | null
    tool_calls_made: number
    budget: { max_tool_calls: number }
    budget_ceiling_usd: number
    budget_authorised_usd: number
    usage: { input_tokens: number | null; output_tokens: number | null; total_tokens: number | null }
    steps: unknown[]
    proposal: {
      candidate_id: string
      path: string
      content: string
      hypothesis: string
      evidence: string[]
      scope_accepted: boolean
      scope_reason: string
    } | null
  } | null
  sandbox: Record<string, unknown> | null
  records_json: string | null
  candidate_source: string | null
  verdict: string | null
  verdict_reason: string | null
  processes: { step: string; process_id: string; at: string }[]
  resumed: boolean
  executed_at_revision: string
  deployment: string
}

async function main(): Promise<number> {
  const base = arg('at', 'https://daily-web-rose.vercel.app').replace(/\/$/, '')
  const token = process.env.LAB_OWNER_TOKEN ?? ''
  const suspend = Number(arg('suspend', '0'))
  if (token === '') {
    console.error('LAB_OWNER_TOKEN is not set in this shell.')
    console.error('It is the bearer token the deployment checks; set the same value there.')
    return 2
  }

  console.log(`starting an investigation on ${base}`)
  const started = await fetch(`${base}/api/lab/investigate`, {
    method: 'POST',
    headers: { authorization: `Bearer ${token}`, 'content-type': 'application/json' },
    body: JSON.stringify({ candidate_id: 'agent-001', suspend_seconds: suspend }),
  })
  const startBody = (await started.json()) as { run_id?: string; error?: string; needs?: string[] }
  if (!started.ok || startBody.run_id === undefined) {
    console.error(`the deployment refused to start a run [${started.status}]: ${startBody.error}`)
    for (const need of startBody.needs ?? []) console.error(`  needs ${need}`)
    return 1
  }

  const runId = startBody.run_id
  console.log(`  run ${runId}; polling`)

  let outcome: Outcome | null = null
  const deadline = Date.now() + 15 * 60 * 1000
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 5_000))
    const res = await fetch(`${base}/api/lab/run/${runId}`)
    if (!res.ok) continue
    const body = (await res.json()) as { status: string; outcome: Outcome | null }
    process.stdout.write(`  ${body.status}\r`)
    if (body.status === 'running' || body.status === 'pending') continue
    if (body.status !== 'completed') {
      console.error(`\nthe run ended ${body.status} without an outcome`)
      return 1
    }
    outcome = body.outcome
    break
  }
  if (outcome === null) {
    console.error('\nthe run did not finish within 15 minutes')
    return 1
  }

  console.log(`\n${outcome.kind}: ${outcome.detail}`)
  console.log(`  deployment ${outcome.deployment} at ${outcome.executed_at_revision.slice(0, 12)}`)
  for (const p of outcome.processes) console.log(`  ${p.step.padEnd(9)} ${p.process_id}  ${p.at}`)
  console.log(`  resumed in a different process: ${outcome.resumed ? 'yes' : 'no'}`)

  const trace = outcome.trace
  if (trace === null) {
    console.error('\nno trace: the investigation refused before anything ran.')
    return 1
  }
  if (trace.error !== null && trace.error !== undefined) {
    // Worth saying loudly. The tool calls before the failure were charged,
    // and the trace is the only record that they happened.
    console.error(`\nthe call failed after ${trace.tool_calls_made} tool calls: ${trace.error.slice(0, 200)}`)
  }
  if (trace.proposal === null || outcome.candidate_source === null) {
    console.error('\nno proposal was produced, so there is no candidate to commit.')
    return 1
  }
  console.log(
    `\nmodel ${trace.model} · ${trace.tool_calls_made} tool calls · ` +
      `${trace.usage.total_tokens ?? '?'} tokens · finish ${trace.finish_reason}`,
  )
  console.log(`  scope gate: ${trace.proposal.scope_accepted ? 'accepted' : 'REFUSED'} — ${trace.proposal.scope_reason}`)
  console.log(`  verdict: ${outcome.verdict ?? 'none'} — ${outcome.verdict_reason ?? ''}`)

  writeEvidence(outcome, trace)
  return 0
}

function writeEvidence(outcome: Outcome, trace: NonNullable<Outcome['trace']>): void {
  const proposal = trace.proposal
  if (proposal === null) return
  const candidateId = 'agent-001'
  const tag = 'sandbox'
  const base = join(RUNS, `${candidateId}-${tag}`)
  mkdirSync(RUNS, { recursive: true })

  const events = `${base}.events.jsonl`
  writeFileSync(events, '')
  const log = (event: Record<string, unknown>, at: string): void =>
    appendFileSync(events, `${JSON.stringify({ ...event, at })}\n`)

  const investigatedAt = outcome.processes.find((p) => p.step === 'execute')?.at ?? trace.started_at
  const gradedAt = outcome.processes.find((p) => p.step === 'grade')?.at ?? investigatedAt
  const attemptId = `article-to-verdict-association__${candidateId}#01`
  const sandboxId = (outcome.sandbox?.sandbox_id as string | undefined) ?? 'unknown'

  log(
    {
      type: 'created',
      run_id: `article-to-verdict-association__${candidateId}`,
      candidate_id: candidateId,
      spec_hash: '',
      executed_at_revision: outcome.executed_at_revision,
    },
    trace.started_at,
  )
  log(
    { type: 'scope-checked', allowed: proposal.scope_accepted, detail: `${proposal.path} — ${proposal.scope_reason}` },
    trace.started_at,
  )
  log({ type: 'attempt-started', attempt_id: attemptId, runner: 'vercel-sandbox' }, trace.started_at)
  log(
    {
      type: 'attempt-ended',
      attempt_id: attemptId,
      status: outcome.records_json === null ? 'failed' : 'succeeded',
      note: `sandbox ${sandboxId} on deployment ${outcome.deployment}`,
    },
    investigatedAt,
  )
  if (outcome.records_json !== null) {
    log({ type: 'records-received', attempt_id: attemptId, n_records: 0 }, investigatedAt)
    log({ type: 'evaluated', verdict: outcome.verdict, reason: outcome.verdict_reason }, gradedAt)
  }

  // The trace, with the proposal's full source removed: it is committed as a
  // file of its own, and duplicating 5 kB of Python into the trace would make
  // the patch on the page and the patch in the trace two things that can
  // disagree.
  const { proposal: _omit, ...rest } = trace
  void _omit
  writeFileSync(
    `${base}.trace.json`,
    `${JSON.stringify({ ...rest, proposal: { ...proposal, content: `see ${proposal.path}` } }, null, 1)}\n`,
  )

  if (outcome.sandbox !== null) {
    writeFileSync(`${base}.sandbox.json`, `${JSON.stringify(outcome.sandbox, null, 1)}\n`)
  }

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

  writeFileSync(
    `${base}.candidate.json`,
    `${JSON.stringify(
      {
        kind: 'agent-authored',
        source_path: 'backend/lab/contract/candidates/agent_001.py',
        declared_protocol: 'keyed-v2',
        description: proposal.hypothesis,
        transcribed_from: 'unknown',
      },
      null,
      1,
    )}\n`,
  )

  mkdirSync(join(LAB, 'contract', 'candidates'), { recursive: true })
  writeFileSync(join(LAB, 'contract', 'candidates', 'agent_001.py'), outcome.candidate_source ?? '')
  if (outcome.records_json !== null) {
    writeFileSync(join(LAB, 'records', `${candidateId}.json`), outcome.records_json)
  }
  console.log(`\nwrote backend/lab/runs/${candidateId}-${tag}.* and the candidate source`)
  console.log('next: npm run export:lab && npm run test')
}

main()
  .then((c) => process.exit(c))
  .catch((e) => {
    console.error(e instanceof Error ? e.stack : String(e))
    process.exit(1)
  })
