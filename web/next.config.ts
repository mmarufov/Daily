import type { NextConfig } from 'next'
import { withWorkflow } from 'workflow/next'

const config: NextConfig = {
  reactStrictMode: true,
  typedRoutes: true,
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
