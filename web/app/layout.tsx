import type { Metadata, Viewport } from 'next'
import Link from 'next/link'

import { SiteNav } from '@/components/SiteNav'

import { fraunces, geistMono } from './fonts'
import './globals.css'

export const metadata: Metadata = {
  title: {
    default: 'Daily — a newspaper and the ruler that measures it',
    template: '%s — Daily',
  },
  description:
    'A personalised daily edition, and the offline evaluation harness that says whether the feed actually got better. Every candidate article, every stage that dropped one, every caveat.',
}

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f4f2ec' },
    { media: '(prefers-color-scheme: dark)', color: '#0f0f10' },
  ],
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${fraunces.variable} ${geistMono.variable}`}>
      <body className="grain min-h-screen bg-paper text-ink antialiased">
        {/* A mark on the paper, not content: the measuring column and the
            grain are both drawn behind everything and read by nothing. */}
        <div className="column-rules" aria-hidden="true" />
        <a href="#main" className="skip-link">
          Skip to content
        </a>

        <header className="relative z-1 border-b border-rule bg-paper/85 backdrop-blur-[2px]">
          <div className="frame flex items-center justify-between gap-6 py-3.5">
            <Link
              href="/"
              className="brand-wordmark text-ink no-underline"
              aria-label="Daily, home"
            >
              Daily
            </Link>
            <SiteNav />
          </div>
        </header>

        <main id="main" className="relative z-1">{children}</main>

        <footer className="relative z-1 mt-24 border-t border-rule">
          <div className="frame flex flex-col gap-6 py-10 md:flex-row md:justify-between">
            <p className="m-0 max-w-xl text-xs text-ink-60">
              Never shipped, no readers. Every number here replays a dated, content-hashed
              corpus against ten adversarial fixtures — not users, and written to make the
              ranking fail.
            </p>
            <div className="flex shrink-0 flex-col gap-2 md:items-end">
              <a
                href="https://github.com/mmarufov/Daily"
                className="link label"
                rel="noreferrer"
              >
                Source on GitHub
              </a>
              <p className="m-0 text-xs text-ink-40">
                Read-only tier. Nothing here scores an article.
              </p>
            </div>
          </div>
        </footer>
      </body>
    </html>
  )
}
