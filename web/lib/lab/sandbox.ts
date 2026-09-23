/**
 * Executing an untrusted candidate, for real.
 *
 * `runner.ts` decides *where* a candidate runs and fails closed; this is the
 * other half — what `vercel-sandbox` actually means. Until now it meant
 * nothing: every candidate in the repository is byte-identical to a committed
 * implementation, so `selectRunner` routed all seven runs to `local-known` and
 * the boundary was never crossed. A security boundary that has never rejected
 * anything is a comment.
 *
 * What is uploaded is the whole of what the candidate can see:
 *
 *   lab/__init__.py      empty
 *   lab/harness.py       the record producer, stdlib-only
 *   lab/cases/*.json     the frozen suite
 *   lab/candidate.py     the untrusted file
 *
 * No repository, no git history, no evaluator, no labels, no environment. The
 * candidate cannot read the thing that grades it because the thing that grades
 * it was never sent, which is a stronger statement than a permission check.
 *
 * `networkPolicy: 'deny-all'` is what makes `SANDBOX_LIMITS.network` true
 * rather than aspirational, and `assertIsolated` proves it per run instead of
 * trusting the flag — see the negative controls in `sandbox-probe.ts`.
 */

import { randomUUID } from 'node:crypto'

import { Sandbox } from '@vercel/sandbox'

import { SANDBOX_LIMITS, sha256 } from './runner'

/** Where the harness lives inside the microVM. */
const CANDIDATE_PATH = 'lab/candidate.py'

export interface SandboxCredentials {
  readonly token: string
  readonly teamId: string
  readonly projectId: string
}

/**
 * Credentials, or an explicit refusal naming what is missing.
 *
 * On a Vercel deployment the SDK authenticates via OIDC and needs none of
 * this; locally it needs all three. Returning the list of missing names
 * rather than a boolean is what lets `/lab` say which credential is absent
 * instead of "unavailable".
 */
export function sandboxCredentials(
  env: Readonly<Record<string, string | undefined>> = process.env,
): SandboxCredentials | { readonly missing: readonly string[] } {
  // OIDC first, and unconditionally.
  //
  // This used to accept OIDC only when all three explicit variables were
  // absent, reasoning that a partial set is a misconfiguration. On a Vercel
  // deployment that condition can never hold: the platform injects
  // `VERCEL_PROJECT_ID` itself, so exactly one of the three is always
  // present, the fallback was unreachable, and every sandboxed run on
  // production refused with `missing VERCEL_TOKEN, VERCEL_TEAM_ID` — on the
  // one host where OIDC is the intended mechanism.
  //
  // The rule it was reaching for is still worth keeping, and now sits where
  // it applies: with no OIDC token, a partial explicit set is a
  // misconfiguration rather than something to paper over.
  if ((env.VERCEL_OIDC_TOKEN ?? '').trim() !== '') {
    return { token: '', teamId: '', projectId: '' }
  }

  const wanted = ['VERCEL_TOKEN', 'VERCEL_TEAM_ID', 'VERCEL_PROJECT_ID'] as const
  const missing = wanted.filter((k) => (env[k] ?? '').trim() === '')
  if (missing.length > 0) return { missing }
  return {
    token: env.VERCEL_TOKEN as string,
    teamId: env.VERCEL_TEAM_ID as string,
    projectId: env.VERCEL_PROJECT_ID as string,
  }
}

export interface UploadedFile {
  readonly path: string
  readonly content: Buffer
}

/** What a sandboxed execution is willing to claim about itself. */
export interface SandboxExecution {
  readonly sandbox_id: string
  readonly runtime: string
  /**
   * Read back off the sandbox, not the value that was requested.
   *
   * Asking for `deny-all` and recording `deny-all` establishes only that the
   * request was made. This is what the platform says it applied.
   */
  readonly network_policy: string
  /**
   * Total bytes metered leaving the microVM.
   *
   * Read this as an upper bound, not as a measurement of what the candidate
   * sent. It includes the control-plane traffic this run itself caused --
   * chiefly the record bundle being read back -- so a non-zero value is
   * expected and says nothing on its own. The direct evidence that the
   * candidate reached no network is `isolation`, below.
   */
  readonly egress_bytes: number | null
  readonly active_cpu_ms: number | null
  readonly region: string
  readonly exit_code: number
  readonly wall_clock_ms: number
  readonly boot_ms: number
  readonly candidate_sha256: string
  readonly uploaded: readonly { path: string; sha256: string; bytes: number }[]
  readonly stdout: string
  readonly stderr: string
  /** The bundle the harness wrote, unparsed. Null when it wrote none. */
  readonly records_json: string | null
  /** Results of the isolation probes run inside this same microVM. */
  readonly isolation: readonly IsolationProbe[]
}

