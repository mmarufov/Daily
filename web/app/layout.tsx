import type { Metadata, Viewport } from 'next'
import Link from 'next/link'

import { SiteNav } from '@/components/SiteNav'

import { fraunces, geistMono, geistSans } from './fonts'
import './globals.css'

/* A tab shows about 20 characters before it truncates, and a browser with
   six tabs open shows fewer. The social card has room the tab does not, so
   the long form lives there and nowhere else. */
const SHORT = 'Daily'
const SOCIAL = 'Daily, a newspaper and the ruler that measures it'
const DESCRIPTION =
  'A personalised daily edition, and the offline evaluation harness that says whether the feed actually got better. Every candidate article, every stage that dropped one, every caveat.'

export const metadata: Metadata = {
  // Without this, `og:image` is emitted as a relative path and most scrapers
  // drop it. Everything the site ships is served from the apex.
  metadataBase: new URL('https://marufov.com'),
  /* The template was '%s — Daily', which made every tab longer than it needed
     to be and turned the Lab's into "Daily Lab — Daily". A page title is
     already the page; the site name after it is for the benefit of nobody. */
  title: { default: SHORT, template: '%s' },
  description: DESCRIPTION,
  // `app/opengraph-image.png` supplies the image on its own; the title and
  // description do not come with it, and a card with no title falls back to
  // whatever the scraper scrapes.
  openGraph: {
    type: 'website',
    siteName: 'Daily',
    url: 'https://marufov.com',
    title: SOCIAL,
    description: DESCRIPTION,
  },
  twitter: {
    // The default is a small square thumbnail, which wastes a 1200x630 figure.
    card: 'summary_large_image',
    title: SOCIAL,
    description: DESCRIPTION,
  },
}

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f9f7f3' },
    { media: '(prefers-color-scheme: dark)', color: '#24211e' },
  ],
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${fraunces.variable} ${geistSans.variable} ${geistMono.variable}`}>
      <body className="grain min-h-screen bg-paper text-ink antialiased">
        <a href="#main" className="skip-link">
          Skip to content
        </a>

        <header className="relative z-1 border-b border-rule bg-paper/85 backdrop-blur-[2px]">
          <div className="frame flex items-center justify-between gap-4 py-3.5 sm:gap-6">
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
              corpus against ten adversarial fixtures, not users, written to make the
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
