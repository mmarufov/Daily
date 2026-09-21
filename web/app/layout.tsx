import type { Metadata, Viewport } from 'next'
import Link from 'next/link'

import './globals.css'

export const metadata: Metadata = {
  title: {
    default: 'Daily — news that knows you',
    template: '%s — Daily',
  },
  description:
    'A personalized daily edition, and an evaluation harness that measures whether the feed actually got better.',
}

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#fcfaf7' },
    { media: '(prefers-color-scheme: dark)', color: '#15120e' },
  ],
}

const NAV = [
  { href: '/reader', label: 'Reader' },
  { href: '/evidence', label: 'Evidence' },
  { href: '/engineering', label: 'Engineering' },
] as const

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-paper text-ink">
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        <header className="border-b border-sepia">
          <div className="mx-auto flex max-w-5xl items-baseline justify-between gap-6 px-5 py-5">
            <Link href="/" className="brand-wordmark text-ink-blue no-underline">
              Daily
            </Link>
            <nav aria-label="Sections">
              <ul className="flex list-none gap-5 p-0">
                {NAV.map((item) => (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      className="meta-caps text-ink-60 no-underline hover:text-ink"
                    >
                      {item.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          </div>
        </header>

        <main id="main" className="mx-auto max-w-5xl px-5 py-8">
          {children}
        </main>

        <footer className="mt-16 border-t border-sepia">
          <div className="mx-auto max-w-5xl px-5 py-6">
            <p className="m-0 text-sm text-ink-60">
              Daily is an unreleased personal project. The reader demo replays a dated frozen
              corpus; the ten reader profiles in the evaluation explorer are adversarial test
              fixtures, not users.{' '}
              <a
                href="https://github.com/mmarufov/Daily"
                className="text-ink-blue underline"
                rel="noreferrer"
              >
                Source on GitHub
              </a>
              .
            </p>
          </div>
        </footer>
      </body>
    </html>
  )
}
