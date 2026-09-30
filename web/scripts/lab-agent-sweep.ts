/**
 * Run the investigation several times per cell, and keep an honest ledger.
 *
 *   npx tsx --env-file=.env.agent.local scripts/lab-agent-sweep.ts \
 *     --model openai/gpt-4.1 --budget tight --reps 4 --prefix g41 --cap-usd 4.5
 *
 * Each run is `scripts/lab-agent-run.ts` in a child process with the cell's
 * configuration in its environment -- the same entry point `npm run lab:agent`
 * uses, so a swept run is not a different kind of run. The budget reaches it
 * as `LAB_BUDGET`, never by editing `BUDGET`.
 *
 * The ledger (`backend/lab/sweeps/<date>.jsonl`) records, around every run,
 * the gateway's own account balance: `getCredits()` before and after. That is
 * a second meter, independent of the per-call cost the trace sums, and the
 * reason it is here is that the two can be compared rather than one trusted.
 * The meter is account-wide, so runs are sequential; anything else spending
 * on the same account in the same minute would show up in the delta.
 *
 * `--cap-usd` is checked against the ledger's cumulative balance delta before
 * every run, across invocations, and the sweep stops rather than start a run
 * that could cross it.
 */

import { spawnSync } from 'node:child_process'
import { appendFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

import { gateway } from '@ai-sdk/gateway'

import { BUDGET, type BudgetOverride } from '../lib/lab/investigator'

/**
 * The budget cells.
 *
 * What varies is the exploration budget -- model calls, tool calls and the
 * token ceiling, scaled together, because those are what a retry loop would
 * convert into accept rate. What is held fixed, and why:
 *
 *   max_proposals          the property under test, not a knob
 *   max_output_tokens      per-call floor for emitting a whole parser file;
 *                          shrinking it measures "can it fit the file", a
 *                          different question from "how much may it look".
 *                          Raised, not lowered, in `generous-out` below.
 *   max_tool_result_chars  changes what one observation contains, not how
 *                          many observations there are
 *
 * `wall_clock_seconds` scales with the call count so it is never the binding
 * limit; `max_usd` is a declaration and is scaled with the token ceiling.
 */
const CELLS: Record<string, BudgetOverride | null> = {
  tight: {
    max_model_calls: 3,
    max_tool_calls: 6,
    max_total_tokens: 60_000,
    max_usd: 0.3,
  },
  default: null,
  generous: {
    max_model_calls: 12,
    max_tool_calls: 24,
    max_total_tokens: 300_000,
    max_usd: 1.5,
    wall_clock_seconds: 360,
  },
  // Added after the first generous run, whose last call hit the 4,096-token
  // output cap while writing the proposal (finish_reason `length`). That
  // made the per-call output cap a binding budget dimension after all, so it
  // gets its own cell rather than being folded into `generous`, which keeps
  // the definition the first run was made under.
  'generous-out': {
    max_model_calls: 12,
    max_tool_calls: 24,
    max_total_tokens: 300_000,
    max_output_tokens: 8_192,
    max_usd: 1.5,
    wall_clock_seconds: 360,
  },
}

function repoRoot(): string {
  let dir = process.cwd()
  for (let i = 0; i < 6; i += 1) {
    if (existsSync(join(dir, 'backend')) && existsSync(join(dir, 'web'))) return dir
    dir = dirname(dir)
  }
  throw new Error('could not locate the repository root')
}

const ROOT = repoRoot()

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`)
  return i === -1 ? undefined : process.argv[i + 1]
}

async function balance(): Promise<{ balance: number; used: number }> {
  const c = await gateway.getCredits()
  return { balance: Number(c.balance), used: Number(c.totalUsed) }
}

interface LedgerLine {
  candidate_id: string
  used_delta_usd: number | null
}

function cumulative(ledger: string): number {
  if (!existsSync(ledger)) return 0
  return readFileSync(ledger, 'utf8')
    .split('\n')
    .filter((l) => l.trim() !== '')
    .map((l) => JSON.parse(l) as LedgerLine)
    .reduce((a, l) => a + (l.used_delta_usd ?? 0), 0)
}

async function main(): Promise<number> {
  const model = arg('model')
  const cell = arg('budget') ?? 'default'
  const reps = Number(arg('reps') ?? '1')
  const prefix = arg('prefix')
  const start = Number(arg('start') ?? '1')
  const cap = Number(arg('cap-usd') ?? 'NaN')
  const perRunCeiling = Number(arg('per-run-usd') ?? '1')
  const date = arg('ledger-date') ?? new Date().toISOString().slice(0, 10)

  if (model === undefined || prefix === undefined || !(cell in CELLS) || !Number.isFinite(cap)) {
    console.error('usage: --model <gateway id> --budget tight|default|generous|generous-out --reps N --prefix <id> --cap-usd <dollars>')
    return 2
  }
  if (!/^[a-z0-9]{1,12}$/.test(prefix)) throw new Error('--prefix must match ^[a-z0-9]{1,12}$')

  const ledgerDir = join(ROOT, 'backend', 'lab', 'sweeps')
  mkdirSync(ledgerDir, { recursive: true })
  const ledger = join(ledgerDir, `${date}.jsonl`)
  const override = CELLS[cell] ?? null

  for (let n = start; n < start + reps; n += 1) {
    const spent = cumulative(ledger)
    if (spent + perRunCeiling > cap) {
      console.error(`stopping: $${spent.toFixed(4)} spent, a further run could cross the $${cap} cap`)
      return 3
    }
    const candidateId = `agent-${prefix}-${cell}-${String(n).padStart(2, '0')}`
    const before = await balance()
    const startedAt = new Date().toISOString()
    console.log(`\n=== ${candidateId} (${model}, ${cell}) · ledger total so far $${spent.toFixed(4)}`)
    const child = spawnSync('npx', ['tsx', 'scripts/lab-agent-run.ts'], {
      cwd: join(ROOT, 'web'),
      stdio: 'inherit',
      env: {
        ...process.env,
        LAB_MODEL: model,
        LAB_MAX_USD: String(perRunCeiling),
        LAB_CANDIDATE_ID: candidateId,
        ...(override === null ? {} : { LAB_BUDGET: JSON.stringify(override), LAB_BUDGET_LABEL: cell }),
      },
    })
    // The gateway settles asynchronously; give it a moment before reading.
    await new Promise((r) => setTimeout(r, 8_000))
    const after = await balance()
    const line = {
      candidate_id: candidateId,
      model,
      budget_label: cell,
      budget: override === null ? BUDGET : { ...BUDGET, ...override },
      started_at: startedAt,
      ended_at: new Date().toISOString(),
      exit_code: child.status,
      gateway_used_before_usd: before.used,
      gateway_used_after_usd: after.used,
      used_delta_usd: Number((after.used - before.used).toFixed(8)),
    }
    appendFileSync(ledger, `${JSON.stringify(line)}\n`)
    console.log(`ledger: ${candidateId} exit ${child.status}, gateway meter moved $${line.used_delta_usd}`)
  }
  return 0
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error(error instanceof Error ? error.stack : String(error))
    process.exit(1)
  })
