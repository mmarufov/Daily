import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import type { Locator, Response } from '@playwright/test'

import { expect, test } from './fixtures'

/** Layout is measured on the document; a clipped table can be wider without
 * making the entire page scroll sideways. Include the deep evidence views. */

const PAGES = [
  '/', '/lab', '/lab/accepted', '/evidence',
  '/evidence?persona=ray&view=funnel',
  '/evidence?run=prod-llm__2026-08-31__47edb50&persona=ray&view=stories&story=a00407',
  '/reader', '/engineering',
] as const

/** 320 is the narrowest phone still in use; 1920 is a common desktop. */
const WIDTHS = [320, 375, 768, 1024, 1280, 1920] as const

test.describe('no page scrolls sideways', () => {
  for (const path of PAGES) {
    test(`${path} fits every width`, async ({ page }) => {
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: 900 })
        await page.goto(path)
        await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
        const overflow = await page.evaluate(() => {
          const de = document.documentElement
          return de.scrollWidth - de.clientWidth
        })
        expect(overflow, `${path} overflows by ${overflow}px at ${width}px`).toBeLessThanOrEqual(0)
      }
    })
  }
})


/** Measure sibling composition rather than incidental CSS class names or pixels. */
async function expectColumns(first: Locator, second: Locator, sideBySide: boolean) {
  const a = await first.boundingBox()
  const b = await second.boundingBox()
  expect(a).not.toBeNull()
  expect(b).not.toBeNull()
  if (sideBySide) {
    expect(Math.abs(a!.y - b!.y), 'Evidence columns must share their top edge').toBeLessThanOrEqual(1)
    expect(b!.x).toBeGreaterThanOrEqual(a!.x + a!.width)
  } else {
    expect(b!.y, 'Evidence must follow the reading order on narrow screens').toBeGreaterThanOrEqual(a!.y + a!.height)
  }
}

for (const colorScheme of ['light', 'dark'] as const) {
  test(`${colorScheme} homepage composition preserves evidence order and stable comparison heights`, async ({ page }) => {
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' })
    for (const width of [390, 639, 640, 1023, 1024, 1440]) {
      await page.setViewportSize({ width, height: 1000 })
      await page.goto('/')
      await page.evaluate(() => document.fonts.ready)
      const invitation = page.locator('#daily-lab')
      const timeline = invitation.getByTestId('recorded-run-timeline')
      const result = invitation.locator('.recorded-result')
      await expectColumns(timeline, result, width >= 1024)
      const action = invitation.getByRole('link', { name: 'Run the default parser', exact: true })
      const actionBox = await action.boundingBox()
      const timelineBox = await timeline.boundingBox()
      expect(timelineBox!.y).toBeGreaterThanOrEqual(actionBox!.y + actionBox!.height)
      expect(await timeline.locator('xpath=ancestor::details').count()).toBe(0)
      await expect(timeline.getByText('graded outside the microVM', { exact: true })).toBeVisible()
      await expect(result.getByTestId('recorded-case-field')).toBeVisible()

      const panel = page.getByTestId('guard-experiment-panel')
      const recall = panel.getByTestId('guard-metric-recall')
      const unwanted = panel.getByTestId('guard-metric-unwanted')
      await expectColumns(recall, unwanted, width >= 640)
      const original = panel.getByRole('button', { name: 'Original', exact: true })
      const experiment = panel.getByRole('button', { name: 'Guard experiment', exact: true })
      await original.click()
      const originalHeight = (await panel.boundingBox())!.height
      await experiment.click()
      await expect(experiment).toHaveAttribute('aria-pressed', 'true')
      const experimentHeight = (await panel.boundingBox())!.height
      expect(Math.abs(originalHeight - experimentHeight), `Comparison shifted at ${width}px`).toBeLessThanOrEqual(1)
      await expect(panel.getByText(/6 recorded gate failures/)).toBeVisible()
      await expect(panel.getByText(/historical working-tree experiment/)).toBeVisible()
      if (width === 1440) {
        expect((await page.locator('#experiment').boundingBox())!.height).toBeLessThanOrEqual(780)
      }
      // Expanded provenance must grow naturally rather than clip the source link.
      const summary = panel.locator('summary').filter({ hasText: /^Experiment provenance$/ })
      await summary.click()
      const source = panel.getByRole('link', { name: /Inspect summary and source hashes/ })
      await expect(source).toBeVisible()
      const sourceBox = await source.boundingBox()
      const panelBox = await panel.boundingBox()
      expect(sourceBox!.y + sourceBox!.height).toBeLessThanOrEqual(panelBox!.y + panelBox!.height)
      await summary.click()
      expect((await panel.boundingBox())!.height).toBeCloseTo(experimentHeight, 0)

      const retrieval = page.getByTestId('retrieval-loss-panel')
      await expectColumns(retrieval.locator('.retrieval-explanation'), retrieval.locator('.retrieval-story'), width >= 1024)
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
      expect(overflow, `Homepage overflow at ${width}px`).toBeLessThanOrEqual(0)
    }
  })
}

