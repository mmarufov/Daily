import localFont from 'next/font/local'

/**
 * The two shared faces are vendored under app/fonts/ rather than fetched from a font CDN at
 * build time. `next/font/google` needs network during `next build`; a committed
 * file does not, so the bytes that ship are the bytes in this tree and an
 * offline build still succeeds.
 *
 * Geist handles interface and prose, while Geist Mono handles figures, ids,
 * hashes and code. Fraunces belongs to the Reader's nested layout so other
 * routes do not preload a font they never use.
 */

export const geistSans = localFont({
  src: './fonts/GeistSans-variable.woff2',
  variable: '--font-sans-var',
  display: 'swap',
  weight: '100 900',
  fallback: [
    'ui-sans-serif',
    'system-ui',
    '-apple-system',
    'Segoe UI',
    'Helvetica Neue',
    'Arial',
    'sans-serif',
  ],
  adjustFontFallback: 'Arial',
})

export const geistMono = localFont({
  src: './fonts/GeistMono-latin.woff2',
  variable: '--font-mono-var',
  display: 'swap',
  weight: '100 900',
  fallback: ['ui-monospace', 'SFMono-Regular', 'SF Mono', 'Menlo', 'monospace'],
})
