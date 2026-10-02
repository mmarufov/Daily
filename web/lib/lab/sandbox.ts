/**
 * Runs candidates in a network-denied microVM. Only the harness, cases, and candidate
 * are uploaded; the evaluator and labels stay outside. Isolation probes run in the same VM.
 */

import { randomUUID } from 'node:crypto'

import { Sandbox } from '@vercel/sandbox'

import { SANDBOX_LIMITS, SANDBOX_VCPUS, sha256 } from './runner'

const CANDIDATE_PATH = 'lab/candidate.py'

export interface SandboxCredentials {
  readonly token: string
  readonly teamId: string
  readonly projectId: string
}

/** The SDK uses OIDC on Vercel. Elsewhere, explicit authentication requires all three variables. */
export function sandboxCredentials(
  env: Readonly<Record<string, string | undefined>> = process.env,
): SandboxCredentials | { readonly missing: readonly string[] } {
  // The SDK reads deployment OIDC from request context. Vercel also injects
  // VERCEL_PROJECT_ID, so a partial explicit set must not override OIDC.
  if ((env.VERCEL_OIDC_TOKEN ?? '').trim() !== '' || env.VERCEL === '1') {
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

export interface SandboxExecution {
  readonly sandbox_id: string
  readonly runtime: string
  /** Policy read back from the platform after creation. */
  readonly network_policy: string
  /** Metered egress includes control-plane traffic. Use the isolation probes to check candidate networking. */
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
  readonly held: boolean
  readonly observed: string
}

/** Run after the candidate in the same microVM. A successful forbidden operation fails the probe. */
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
  readonly onProgress?: (step: string) => void
  /** Tags used to find the microVM by run. */
  readonly tags?: Readonly<Record<string, string>>
}

/** Sandbox failures propagate to the caller as incomplete runs. */
export async function runInSandbox(options: RunInSandboxOptions): Promise<SandboxExecution> {
  const { candidateSource, files, credentials, onProgress = () => {}, tags } = options
  const startedAt = Date.now()

  onProgress('creating microVM')
  const sandbox = await Sandbox.create({
    ...(credentials.token === '' ? {} : credentials),
    runtime: 'python3.13',
    timeout: SANDBOX_LIMITS.wall_clock_seconds * 1000,
    networkPolicy: 'deny-all',
    resources: { vcpus: SANDBOX_VCPUS },
    ...(tags === undefined ? {} : { tags: { ...tags } }),
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
    // The guest can read this framing marker. See unframe.
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

    // Read records from stdout. The candidate shares the harness process and can forge guest files.
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

    // Egress meters become final after the microVM stops.
    onProgress('stopping the microVM')
    await sandbox.stop()
    stopped = true

    return {
      // Platform ID for looking up this microVM in Vercel.
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

function describePolicy(policy: unknown): string {
  if (typeof policy === 'string') return policy
  if (policy === undefined || policy === null) return 'not reported by the platform'
  return JSON.stringify(policy).slice(0, 200)
}

/** Keep the operator-facing stdout readable by dropping the framed bundle. */
function stripFrames(stdout: string): string {
  return stdout.replace(/<<<LAB-RECORDS:[^>]*>>>[\s\S]*?<<<END:[^>]*>>>/g, '[record bundle removed]')
}

/**
 * Framing separates diagnostic output from records; the guest can read the marker.
 * The last frame wins so a preceding decoy cannot replace the harness output.
 */
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
