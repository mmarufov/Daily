import type { NextConfig } from 'next'
import { withWorkflow } from 'workflow/next'

/**
 * The evidence a Lab function reads at runtime.
 *
 * File tracing follows imports, and these are opened by path rather than
 * imported, so nothing pulls them into the bundle on its own. They also live
 * outside `web/`, which is the Root Directory -- so the default tracing root
 * cannot even see them.
 *
 * This was found the way these always are: every local check passed, and the
 * deployed route answered `ENOENT`. The case suite is the experiment's
 * evidence; a function that cannot read it cannot start a run.
 */
const LAB_EVIDENCE = ['lab-evidence/**']

const config: NextConfig = {
  reactStrictMode: true,
  typedRoutes: true,
  outputFileTracingIncludes: {
    // The API routes that start a run, and the workflow step route where the
    // sandbox upload and the agent's source reads actually happen.
    '/api/lab/run': LAB_EVIDENCE,
    '/api/lab/run/[runId]': LAB_EVIDENCE,
    '/api/lab/investigate': LAB_EVIDENCE,
    '/.well-known/workflow/v1/flow': LAB_EVIDENCE,
    '/.well-known/workflow/v1/step': LAB_EVIDENCE,
  },
  // The evidence explorer renders only committed/exported artifacts, so it is
  // safe to cache publicly. Reader responses are per-user and must never be
  // shared; those routes set their own no-store headers at the handler.
  async headers() {
    return [
      {
        source: '/artifacts/:path*',
        headers: [
          { key: 'Cache-Control', value: 'public, max-age=31536000, immutable' },
        ],
      },
    ]
  },
}

/**
 * Durability is the platform's, not a loop in this repository.
 *
 * `withWorkflow` compiles the `"use workflow"` and `"use step"` directives in
 * `lib/lab/orchestration.ts` into journaled functions. What that buys is the
 * one property the local Python orchestrator could only approximate: when the
 * process dies mid-run, the run is resumed from its journal by something that
 * did not die with it.
 */
export default withWorkflow(config)
