import type { Metadata, Viewport } from 'next'
import Link from 'next/link'
import { SiteNav } from '@/components/SiteNav'
import { geistMono, geistSans } from './fonts'
import './globals.css'
import './motion.css'
import './case-status.css'

const DESCRIPTION = 'Daily builds news editions around a reader\'s interests. Read a recorded edition, then explore Daily Lab to test the parsers inside its news pipeline.'

export const metadata: Metadata = {
  metadataBase: new URL('https://marufov.com'),
  title: { default: 'Daily', template: '%s' },
  description: DESCRIPTION,
  openGraph: {
    type: 'website', siteName: 'Daily', url: 'https://marufov.com',
    title: 'Daily makes news personal.', description: DESCRIPTION,
  },
  twitter: { card: 'summary_large_image', title: 'Daily makes news personal.', description: DESCRIPTION },
}

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#fafaf9' },
    { media: '(prefers-color-scheme: dark)', color: '#17191b' },
  ],
}

function Brand() {
  return <><span className="brand-symbol" aria-hidden="true"><i /><i /><i /><i /></span><span>Daily</span></>
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable}`}>
      <body className="min-h-screen bg-paper text-ink antialiased">
        <a href="#main" className="skip-link">Skip to content</a>
        <header className="site-header">
          <div className="frame site-header-inner">
            <Link href="/" className="site-brand" aria-label="Daily, home"><Brand /></Link>
            <SiteNav />
          </div>
        </header>
        <main id="main">{children}</main>
        <footer className="site-footer">
          <div className="frame site-footer-inner">
            <div>
              <Link href="/" className="site-brand"><Brand /></Link>
              <p>News editions shaped around a reader's interests.<br />Daily Lab tests the parsers behind the pipeline.</p>
            </div>
            <div className="footer-links">
              <Link href="/reader" prefetch={false}>Read an edition</Link>
              <Link href="/evidence">Evidence</Link>
              <a href="https://github.com/mmarufov/Daily" rel="noreferrer">Source <span aria-hidden="true">↗</span></a>
            </div>
          </div>
        </footer>
      </body>
    </html>
  )
}
