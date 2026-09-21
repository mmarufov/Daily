import type { NextConfig } from 'next'

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

export default config