test('nothing is painted above the header', async ({ page }) => {
  // The overscroll area at the top of a document shows whatever sits above
  // the first element. Anything bleeding up there is visible the moment a
  // trackpad user rubber-bands, which is the first thing many people do.
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')
  const strays = await page.evaluate(() => {
    const header = document.querySelector('header')?.getBoundingClientRect()
    if (header === undefined) return ['no header']
    const found: string[] = []
    document.querySelectorAll('*').forEach((el) => {
      const box = el.getBoundingClientRect()
      if (box.height === 0) return
      if (getComputedStyle(el).position === 'fixed') return
      if (box.top < header.top - 1) found.push(el.tagName.toLowerCase())
    })
    return [...new Set(found)]
  })
  expect(strays).toEqual([])
})

test('all four primary destinations remain visible and touch sized on a narrow phone', async ({ page }) => {
  for (const width of [320, 375, 639]) {
    await page.setViewportSize({ width, height: 900 })
    await page.goto('/')
    const banner = page.getByRole('banner')
    const brand = banner.getByRole('link', { name: 'Daily, home', exact: true })
    const navigation = banner.getByRole('navigation')
    const brandBox = await brand.boundingBox()
    const navigationBox = await navigation.boundingBox()
    expect(navigationBox!.y).toBeGreaterThanOrEqual(brandBox!.y + brandBox!.height)
    for (const name of ['Reader', 'Lab', 'Evidence', 'Findings']) {
      const link = navigation.getByRole('link', { name, exact: true })
      await expect(link).toBeInViewport()
      const box = await link.boundingBox()
      expect(box!.height).toBeGreaterThanOrEqual(44)
      expect(box!.width).toBeGreaterThanOrEqual(44)
      expect(box!.x).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(width)
    }
  }
})

test('Fraunces is fetched only after entering the Reader, where the editorial headlines use it', async ({ page }) => {
  const digest = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex')
  const sourceHash = (name: string) => digest(readFileSync(join(__dirname, '..', '..', 'app', 'fonts', name)))
  const fraunces = sourceHash('Fraunces-latin.woff2')
  const sans = sourceHash('GeistSans-variable.woff2')
  const mono = sourceHash('GeistMono-latin.woff2')
  const fonts: Response[] = []
  page.on('response', (response) => {
    if (/\.woff2(?:\?|$)/.test(response.url())) fonts.push(response)
  })

  await page.goto('/')
  await page.evaluate(() => document.fonts.ready.then(() => undefined))
  // Expose both hero/nav and footer entry links to Next's viewport prefetch.
  await page.getByRole('contentinfo').scrollIntoViewIfNeeded()
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(2000)
  const homeHashes = await Promise.all(fonts.map(async (response) => digest(await response.body())))
  expect([...new Set(homeHashes)].sort()).toEqual([sans, mono].sort())
  expect(homeHashes).not.toContain(fraunces)
  const loadedOnHome = fonts.length

  await page.getByRole('banner').getByRole('link', { name: 'Reader', exact: true }).click()
  await expect(page).toHaveURL((url) => url.pathname === '/reader')
  const editorial = page.getByRole('article').locator('.editorial').first()
  await expect(editorial).toBeVisible()
  await page.evaluate(() => document.fonts.ready.then(() => undefined))
  await page.waitForLoadState('networkidle')
  const readerHashes = await Promise.all(fonts.slice(loadedOnHome).map(async (response) => digest(await response.body())))
  expect(readerHashes).toContain(fraunces)
  expect(await editorial.evaluate((element) => getComputedStyle(element).fontFamily)).toMatch(/fraunces/i)
})

