import type { Metadata, Viewport } from 'next'
import Link from 'next/link'
import { SiteNav } from '@/components/SiteNav'
import { fraunces, geistMono, geistSans } from './fonts'
import './globals.css'

const DESCRIPTION = 'Run untrusted Python parsers in Vercel Sandbox against recorded and injected failures. Inspect independently graded results, versioned criteria, and the evidence behind every verdict.'

export const metadata: Metadata = {
  metadataBase: new URL('https://marufov.com'),
  title: { default: 'Daily Lab', template: '%s' },
  description: DESCRIPTION,
  openGraph: {
    type: 'website', siteName: 'Daily Lab', url: 'https://marufov.com',
    title: 'Daily Lab · Does the fix actually work?', description: DESCRIPTION,
  },
  twitter: { card: 'summary_large_image', title: 'Daily Lab · Does the fix actually work?', description: DESCRIPTION },
}

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#fafaf9' },
    { media: '(prefers-color-scheme: dark)', color: '#17191b' },
  ],
}

function Brand() {
  return <><span className="brand-symbol" aria-hidden="true"><i /><i /><i /><i /></span><span>Daily Lab</span></>
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${fraunces.variable} ${geistSans.variable} ${geistMono.variable}`}>
      <body className="min-h-screen bg-paper text-ink antialiased">
        <a href="#main" className="skip-link">Skip to content</a>
        <header className="site-header">
          <div className="frame site-header-inner">
            <Link href="/" className="site-brand" aria-label="Daily Lab, home"><Brand /></Link>
            <SiteNav />
          </div>
        </header>
        <main id="main">{children}</main>
        <footer className="site-footer">
          <div className="frame site-footer-inner">
            <div>
              <Link href="/" className="site-brand"><Brand /></Link>
              <p>A working instrument for an unfinished news pipeline.<br />Recorded inputs. Live parser execution. Independent verdicts.</p>
            </div>
            <div className="footer-links">
              <Link href="/reader">Sample newspaper</Link>
              <Link href="/evidence">Evidence</Link>
              <a href="https://github.com/mmarufov/Daily" rel="noreferrer">Source <span aria-hidden="true">↗</span></a>
            </div>
          </div>
        </footer>
      </body>
    </html>
  )
}
