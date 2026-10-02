/**
 * Render the committed icon set from `app/icon.svg` and the sieve figure.
 *
 *   npm run build:icons
 *
 * Three outputs, all committed so no build step depends on a browser:
 *
 *   app/apple-icon.png      180x180, iOS home screen
 *   app/icon1.png           32x32, raster fallback for browsers that still
 *                           ignore an SVG favicon (Safari before 16.4)
 *   app/opengraph-image.png 1200x630, link previews
 *
 * The OG image is the sieve rather than the letterform. The tab icon had to
 * survive 16px and a grid of cells cannot; at 1200x630 the same figure is the
 * most characteristic thing the product has, so each mark is used where it
 * actually works.
 *
 * Playwright renders these rather than `next/og`, because Satori supports a
 * subset of CSS and the cell field is 1,362 positioned elements. A committed
 * PNG also means a link preview cannot be broken by a runtime failure on a
 * route nobody visits.
 */

import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright'

const WEB = join(fileURLToPath(new URL('.', import.meta.url)), '..')

/** The frozen run this figure describes. Kept in sync with the home page. */
const POOL = 1362
const DELIVERED = 50

/** Deterministic, so regenerating does not produce a spurious diff. */
function rng(seed: number): () => number {
  let s = seed >>> 0
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0
    return s / 0x100000000
  }
}

function ogHtml(): string {
  const fontPath = join(WEB, 'app/fonts/GeistSans-variable.woff2')
  const monoPath = join(WEB, 'app/fonts/GeistMono-latin.woff2')
  const total = POOL

  // Which cells survived. Spread rather than clustered: the real figure is a
  // corpus in recency order, not a blob.
  const next = rng(20260902)
  const lit = new Set<number>()
  while (lit.size < DELIVERED) lit.add(Math.floor(next() * total))

  const cells = Array.from({ length: total }, (_, i) =>
    `<i${lit.has(i) ? ' class="on"' : ''}></i>`,
  ).join('')

  return `<!doctype html><meta charset="utf-8">
<style>
  @font-face{font-family:F;src:url("file://${fontPath}") format("woff2");font-weight:100 900}
  @font-face{font-family:M;src:url("file://${monoPath}") format("woff2")}
  *{margin:0;box-sizing:border-box}
  body{width:1200px;height:630px;background:#fafaf9;color:#171717;padding:54px;display:grid;grid-template-columns:1fr 1fr;gap:48px;align-items:center;font-family:F;overflow:hidden}
  .copy{display:flex;flex-direction:column;gap:28px}
  .brand{font-size:26px;font-weight:600;letter-spacing:-1px}
  h1{font:600 74px/1.02 F;letter-spacing:-4px}
  p{font:400 22px/1.45 F;color:#626262;max-width:25ch}
  .instrument{background:#111315;border-radius:12px;padding:30px;color:#fafaf9}
  .label{font:400 13px M;color:#bfc3c6}
  .plate{display:grid;grid-template-columns:repeat(48,1fr);gap:3px;margin:32px 0}
  .plate i{aspect-ratio:1;background:#303436;border-radius:1px}
  .plate i.on{background:#fafaf9}
  .n{font:400 18px M;color:#a4a8aa}
  .n b{font:400 48px/1.1 M;color:#fafaf9;font-weight:400}
</style>
<div class="copy"><div class="brand">Daily Lab</div><h1>Does the fix<br>actually work?</h1><p>Run a parser in Vercel Sandbox. Inspect the verdict.</p></div>
<div class="instrument"><div class="label">RECORDED PIPELINE REPLAY</div><div class="plate">${cells}</div><div class="n"><b>${DELIVERED}</b> / ${POOL.toLocaleString()} delivered</div></div>`
}

async function main(): Promise<void> {
  const browser = await chromium.launch()
  const tmp = mkdtempSync(join(tmpdir(), 'daily-icons-'))
  try {
    // --- apple-icon + favicon, both from the committed icon.svg -------------
    const svg = readFileSync(join(WEB, 'app/icon.svg'), 'utf8')
    const svgPage = join(tmp, 'icon.html')
    writeFileSync(
      svgPage,
      `<!doctype html><meta charset="utf-8"><style>*{margin:0}
       svg{display:block;width:100vw;height:100vh}</style>${svg}`,
    )

    // A vector icon covers every current browser, and `icon1.png` is the
    // raster fallback for the ones that still ignore an SVG favicon. Next
    // emits both; numbered files are how it takes more than one.
    for (const [size, out] of [
      [180, join(WEB, 'app/apple-icon.png')],
      [32, join(WEB, 'app/icon1.png')],
    ] as const) {
      const ctx = await browser.newContext({ viewport: { width: size, height: size } })
      const page = await ctx.newPage()
      await page.goto(`file://${svgPage}`)
      await page.screenshot({ path: out })
      await ctx.close()
      console.log(`  ${String(size).padStart(4)}px -> ${out.replace(WEB, 'web')}`)
    }

    // --- opengraph image ----------------------------------------------------
    const ogPage = join(tmp, 'og.html')
    writeFileSync(ogPage, ogHtml())
    const ctx = await browser.newContext({ viewport: { width: 1200, height: 630 } })
    const page = await ctx.newPage()
    await page.goto(`file://${ogPage}`)
    await page.evaluate(() => document.fonts.ready)
    await page.screenshot({ path: join(WEB, 'app/opengraph-image.png') })
    await ctx.close()
    console.log('  1200x630 -> web/app/opengraph-image.png')
  } finally {
    await browser.close()
    rmSync(tmp, { recursive: true, force: true })
  }

  // Surface the sizes: an OG image over ~1MB is dropped by some scrapers.
  for (const f of ['app/apple-icon.png', 'app/icon1.png', 'app/opengraph-image.png']) {
    const bytes = readFileSync(join(WEB, f)).length
    console.log(`  ${f}  ${(bytes / 1024).toFixed(1)} kB`)
  }
}

main().catch((err: unknown) => {
  console.error(err)
  process.exitCode = 1
})