for (const colorScheme of ['light', 'dark'] as const) {
  test(`${colorScheme} mode exposes readable, touch-sized instrument controls and visible keyboard focus`, async ({ page }) => {
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' })
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
    const hero = page.getByTestId('hero-sieve')
    await expect(hero).toHaveAttribute('data-stage', '9')
    const controls = [
      hero.getByRole('combobox', { name: 'Reader fixture' }),
      hero.getByRole('slider', { name: 'Pipeline stage' }),
      hero.getByRole('button', { name: 'Replay', exact: true }),
    ]
    for (const control of controls) {
      await expect(control).toBeVisible()
      const box = await control.boundingBox()
      expect(box).not.toBeNull()
      expect(box!.width).toBeGreaterThanOrEqual(44)
      expect(box!.height).toBeGreaterThanOrEqual(44)
    }

    const slider = hero.getByRole('slider', { name: 'Pipeline stage' })
    await slider.press('Home')
    await expect(slider).toBeFocused()
    const focus = await slider.evaluate((element) => {
      const style = getComputedStyle(element)
      return { visible: element.matches(':focus-visible'), width: parseFloat(style.outlineWidth), style: style.outlineStyle }
    })
    expect(focus.visible).toBe(true)
    expect(focus.width).toBeGreaterThanOrEqual(2)
    expect(focus.style).not.toBe('none')
  })

  test(`${colorScheme} result cells retain visible symbols and text beyond color`, async ({ page }) => {
    await page.emulateMedia({ colorScheme, reducedMotion: 'reduce' })
    await page.goto('/')
    const field = page.getByTestId('recorded-case-field')
    await field.scrollIntoViewIfNeeded()
    for (const tone of ['correct', 'wrong', 'unscored']) {
      const mark = field.locator(`[data-case-mark="${tone}"]`).first()
      await expect(mark).toBeVisible()
      const appearance = await mark.evaluate((element) => {
        const style = getComputedStyle(element)
        const bounds = element.getBoundingClientRect()
        return { width: bounds.width, height: bounds.height, stroke: style.stroke, color: style.color }
      })
      expect(appearance.width).toBeGreaterThanOrEqual(12)
      expect(appearance.height).toBeGreaterThanOrEqual(12)
      expect(appearance.stroke).not.toBe('none')
      expect(appearance.color).not.toBe('rgba(0, 0, 0, 0)')
    }
  })
}

test('forced colors preserve result marks and the counted legend', async ({ page }) => {
  await page.emulateMedia({ forcedColors: 'active', reducedMotion: 'reduce' })
  await page.goto('/')
  const field = page.getByTestId('recorded-case-field')
  await field.scrollIntoViewIfNeeded()
  const shapes: string[] = []
  for (const tone of ['correct', 'wrong', 'unscored']) {
    const mark = field.locator(`[data-case-mark="${tone}"]`).first()
    await expect(mark).toBeVisible()
    shapes.push(await mark.innerHTML())
    const colors = await mark.evaluate((element) => ({
      foreground: getComputedStyle(element).color,
      background: getComputedStyle(element.parentElement!).backgroundColor,
    }))
    expect(colors.foreground).not.toBe(colors.background)
  }
  expect(new Set(shapes).size).toBe(3)
  await expect(field.locator('xpath=..').getByText('48 correct', { exact: true })).toBeVisible()
})

