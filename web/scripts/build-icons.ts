/**
 * Render the committed icon set from `app/icon.svg` and the Daily/Lab story.
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
 * The social card introduces Daily and its Lab using the recorded offending
 * batch. A committed PNG keeps crawlers independent of runtime rendering.
 */

import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright'

const WEB = join(fileURLToPath(new URL('.', import.meta.url)), '..')

function ogHtml(): string {
  const fontPath = join(WEB, 'app/fonts/GeistSans-variable.woff2')
  const monoPath = join(WEB, 'app/fonts/GeistMono-latin.woff2')
  const batch = JSON.parse(readFileSync(join(WEB, 'public/lab-artifacts/offending-case.json'), 'utf8')) as {
    articles_sent: number; verdicts_returned: number
  }
  return `<!doctype html><meta charset="utf-8">
<style>
  @font-face{font-family:F;src:url("file://${fontPath}") format("woff2");font-weight:100 900}
  @font-face{font-family:M;src:url("file://${monoPath}") format("woff2")}
  *{margin:0;box-sizing:border-box}
  body{width:1200px;height:630px;background:#fafaf9;color:#171717;padding:54px;display:grid;grid-template-columns:1.05fr 1fr;gap:48px;align-items:center;font-family:F;overflow:hidden}
  .copy{display:flex;flex-direction:column;gap:28px}
  .brand{font-size:26px;font-weight:600;letter-spacing:-1px}
  h1{font:550 76px/1.02 F;letter-spacing:-4px}
  p{font:400 22px/1.45 F;color:#626262;max-width:26ch}
  .instrument{background:#111315;border:1px solid #35393b;border-radius:12px;padding:32px;color:#fafaf9}
  .label{font:400 12px M;color:#bfc3c6;letter-spacing:1px}
  h2{font:500 39px/1.08 F;letter-spacing:-1.5px;margin:28px 0 36px}
  .batch{display:flex;align-items:center;gap:24px;padding:28px 0;border-top:1px solid #383c40;border-bottom:1px solid #383c40}
  .n{display:flex;flex-direction:column;gap:8px;font:400 12px M;color:#bfc3c6}
  .n b{font:400 54px/1 M;color:#fafaf9;letter-spacing:-3px}
  .n:last-child b{color:#ed927b}
  .arrow{color:#a4a8aa;font-size:22px}
  .foot{color:#bfc3c6;font:400 13px/1.6 F;margin-top:24px}
</style>
<div class="copy"><div class="brand">Daily</div><h1>Daily makes<br>news personal.</h1><p>A personalized news app.<br>A Lab to test what breaks.</p></div>
<div class="instrument"><div class="label">DAILY LAB</div><h2>Does the fix<br>actually work?</h2><div class="batch"><div class="n"><b>${batch.articles_sent}</b><span>articles sent</span></div><span class="arrow">→</span><div class="n"><b>${batch.verdicts_returned}</b><span>verdicts returned</span></div></div><div class="foot">A recorded parser failure.<br>Test a proposed fix in Vercel Sandbox.</div></div>`
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
