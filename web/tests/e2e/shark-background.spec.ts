import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

const canvasSelector = '[data-testid="shark-background"] canvas'

const posterSelector = '[data-testid="shark-background"] picture img'
type CountedWindow = Window & { oceanDraws: number }

async function countDraws(page: Page) {
  await page.addInitScript(() => {
    const counted = window as CountedWindow
    counted.oceanDraws = 0
    const prototype = CanvasRenderingContext2D.prototype
    for (const name of ['fillText', 'drawImage'] as const) {
      const original = prototype[name]
      Object.defineProperty(prototype, name, {
        configurable: true,
        value(this: CanvasRenderingContext2D, ...args: unknown[]) {
          if (this.canvas instanceof HTMLCanvasElement && this.canvas.matches('[data-testid="shark-background"] canvas')) counted.oceanDraws++
          return Reflect.apply(original, this, args)
        },
      })
    }
  })
}

function draws(page: Page) {
  return page.evaluate(() => (window as CountedWindow).oceanDraws)
}

async function expectStopped(page: Page) {
  const before = await draws(page)
  await page.waitForTimeout(350)
  expect(await draws(page)).toBe(before)
}

async function expectPoster(page: Page) {
  const poster = page.locator(posterSelector)
  await expect(poster).toBeVisible()
  await expect.poll(() => poster.evaluate((image: HTMLImageElement) => image.complete && image.naturalWidth > 0)).toBe(true)
}

test('the desktop opening fills the viewport and retains its two-column foreground', async ({ page, isMobile }) => {
  test.skip(isMobile, 'Mobile content may grow past one viewport.')
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/')
  const layout = await page.evaluate(() => {
    const hero = document.querySelector('.hero-scene')!.getBoundingClientRect()
    const copy = document.querySelector('.hero-copy')!.getBoundingClientRect()
    const edition = document.querySelector('[data-testid="edition-preview"]')!.getBoundingClientRect()
    const header = document.querySelector('.site-header')!.getBoundingClientRect()
    return { heroBottom: hero.bottom, heroTop: hero.top, headerBottom: header.bottom, copyRight: copy.right, editionLeft: edition.left }
  })
  expect(Math.abs(layout.heroBottom - 1000)).toBeLessThanOrEqual(2)
  expect(Math.abs(layout.heroTop - layout.headerBottom)).toBeLessThanOrEqual(2)
  expect(layout.copyRight).toBeLessThan(layout.editionLeft)
  await expect(page.getByRole('link', { name: 'Explore the Lab' })).toBeInViewport()
  await expect(page.getByTestId('edition-preview')).toBeInViewport()
  await page.mouse.move(720, 500)
  await page.mouse.wheel(0, 1100)
  await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(700)
  await expect(page.getByTestId('run-story')).toBeInViewport()
})

test('the decorative scene moves and keyboard pause preserves usable hero actions', async ({ page }) => {
  await countDraws(page)
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/')
  const canvas = page.locator(canvasSelector)
  await expect(canvas).toBeVisible()
  await expect(page.getByTestId('shark-background')).toHaveAttribute('aria-hidden', 'true')
  const frame = () => canvas.evaluate((el: HTMLCanvasElement) => el.toDataURL())
  const first = await frame()
  await expect.poll(frame).not.toBe(first)
  await page.getByRole('button', { name: 'Pause background animation' }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('button', { name: 'Play background animation' })).toBeFocused()
  await expectStopped(page)
  await page.keyboard.press('Enter')
  const before = await draws(page)
  await expect.poll(() => draws(page)).toBeGreaterThan(before)
  await page.getByRole('link', { name: 'Explore the Lab' }).click()
  await expect(page).toHaveURL(/\/lab$/)
})

test('offscreen drawing stays stopped through resize and resumes on return', async ({ page }) => {
  await countDraws(page)
  await page.goto('/')
  await expect(page.locator(canvasSelector)).toBeVisible()
  await expect.poll(() => draws(page)).toBeGreaterThan(0)
  await page.getByRole('contentinfo').scrollIntoViewIfNeeded()
  await page.waitForTimeout(150)
  const viewport = page.viewportSize()!
  await page.setViewportSize({ width: viewport.width, height: viewport.height - 30 })
  await page.waitForTimeout(150)
  await expectStopped(page)
  await page.evaluate(() => scrollTo({ top: 0, behavior: 'instant' }))
  const before = await draws(page)
  await expect.poll(() => draws(page)).toBeGreaterThan(before)
})

