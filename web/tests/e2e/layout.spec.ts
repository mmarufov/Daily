import { expect, test } from '@playwright/test'

/**
 * Layout integrity across the breakpoints the site is actually read at.
 *
 * Both of these shipped, and both came from one declaration: the hero's
 * background ellipse was inset `-10%` horizontally and `-18%` vertically, so
 * it extended 120px past each edge and 122px above the section. That is a
 * page you can scroll sideways, and a band of warm colour visible above the
 * header when you pull down at the top.
 *
 * Neither is catchable by reading a component -- the offender is a
 * pseudo-element, which does not appear in the DOM, and the symptom only
 * shows on the document. So it is measured here instead.
 */

const PAGES = ['/', '/lab', '/evidence', '/reader', '/engineering'] as const

/** 320 is the narrowest phone still in use; 1920 is a common desktop. */
const WIDTHS = [320, 375, 768, 1024, 1280, 1920] as const

test.describe('no page scrolls sideways', () => {
  for (const path of PAGES) {
    test(`${path} fits every width`, async ({ page }) => {
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: 900 })
        await page.goto(path)
        const overflow = await page.evaluate(() => {
          const de = document.documentElement
          return de.scrollWidth - de.clientWidth
        })
        expect(overflow, `${path} overflows by ${overflow}px at ${width}px`).toBeLessThanOrEqual(0)
      }
    })
  }
})

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

test('the hero ground stays inside the hero', async ({ page }) => {
  // The specific regression, asserted on the computed value rather than the
  // source, so it still fails if the inset moves to a variable.
  await page.setViewportSize({ width: 1280, height: 900 })
  await page.goto('/')
  const inset = await page.evaluate(() => {
    const hero = document.querySelector('.hero')
    if (hero === null) return null
    const cs = getComputedStyle(hero, '::before')
    return { top: parseFloat(cs.top), left: parseFloat(cs.left), right: parseFloat(cs.right) }
  })
  expect(inset).not.toBeNull()
  expect(inset!.top).toBeGreaterThanOrEqual(0)
  expect(inset!.left).toBeGreaterThanOrEqual(0)
  expect(inset!.right).toBeGreaterThanOrEqual(0)
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