export interface IsolationProbe {
  readonly name: string
  readonly command: string
  readonly expectation: string
  /** True when the sandbox behaved as the limits claim it does. */
  readonly held: boolean
  readonly observed: string
}

/**
 * Probes that must fail for the boundary to mean anything.
 *
 * Run inside the same microVM as the candidate, in the same session, after it
 * — so what they establish is a property of the environment the candidate
 * actually had, not of a separate one configured the same way. A probe that
 * *succeeds* is a failed probe.
 */
const PROBES: readonly {
  name: string
  argv: readonly string[]
  expectation: string
  held: (exit: number, out: string) => boolean
}[] = [
  {
    name: 'egress-dns',
    argv: ['python3', '-c', 'import socket;socket.setdefaulttimeout(8);socket.gethostbyname("api.openai.com")'],
    expectation: 'DNS resolution of an external host fails',
    held: (exit) => exit !== 0,
  },
  {
    name: 'egress-https',
    argv: [
      'python3',
      '-c',
      'import urllib.request;urllib.request.urlopen("https://api.github.com/meta",timeout=8).read(16)',
    ],
    expectation: 'an outbound HTTPS request fails',
    held: (exit) => exit !== 0,
  },
  {
    name: 'no-evaluator-present',
    argv: ['sh', '-c', 'ls -R / 2>/dev/null | grep -c "evaluator.ts" || true'],
    expectation: 'the code that grades the candidate is nowhere on the filesystem',
    held: (_exit, out) => out.trim() === '0',
  },
  {
    name: 'no-secrets-in-env',
    argv: [
      'sh',
      '-c',
      'env | grep -ciE "^(VERCEL_TOKEN|AI_GATEWAY|OPENAI|BLOB_READ_WRITE|DATABASE|ANTHROPIC)" || true',
    ],
    expectation: 'no production credential is present in the environment',
    held: (_exit, out) => out.trim() === '0',
  },
]

export interface RunInSandboxOptions {
  readonly candidateSource: string
  readonly files: readonly UploadedFile[]
  readonly credentials: SandboxCredentials
  /** Called with progress so a long run is not a silent one. */
  readonly onProgress?: (step: string) => void
}

/**
 * Run one candidate over the case suite inside an isolated microVM.
 *
 * Throws rather than degrading. If the sandbox cannot run, the correct
 * outcome is an `incomplete` run recorded as such — never a local execution,
 * and never a fabricated record set.
 */
