/**
 * Summarise every committed agent run: the run table, accept rate per cell,
 * and how often each trajectory predicate fired.
 *
 *   npx tsx scripts/lab-agent-report.ts          # markdown to stdout
 *   npx tsx scripts/lab-agent-report.ts --json   # the same, as JSON
 *
 * Reads only committed evidence: the exported run artifacts for the verdict,
 * `backend/lab/runs/*.investigation.json` for the cell and the spend, the
 * traces for the predicates, and the sweep ledgers for the gateway meter.
 * Computes nothing that is not a count over those files.
 */

import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { parseLabRun } from '../lib/lab/artifact'
import { RecordedTraceSchema, verifyTrajectory, type PredicateId } from '../lib/lab/trajectory'

function repoRoot(): string {
  let dir = process.cwd()
  for (let i = 0; i < 6; i += 1) {
    if (existsSync(join(dir, 'backend')) && existsSync(join(dir, 'web'))) return dir
    dir = dirname(dir)
  }
  throw new Error('could not locate the repository root')
}

const ROOT = repoRoot()
const RUNS = join(ROOT, 'backend', 'lab', 'runs')
const OUT = join(ROOT, 'web', 'public', 'lab-artifacts')

interface Row {
  id: string
  model: string
  cell: string
  verdict: string
  verdict_by_spec: Record<string, string>
  stop: string
  last_finish: string
  proposed: boolean
  evaluation_by: string
  tool_attempted: number
  tool_executed: number
  model_calls: number
  tokens: number
  cost_usd: number | null
  ledger_usd: number | null
  wall_s: number
  predicates: Record<PredicateId, string>
  refused: Record<PredicateId, string[]>
}

function ledger(): Map<string, number> {
  const dir = join(ROOT, 'backend', 'lab', 'sweeps')
  const out = new Map<string, number>()
  if (!existsSync(dir)) return out
  for (const f of readdirSync(dir).filter((x) => x.endsWith('.jsonl'))) {
    for (const line of readFileSync(join(dir, f), 'utf8').split('\n')) {
      if (line.trim() === '') continue
      const l = JSON.parse(line) as { candidate_id: string; used_delta_usd: number }
      out.set(l.candidate_id, l.used_delta_usd)
    }
  }
  return out
}

