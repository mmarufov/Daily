import type { Metadata, Viewport } from 'next'
import Link from 'next/link'

import { Mark } from '@/components/Mark'
import { SiteNav } from '@/components/SiteNav'
import { NAV } from '@/lib/nav'

import { fraunces, geistMono, geistSans } from './fonts'
import './globals.css'

/* A tab shows about 20 characters before it truncates. The long form lives
   on the social card and nowhere else. */
const SHORT = 'Daily Lab'
const SOCIAL = 'Daily Lab: does the fix fix anything?'
const DESCRIPTION =
  'An evaluation harness on Vercel. It runs a proposed fix in a Sandbox microVM against recorded and fault-injected cases, grades it with criteria hashed before it ran, and publishes where it fails.'

export const metadata: Metadata = {
  // Without this, `og:image` is emitted as a relative path and most scrapers
  // drop it.
  metadataBase: new URL('https://marufov.com'),
  title: { default: SHORT, template: '%s' },
  description: DESCRIPTION,
  openGraph: {
    type: 'website',
    siteName: 'Daily Lab',
    url: 'https://marufov.com',
    title: SOCIAL,
    description: DESCRIPTION,
  },
  twitter: {
    card: 'summary_large_image',
    title: SOCIAL,
    description: DESCRIPTION,
  },
}

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#fafafa' },
    { media: '(prefers-color-scheme: dark)', color: '#0a0a0a' },
  ],
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${fraunces.variable} ${geistSans.variable} ${geistMono.variable}`}>
      <body className="min-h-screen bg-paper text-ink antialiased">
        <a href="#main" className="skip-link">
          Skip to content
        </a>

        <header className="sticky top-0 z-40 border-b border-rule bg-paper">
          <div className="frame flex h-14 items-center justify-between gap-4">
            <Link
              href="/"
              className="flex shrink-0 items-center gap-2.5 text-ink no-underline"
              aria-label="Daily Lab, home"
            >
              <Mark />
              <span className="brand-wordmark max-[26rem]:sr-only">Daily Lab</span>
            </Link>
            <SiteNav />
          </div>
        </header>

        <main id="main">{children}</main>

        <footer className="mt-32 border-t border-rule">
          <div className="frame grid gap-10 py-14 md:grid-cols-[minmax(0,1fr)_auto]">
            <div className="flex max-w-xl flex-col gap-4">
              <Link href="/" className="flex items-center gap-2.5 text-ink no-underline">
                <Mark />
                <span className="brand-wordmark">Daily Lab</span>
              </Link>
              <p className="m-0 text-sm text-ink-60">
                Never shipped, no readers. Every number here replays a dated, content-hashed
                corpus against ten adversarial fixtures, not users, written to make the ranking
                fail.
              </p>
              <p className="m-0 text-sm text-ink-40">
                Relevance labels are written by a model. None has been reviewed by a person, so
                absolute values are provisional. No confidence intervals were computed.
              </p>
            </div>
            <nav aria-label="Footer" className="flex flex-col gap-2 text-sm md:items-end">
              {NAV.map((item) => (
                <Link key={item.href} href={item.href} className="text-ink-60 no-underline hover:text-ink">
                  {item.label}
                </Link>
              ))}
              <a href="https://github.com/mmarufov/Daily" rel="noreferrer" className="text-ink-60 no-underline hover:text-ink">
                Source on GitHub
              </a>
            </nav>
          </div>
        </footer>
      </body>
    </html>
  )
}