export async function runInSandbox(options: RunInSandboxOptions): Promise<SandboxExecution> {
  const { candidateSource, files, credentials, onProgress = () => {} } = options
  const startedAt = Date.now()

  onProgress('creating microVM')
  const sandbox = await Sandbox.create({
    ...(credentials.token === '' ? {} : credentials),
    runtime: 'python3.13',
    timeout: SANDBOX_LIMITS.wall_clock_seconds * 1000,
    networkPolicy: 'deny-all',
    resources: { vcpus: 2 },
  })
  const bootMs = Date.now() - startedAt
  let stopped = false

  try {
    const payload = [
      ...files,
      { path: CANDIDATE_PATH, content: Buffer.from(candidateSource, 'utf8') },
    ]
    onProgress(`uploading ${payload.length} files`)
    await sandbox.writeFiles(payload.map((f) => ({ path: f.path, content: f.content })))

    onProgress('running the harness')
    const ranAt = Date.now()
    // A frame marker, not a secret. See `unframe` below.
    const frame = randomUUID()
    const result = await sandbox.runCommand('python3', [
      '-m',
      'lab.harness',
      '--candidate',
      CANDIDATE_PATH,
      '--cases',
      'lab/cases/observed.json',
      'lab/cases/synthetic.json',
      '--stdout',
      '--frame',
      frame,
    ])
    const wallClockMs = Date.now() - ranAt

    const [stdout, stderr] = await Promise.all([result.stdout(), result.stderr()])

    // The records come off stdout, never off the guest filesystem.
    //
    // This used to read `records.json` back out of the microVM. An audit
    // showed what that allowed: the harness imports the candidate into its
    // own process, so module-level candidate code could read `--out` from
    // argv, write a bundle of its own and exit 0 — `parse()` never ran, and
    // the forged file was what got graded. Nothing the guest writes to disk
    // is read any more, and `--out` no longer exists on this path.
    const recordsJson = result.exitCode === 0 ? unframe(stdout, frame) : null

    onProgress('probing isolation')
    const isolation: IsolationProbe[] = []
    for (const probe of PROBES) {
      const [cmd, ...args] = probe.argv
      const probeResult = await sandbox.runCommand(cmd as string, args)
      const out = `${await probeResult.stdout()}${await probeResult.stderr()}`.trim()
      isolation.push({
        name: probe.name,
        command: probe.argv.join(' '),
        expectation: probe.expectation,
        held: probe.held(probeResult.exitCode, out),
        observed: `exit ${probeResult.exitCode}${out === '' ? '' : `: ${out.slice(0, 300)}`}`,
      })
    }

    // Stop first, then read the meters. `totalEgressBytes` is not final while
    // the microVM is alive -- reading it before the stop returns `undefined`,
    // which would record the strongest available evidence of isolation as
    // `unknown`.
    onProgress('stopping the microVM')
    await sandbox.stop()
    stopped = true

    return {
      // `name` is the platform's identifier for this microVM. It is recorded
      // so the claim "this ran in a sandbox" is checkable against the Vercel
      // dashboard rather than taken on faith.
      sandbox_id: sandbox.name,
      runtime: sandbox.runtime ?? 'python3.13',
      network_policy: describePolicy(sandbox.networkPolicy),
      egress_bytes: sandbox.totalEgressBytes ?? null,
      active_cpu_ms: sandbox.totalActiveCpuDurationMs ?? null,
      region: sandbox.region,
      exit_code: result.exitCode,
      wall_clock_ms: wallClockMs,
      boot_ms: bootMs,
      candidate_sha256: sha256(candidateSource),
      uploaded: payload.map((f) => ({
        path: f.path,
        sha256: sha256(f.content.toString('utf8')),
        bytes: f.content.byteLength,
      })),
      stdout: stripFrames(stdout).slice(0, 8_000),
      stderr: stderr.slice(0, 8_000),
      records_json: recordsJson,
      isolation,
    }
  } finally {
    if (!stopped) {
      onProgress('stopping the microVM after a failure')
      await sandbox.stop().catch(() => {})
    }
  }
}

/** The applied policy as a short string, whatever shape it came back in. */
function describePolicy(policy: unknown): string {
  if (typeof policy === 'string') return policy
  if (policy === undefined || policy === null) return 'not reported by the platform'
  return JSON.stringify(policy).slice(0, 200)
}

/**
 * Take the bundle out of a stdout stream a candidate is free to print into.
 *
 * The marker is a per-run UUID and is deliberately *not* a security boundary
 * — the guest can read it from argv, and a candidate that forges a correctly
 * framed bundle has done exactly what a lying `parse()` does. It is defeated
 * by the same thing: `upload-set.ts` ships no expectations, so nothing inside
 * the microVM knows which answers would pass. What framing buys is that an
 * honest candidate printing diagnostics cannot corrupt an honest run.
 *
 * The *last* frame wins. A candidate that prints a decoy frame before the
 * harness emits the real one should not get the decoy graded.
 */
/** Keep the operator-facing stdout readable by dropping the framed bundle. */
function stripFrames(stdout: string): string {
  return stdout.replace(/<<<LAB-RECORDS:[^>]*>>>[\s\S]*?<<<END:[^>]*>>>/g, '[record bundle removed]')
}

export function unframe(stdout: string, frame: string): string | null {
  const open = `<<<LAB-RECORDS:${frame}>>>\n`
  const close = `<<<END:${frame}>>>`
  const start = stdout.lastIndexOf(open)
  if (start === -1) return null
  const from = start + open.length
  const end = stdout.indexOf(close, from)
  if (end === -1) return null
  const body = stdout.slice(from, end)
  return body.trim() === '' ? null : body
}
