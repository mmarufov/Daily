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
 * The tab icon is the mark: a three-by-three sieve that survives 16px. The OG
 * image is the homepage's first screen at card size, with the 64 cases of the
 * recorded production run drawn from the stored response.
 *
 * Playwright renders these rather than `next/og`, because Satori supports a
 * subset of CSS. A committed PNG also means a link preview cannot be broken by
 * a runtime failure on a route nobody visits.
 */

import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { chromium } from 'playwright'

const WEB = join(fileURLToPath(new URL('.', import.meta.url)), '..')

/**
 * The recorded production run the homepage opens on. The card draws its 64
 * cases from the stored response, so the picture is that run, not a pattern.
 */
const RECORDED = 'public/runs/wrun_01M3WXWPKMF3H8Q66KZA56MZCV.json'

interface StoredCase {
  case_id: string
  origin: string
  applicability: string
  status: string
}

function ogHtml(): string {
  const fontPath = join(WEB, 'app/fonts/GeistSans-variable.woff2')
  const monoPath = join(WEB, 'app/fonts/GeistMono-latin.woff2')
  const stored = JSON.parse(readFileSync(join(WEB, RECORDED), 'utf8')) as {
    response: { outcome: { verdict: string; grading: { cases: StoredCase[]; out_of_protocol_case_ids: string[] } } }
  }
  const grading = stored.response.outcome.grading
  const outside = new Set(grading.out_of_protocol_case_ids)
  const tone = (c: StoredCase) =>
    c.applicability === 'not-applicable' ? (outside.has(c.case_id) ? 'out' : 'na') : c.status === 'correct' ? 'ok' : 'bad'
  const caught = grading.cases.find(
    (c) => c.origin === 'fault-injection' && c.applicability === 'scored' && c.status !== 'correct',
  )
  const row = (origin: string) =>
    grading.cases
      .filter((c) => c.origin === origin)
      .map((c) => `<i class="${tone(c)}${c === caught ? ' caught' : ''}"></i>`)
      .join('')

  return `<!doctype html><meta charset="utf-8">
<style>
  @font-face{font-family:G;src:url("file://${fontPath}") format("woff2");font-weight:100 900}
  @font-face{font-family:M;src:url("file://${monoPath}") format("woff2")}
  *{margin:0;box-sizing:border-box}
  body{width:1200px;height:630px;background:#fafafa;color:#171717;font-family:G;padding:64px;display:flex;flex-direction:column;justify-content:space-between;overflow:hidden}
  .brand{display:flex;align-items:center;gap:14px;font:600 26px G;letter-spacing:-.5px}
  .brand svg{width:28px;height:28px}
  .main{display:grid;grid-template-columns:1fr 524px;gap:48px;align-items:end}
  h1{font:600 84px/1 G;letter-spacing:-4px}
  .panel{background:#fff;border:1px solid #e6e6e6;border-radius:18px;padding:30px;box-shadow:0 24px 48px -24px rgb(0 0 0/.18)}
  .k{font:500 16px G;color:#6b6b6b;margin:0 0 10px}
  .cells{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:22px;max-width:calc(22 * 15px + 21 * 6px)}
  .cells i{width:15px;height:15px;border-radius:3.5px;box-shadow:inset 0 0 0 1px #d0d0d0}
  .cells i.ok{background:#171717;box-shadow:none}
  .cells i.bad{background:#e5484d;box-shadow:none}
  .cells i.na{background:#ebebeb;box-shadow:none}
  .cells i.out{background:#fff;box-shadow:inset 0 0 0 2px #e5484d}
  .cells i.caught{box-shadow:0 0 0 2px #fff,0 0 0 3.5px #e5484d}
  .verdict{display:flex;align-items:baseline;justify-content:space-between;border-top:1px solid #e6e6e6;padding-top:18px}
  .verdict b{font:600 34px G;letter-spacing:-1.2px;color:#ce2c31}
  .verdict span{font:400 15px M;color:#4d4d4d}
  .foot{font:400 21px G;color:#4d4d4d}
</style>
<div class="brand"><svg viewBox="0 0 18 18"><rect x="0" y="0" width="5" height="5" rx="1"/><rect x="6.5" y="0" width="5" height="5" rx="1" opacity=".2"/><rect x="13" y="0" width="5" height="5" rx="1" opacity=".2"/><rect x="0" y="6.5" width="5" height="5" rx="1" opacity=".2"/><rect x="6.5" y="6.5" width="5" height="5" rx="1"/><rect x="13" y="6.5" width="5" height="5" rx="1"/><rect x="0" y="13" width="5" height="5" rx="1" opacity=".2"/><rect x="6.5" y="13" width="5" height="5" rx="1"/><rect x="13" y="13" width="5" height="5" rx="1" opacity=".2"/></svg>Daily Lab</div>
<div class="main">
  <h1>Find out if the fix fixes anything.</h1>
  <div class="panel">
    <p class="k">Recorded production run, 64 cases</p>
    <div class="cells">${row('recorded-replay')}</div>
    <div class="cells">${row('fault-injection')}</div>
    <div class="verdict"><b>${stored.response.outcome.verdict === 'rejected' ? 'Rejected' : stored.response.outcome.verdict}</b><span>${caught?.case_id ?? ''}</span></div>
  </div>
</div>
<p class="foot">A proposed fix, run in a Vercel Sandbox microVM against cases built to break it. Every result published.</p>`
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
    await page.waitForTimeout(100)
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
