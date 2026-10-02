import localFont from 'next/font/local'
import './reader.css'

const fraunces = localFont({
  src: '../fonts/Fraunces-latin.woff2',
  variable: '--font-editorial-var',
  display: 'swap',
  weight: '300 900',
  fallback: ['Charter', 'Georgia', 'Times New Roman', 'serif'],
  adjustFontFallback: 'Times New Roman',
})

export default function ReaderLayout({ children }: { children: React.ReactNode }) {
  return <div className={`${fraunces.variable} reader-layout`}>{children}</div>
}