test('reduced motion displays the loaded poster and preserves the headline and links', async ({ page }) => {
  await countDraws(page)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await expectPoster(page)
  await expect(page.locator(canvasSelector)).toBeHidden()
  await expect(page.getByRole('button', { name: 'Pause background animation' })).toBeHidden()
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Explore the Lab' })).toBeVisible()
  await expectStopped(page)
})

test('unavailable canvas keeps the still artwork and usable hero', async ({ page }) => {
  await page.addInitScript(() => { HTMLCanvasElement.prototype.getContext = () => null })
  await page.goto('/')
  await expectPoster(page)
  await page.getByRole('link', { name: 'Explore the Lab' }).click()
  await expect(page).toHaveURL(/\/lab$/)
})

test.describe('without scripts', () => {
  test.use({ javaScriptEnabled: false })
  test('still artwork and both destinations render without hydration', async ({ page }) => {
    await page.goto('/')
    await expectPoster(page)
    await expect(page.getByRole('link', { name: 'Explore the Lab' })).toHaveAttribute('href', '/lab')
    await expect(page.getByRole('link', { name: 'Read an edition', exact: false }).first()).toHaveAttribute('href', '/reader?profile=ray')
  })
})

test('a hidden tab stops drawing and resumes on return', async ({ page }) => {
  await countDraws(page)
  await page.goto('/')
  const canvas = page.locator(canvasSelector)
  await expect(canvas).toBeVisible()
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  await expectStopped(page)
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false })
    document.dispatchEvent(new Event('visibilitychange'))
  })
  const before = await draws(page)
  await expect.poll(() => draws(page)).toBeGreaterThan(before)
})

test('manual pause survives resizing without a continuous draw loop', async ({ page }) => {
  await countDraws(page)
  await page.goto('/')
  await page.getByRole('button', { name: 'Pause background animation' }).click()
  const viewport = page.viewportSize()!
  await page.setViewportSize({ width: viewport.width - 30, height: viewport.height - 30 })
  await page.waitForTimeout(150)
  await expect(page.getByRole('button', { name: 'Play background animation' })).toBeVisible()
  await expectStopped(page)
  expect(await page.locator(canvasSelector).evaluate((el: HTMLCanvasElement) => el.width > 0 && el.height > 0)).toBe(true)
  await page.getByRole('button', { name: 'Play background animation' }).click()
  const before = await draws(page)
  await expect.poll(() => draws(page)).toBeGreaterThan(before)
})

test('switching motion preference stops the canvas and returns to the poster', async ({ page }) => {
  await countDraws(page)
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/')
  await expect(page.locator(canvasSelector)).toBeVisible()
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await expectPoster(page)
  await expect(page.locator(canvasSelector)).toBeHidden()
  await expectStopped(page)
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await expect(page.locator(canvasSelector)).toBeVisible()
  const before = await draws(page)
  await expect.poll(() => draws(page)).toBeGreaterThan(before)
})

test('printing suspends the scene and returning restores drawing', async ({ page }) => {
  await countDraws(page)
  await page.goto('/')
  await expect(page.locator(canvasSelector)).toBeVisible()
  await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')))
  await page.emulateMedia({ media: 'print' })
  await expect(page.getByTestId('shark-background')).toBeHidden()
  await expectStopped(page)
  await page.emulateMedia({ media: 'screen' })
  await page.evaluate(() => window.dispatchEvent(new Event('afterprint')))
  const before = await draws(page)
  await expect.poll(() => draws(page)).toBeGreaterThan(before)
})

// The existing RunStory also fails without IntersectionObserver on production.
test.fixme('missing intersection observation leaves static artwork without a frame loop', async ({ page }) => {
  await page.addInitScript(() => { Object.defineProperty(window, 'IntersectionObserver', { value: undefined }) })
  await page.goto('/')
  await expectPoster(page)
  await expect(page.locator(canvasSelector)).toBeHidden()
  await expect(page.getByRole('link', { name: 'Explore the Lab' })).toBeVisible()
})