function main(): void {
  const meter = ledger()
  const rows: Row[] = []
  for (const f of readdirSync(RUNS).filter((x) => /^agent-.+-sandbox\.investigation\.json$/.test(x)).sort()) {
    const id = f.replace(/-sandbox\.investigation\.json$/, '')
    const inv = JSON.parse(readFileSync(join(RUNS, f), 'utf8'))
    const trace = RecordedTraceSchema.parse(JSON.parse(readFileSync(join(ROOT, inv.trace_path), 'utf8')))
    const art = parseLabRun(JSON.parse(readFileSync(join(OUT, `${id}-sandbox.json`), 'utf8')))
    if (!art.ok) throw new Error(`${id}: ${art.issues.join('; ')}`)
    const results = verifyTrajectory(trace)
    rows.push({
      id,
      model: inv.model,
      cell: inv.budget_label,
      verdict: art.value.verdict,
      verdict_by_spec: Object.fromEntries(art.value.gradings.map((g) => [String(g.spec_version), g.verdict])),
      stop: inv.stop_cause,
      last_finish: trace.model_steps.at(-1)?.finish_reason ?? 'none',
      proposed: inv.proposed,
      evaluation_by: inv.evaluation_requested_by,
      tool_attempted: trace.tool_calls_made,
      tool_executed: trace.steps.filter((s) => s.kind === 'tool-call').length,
      model_calls: trace.model_calls_made,
      tokens: trace.tokens_used,
      cost_usd: trace.cost_usd,
      ledger_usd: meter.get(id) ?? null,
      wall_s: Math.round(trace.wall_clock_ms / 100) / 10,
      predicates: Object.fromEntries(results.map((r) => [r.id, r.status])) as Record<PredicateId, string>,
      refused: Object.fromEntries(results.map((r) => [r.id, [...r.observations]])) as Record<PredicateId, string[]>,
    })
  }

  const cells = new Map<string, Row[]>()
  for (const r of rows) {
    const key = `${r.model} · ${r.cell}`
    cells.set(key, [...(cells.get(key) ?? []), r])
  }
  const predicateIds: PredicateId[] = ['read-before-propose', 'inside-scope-gate', 'inside-budget', 'proposed-once']
  const firing = Object.fromEntries(
    predicateIds.map((p) => {
      const applicable = rows.filter((r) => r.predicates[p] !== 'not-applicable')
      const fired = applicable.filter((r) => r.predicates[p] === 'fail')
      return [p, { fired: fired.length, of: applicable.length, ids: fired.map((r) => r.id) }]
    }),
  )
  const total = rows.reduce((a, r) => a + (r.cost_usd ?? 0), 0)
  const totalLedger = [...meter.values()].reduce((a, v) => a + v, 0)

  if (process.argv.includes('--json')) {
    console.log(JSON.stringify({ rows, firing, total_trace_usd: total, total_ledger_usd: totalLedger }, null, 1))
    return
  }

  console.log('| run | model | budget | verdict | stop (last finish) | proposed | tool calls exec/attempted | model calls | tokens | cost (trace) | cost (meter) | wall s |')
  console.log('|---|---|---|---|---|---|---|---|---|---|---|---|')
  for (const r of rows) {
    console.log(
      `| ${r.id} | ${r.model} | ${r.cell} | ${r.verdict} | ${r.stop} (${r.last_finish}) | ${r.proposed ? `yes (${r.evaluation_by})` : 'no'} | ${r.tool_executed}/${r.tool_attempted} | ${r.model_calls} | ${r.tokens} | ${r.cost_usd === null ? 'unknown' : `$${r.cost_usd.toFixed(4)}`} | ${r.ledger_usd === null ? 'n/a' : `$${r.ledger_usd.toFixed(4)}`} | ${r.wall_s} |`,
    )
  }
  console.log('\n| cell | accepted (k of n) | proposed | reached sandbox | stop causes |')
  console.log('|---|---|---|---|---|')
  for (const [key, rs] of cells) {
    const stops = Object.entries(rs.reduce<Record<string, number>>((a, r) => ({ ...a, [r.stop]: (a[r.stop] ?? 0) + 1 }), {}))
      .map(([k, v]) => `${k} ${v}`)
      .join(', ')
    console.log(
      `| ${key} | ${rs.filter((r) => r.verdict === 'accepted-for-review').length} of ${rs.length} | ${rs.filter((r) => r.proposed).length} of ${rs.length} | ${rs.filter((r) => r.verdict !== 'failed').length} of ${rs.length} | ${stops} |`,
    )
  }
  console.log('\n| predicate | fired (k of n applicable) | runs it fired on |')
  console.log('|---|---|---|')
  for (const p of predicateIds) {
    const f = firing[p] as { fired: number; of: number; ids: string[] }
    console.log(`| ${p} | ${f.fired} of ${f.of} | ${f.ids.join(', ') || 'none'} |`)
  }
  // Requests the harness turned away before they ran: not firings, counted apart.
  console.log('\n| predicate | runs with requests refused before running | what was refused |')
  console.log('|---|---|---|')
  for (const p of predicateIds) {
    const hit = rows.filter((r) => r.refused[p].length > 0)
    const what = hit.map((r) => `${r.id}: ${r.refused[p].join('; ')}`)
    console.log(`| ${p} | ${hit.length} of ${rows.length} | ${what.join('<br>') || 'none'} |`)
  }

  // A gateway call that failed after its retries is an infrastructure failure.
  // It stays in every table above as a failure; it is also listed here.
  const infra = rows.filter((r) => r.stop === 'call-error')
  console.log(`\ninfrastructure failures (gateway call failed after retries): ${infra.length} of ${rows.length}`)
  for (const r of infra) console.log(`- ${r.id} (${r.model}, ${r.cell}): ${r.model_calls} model call(s) completed first`)

  console.log(`\ntotal gateway cost summed from traces: $${total.toFixed(6)} over ${rows.length} runs`)
  console.log(`total gateway meter movement in the ledgers: $${totalLedger.toFixed(6)}`)
}

main()
