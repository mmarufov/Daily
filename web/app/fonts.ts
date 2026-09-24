import localFont from 'next/font/local'

/**
 * Two faces, vendored under app/fonts/ rather than fetched from a font CDN at
 * build time. `next/font/google` needs network during `next build`; a committed
 * file does not, so the bytes that ship are the bytes in this tree and an
 * offline build still succeeds.
 *
 * Three faces, and the third one is a correction.
 *
 * The original pairing was serif for prose and monospace for *everything*
 * else, on the theory that a measuring instrument should look like one. In
 * practice monospace carried every label, note, caption and supporting
 * sentence on the site, and the result read as a terminal dump rather than a
 * product -- thin, uniform, and without any of the weight that makes an
 * interface feel built.
 *
 * The registers now have real jobs:
 *
 *   Fraunces    display and editorial prose -- the newspaper
 *   Geist       interface text, labels, navigation -- the product
 *   Geist Mono  data only: figures, ids, hashes, stage names -- the instrument
 *
 * Monospace kept for data is the part that was right: tabular figures in a
 * column of numbers are worth the register change. Monospace for a caption
 * never was.
 */

export const fraunces = localFont({
  src: './fonts/Fraunces-latin.woff2',
  variable: '--font-editorial-var',
  display: 'swap',
  weight: '300 900',
  // Georgia's cap height and x-height are close enough that the swap does not
  // reflow noticeably, which matters more than matching the skeleton.
  fallback: ['Charter', 'Georgia', 'Times New Roman', 'serif'],
  adjustFontFallback: 'Times New Roman',
})

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