/**
 * The tab was blank and every link to the site previewed as a grey box --
 * including on a job application. None of it is visible from inside the app,
 * so nothing would have reported it broken a second time either.
 */
test.describe('identity', () => {
  test('the tab has an icon and links preview with an image', async ({ page }) => {
    await page.goto('/')

    // A vector icon, plus the raster fallback for browsers that ignore it.
    await expect(page.locator('link[rel="icon"][type="image/svg+xml"]')).toHaveCount(1)
    await expect(page.locator('link[rel="icon"][type="image/png"]')).toHaveCount(1)
    await expect(page.locator('link[rel="apple-touch-icon"]')).toHaveCount(1)

    // An og:image with no dimensions is rendered small or dropped outright.
    await expect(page.locator('meta[property="og:image"]')).toHaveCount(1)
    await expect(page.locator('meta[property="og:image:width"]')).toHaveAttribute(
      'content',
      '1200',
    )
    await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute(
      'content',
      'summary_large_image',
    )

    // Every referenced asset must actually resolve -- a 404 here is invisible
    // in the browser and fatal to the preview.
    for (const sel of [
      'link[rel="icon"][type="image/svg+xml"]',
      'link[rel="icon"][type="image/png"]',
      'link[rel="apple-touch-icon"]',
    ]) {
      const href = await page.locator(sel).getAttribute('href')
      expect(href, sel).not.toBeNull()
      const res = await page.request.get(href as string)
      expect(res.status(), `${sel} -> ${href}`).toBe(200)
    }
    // og:image is absolute, pinned to the production origin by metadataBase --
    // which is what a scraper needs and what makes it useless to fetch here.
    // Check the path against the site under test, so the assertion is about
    // this build rather than about whatever is currently deployed.
    const og = await page.locator('meta[property="og:image"]').getAttribute('content')
    expect(og, 'og:image must be absolute or scrapers drop it').toMatch(/^https:\/\/marufov\.com\//)
    const { pathname, search } = new URL(og as string)
    expect((await page.request.get(`${pathname}${search}`)).status()).toBe(200)
  })
})

/**
 * Two house rules, both asked for after they had already shipped.
 *
 * The title template was '%s — Daily', which made the Lab's tab read "Daily
 * Lab — Daily" and every other one longer than a tab can show. And the em
 * dash had spread to 45 places: it is the punctuation you reach for when you
 * have not decided whether two clauses are one sentence or two, which is why
 * it reads as filler.
 */
const ROUTES = ['/', '/reader', '/evidence', '/lab', '/engineering'] as const

test.describe('house style', () => {
  for (const route of ROUTES) {
    test(`${route} has a short title and no em dash anywhere`, async ({ page }) => {
      await page.goto(route)

      const title = await page.title()
      // A tab truncates around here, and a window with several open truncates
      // sooner. The site name belongs in og:site_name, not after every title.
      expect(title.length, `"${title}" is too long for a tab`).toBeLessThanOrEqual(24)
      expect(title, `"${title}" still carries the site-name suffix`).not.toMatch(/ [—-] Daily$/)

      // Article headlines come out of the frozen corpus and are reproduced
      // exactly. Editing a real headline to satisfy a house style would be
      // falsifying the evidence, on a site whose whole argument is that its
      // evidence is one set of bytes. They carry `data-verbatim`, and the rule
      // stops at that boundary.
      const found = await page.evaluate(() => {
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
        const hits: string[] = []
        let node = walker.nextNode()
        while (node !== null) {
          const text = node.textContent ?? ''
          const parent = node.parentElement
          const inScript =
            parent !== null && parent.closest('script, style, noscript') !== null
          if (
            text.includes('\u2014') &&
            parent !== null &&
            !inScript &&
            parent.closest('[data-verbatim]') === null
          ) {
            hits.push(text.trim().slice(0, 110))
          }
          node = walker.nextNode()
        }
        return hits
      })
      expect(found, `em dash in the site's own copy:\n${found.join('\n')}`).toEqual([])
    })
  }
})
