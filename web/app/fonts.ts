import localFont from 'next/font/local'

/**
 * Two faces, vendored under app/fonts/ rather than fetched from a font CDN at
 * build time. `next/font/google` needs network during `next build`; a committed
 * file does not, so the bytes that ship are the bytes in this tree and an
 * offline build still succeeds.
 *
 * The pairing is the site's argument in miniature. Daily is a newspaper
 * assembled by a measuring instrument, so prose is set in a high-contrast
 * editorial serif and every number, identifier, stage name and label is set in
 * a monospace. There is deliberately no sans in between: the two registers are
 * supposed to look like different kinds of object.
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

export const geistMono = localFont({
  src: './fonts/GeistMono-latin.woff2',
  variable: '--font-mono-var',
  display: 'swap',
  weight: '100 900',
  fallback: ['ui-monospace', 'SFMono-Regular', 'SF Mono', 'Menlo', 'monospace'],
})
