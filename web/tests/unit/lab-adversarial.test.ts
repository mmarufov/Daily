import { spawnSync } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { gradeStep } from '@/lib/lab/orchestration'
import { unframe } from '@/lib/lab/sandbox'
import { projectForGuest, uploadSet } from '@/lib/lab/upload-set'

/**
 * The attacks an external audit demonstrated, kept as tests.
 *
 * Each of these reached `accepted-for-review` over the real suite at the time
 * it was written. They are here rather than in a report because a fixed
 * vulnerability with no test is a vulnerability waiting for a refactor, and
 * because "we had it attacked and here is what survived" is worth more than
 * a green badge.
 */

const LAB = join(process.cwd(), '..', 'backend', 'lab')
const PYTHON = join(process.cwd(), '..', 'backend', 'venv', 'bin', 'python')
const havePython = existsSync(PYTHON)

describe('a candidate cannot hand the grader evidence it wrote itself', () => {
  it.runIf(havePython)('sees no argv, so it cannot find the output path', () => {
    // The original: read `--out` from sys.argv, write a forged bundle there,
    // os._exit(0). parse() never ran and the forged file was graded.
    const attack = join('/tmp', 'lab-attack-argv.py')
    writeFileSync(
      attack,
      [
        'import sys',
        'sys.stderr.write("ARGV=%r\\n" % (sys.argv,))',
        'def parse(articles, response):',
        '    return {"ok": False, "refusal": {"kind": "unsupported_protocol", "detail": ""}}',
      ].join('\n'),
    )
    const run = spawnSync(
      PYTHON,
      ['-m', 'lab.harness', '--candidate', attack, '--cases', 'lab/cases/synthetic.json', '--stdout', '--frame', 'SECRET-FRAME'],
      { cwd: join(process.cwd(), '..', 'backend'), encoding: 'utf8' },
    )
    expect(run.status).toBe(0)
    // What the candidate could see of the invocation that is grading it.
    expect(run.stderr).toContain("ARGV=['lab-candidate']")
    expect(run.stderr).not.toContain('--out')
    expect(run.stderr).not.toContain('SECRET-FRAME')
    // And the harness still produced a real, framed bundle.
    expect(unframe(run.stdout, 'SECRET-FRAME')).not.toBeNull()
  })

  it('takes records from framed stdout, never from a guest file', () => {
    const source = require('node:fs').readFileSync(join(process.cwd(), 'lib', 'lab', 'sandbox.ts'), 'utf8') as string
    const code = source.split('\n').filter((l) => !/^\s*(\*|\/\/|\/\*)/.test(l)).join('\n')
    // `readFile` off the sandbox is how the forged bundle used to arrive.
    expect(code).not.toMatch(/sandbox\.readFile/)
    expect(code).not.toContain("'--out'")
  })

  it('prefers the last frame, so a decoy printed first is not graded', () => {
    const decoyed =
      '<<<LAB-RECORDS:f>>>\n{"forged":true}\n<<<END:f>>>\n<<<LAB-RECORDS:f>>>\n{"real":true}\n<<<END:f>>>\n'
    expect(unframe(decoyed, 'f')).toContain('"real"')
    expect(unframe(decoyed, 'f')).not.toContain('forged')
  })

  it('treats an absent, mismatched or empty frame as no evidence', () => {
    expect(unframe('candidate printed nothing', 'f')).toBeNull()
    expect(unframe('<<<LAB-RECORDS:other>>>\n{}\n<<<END:other>>>', 'f')).toBeNull()
    expect(unframe('<<<LAB-RECORDS:f>>>\n\n<<<END:f>>>', 'f')).toBeNull()
  })
})

describe('the guest is never told the answers', () => {
  it('ships cases projected onto exactly what the harness reads', async () => {
    for (const file of await uploadSet(LAB)) {
      if (!file.path.endsWith('.json')) continue
      const suite = JSON.parse(file.content.toString('utf8')) as { cases: Record<string, unknown>[] }
      expect(suite.cases.length).toBeGreaterThan(0)
      for (const kase of suite.cases) {
        // A projection, not a deletion: an allowlist has to recognise three
        // names, a denylist has to anticipate every future field that might
        // carry ground truth.
        expect(Object.keys(kase).sort()).toEqual(['articles', 'case_id', 'response'])
      }
    }
  })

  it('drops expectation even when the source case carries one', () => {
    const withAnswers = {
      cases: [
        {
          case_id: 'syn-keyed-in-order',
          articles: [{ id: 'a1', title: 't' }],
          response: { content: '{}' },
          expectation: { association: { a1: { relevant: true, score: 0.8 } }, refusal_kinds: [] },
          group: 'synthetic',
          family: 'protocol-association',
        },
      ],
    }
    const projected = projectForGuest(withAnswers)
    expect(JSON.stringify(projected)).not.toContain('expectation')
    expect(JSON.stringify(projected)).not.toContain('refusal_kinds')
    expect(JSON.stringify(projected)).not.toContain('relevant')
  })

  it('leaves no ground-truth key anywhere in the shipped payload', async () => {
    const files = await uploadSet(LAB)
    for (const file of files.filter((f) => f.path.endsWith('.json'))) {
      const seen = new Set<string>()
      const walk = (v: unknown, depth = 0): void => {
        if (depth > 8 || v === null || typeof v !== 'object') return
        if (Array.isArray(v)) return void v.forEach((x) => walk(x, depth + 1))
        for (const [k, val] of Object.entries(v)) {
          seen.add(k)
          walk(val, depth + 1)
        }
      }
      walk(JSON.parse(file.content.toString('utf8')))
      expect([...seen].filter((k) => /expect|refusal|association|ground_truth/i.test(k))).toEqual([])
    }
  })
})

describe('a failure never resolves to acceptance', () => {
  const records = require('node:fs').readFileSync(join(LAB, 'records', 'keyed-v2.json'), 'utf8') as string

  it('refuses to grade records when the step that produced them failed', async () => {
    // The original: gradeStep consulted `failure` only when records were
    // null, so a gateway call that timed out *after* the sandbox had run came
    // back kind:refused with verdict:accepted-for-review.
    const clean = await gradeStep(records, null)
    expect(clean.verdict).toBe('accepted-for-review')

    const failed = await gradeStep(records, 'the gateway call timed out after 3 tool calls')
    expect(failed.verdict).not.toBe('accepted-for-review')
    expect(failed.reason).toContain('timed out')
  })

  it('checks isolation before it keeps the records, not after', () => {
    const source = require('node:fs').readFileSync(
      join(process.cwd(), 'lib', 'lab', 'orchestration.ts'),
      'utf8',
    ) as string
    const code = source.split('\n').filter((l) => !/^\s*(\*|\/\/|\/\*)/.test(l)).join('\n')
    // `recordsJson` is a closure variable the caller reads after the tool
    // returns, so assigning it before the probe check left a breached run's
    // output in place — the early return exits the tool, not the step.
    const assign = code.indexOf('recordsJson = records')
    const check = code.indexOf('const breached = execution.isolation')
    expect(check).toBeGreaterThan(-1)
    expect(check).toBeLessThan(assign)
    expect(code).toContain('recordsJson = null')
  })

  it('consults the failure before it consults the records', () => {
    const source = require('node:fs').readFileSync(
      join(process.cwd(), 'lib', 'lab', 'orchestration.ts'),
      'utf8',
    ) as string
    const step = source.slice(source.indexOf('export async function gradeStep'))
    expect(step.indexOf('if (failure !== null)')).toBeLessThan(step.indexOf('if (recordsJson === null)'))
  })
})
