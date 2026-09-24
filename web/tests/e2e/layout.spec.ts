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
