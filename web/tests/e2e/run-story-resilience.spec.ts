import type { Locator, Page } from '@playwright/test'
import { expect, test } from './fixtures'

const chunks = '**/_next/static/**/*.js'

async function scrollToStage(story: Locator, progress = 0.6) {
  await story.locator('.run-story-track').evaluate((track, fraction) => {
    const panel = track.querySelector<HTMLElement>('.run-story-sticky')!
    window.scrollTo({ top: window.scrollY + track.getBoundingClientRect().top - 96 + ((track as HTMLElement).offsetHeight - panel.offsetHeight) * fraction, behavior: 'instant' })
  }, progress)
}

async function staticStory(page: Page) {
  const story = page.getByTestId('run-story')
  await expect(story).toHaveAttribute('data-mode', 'static')
  await expect(story.locator('.run-story-animation')).toBeHidden()
  for (const chapter of await story.locator('.run-story-chapter').all()) await expect(chapter).toBeVisible()
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
}

async function usableRestoredStory(page: Page) {
  const story = page.getByTestId('run-story')
  await expect(story).toBeVisible()
  await expect.poll(async () => {
    if (await story.getAttribute('data-mode') === 'static') return story.locator('.run-story-chapters').isVisible()
    return story.evaluate(element => {
      const track = element.querySelector<HTMLElement>('.run-story-track')!
      const panel = element.querySelector<HTMLElement>('.run-story-sticky')!
      const progress = Math.max(0, Math.min(1, (96 - track.getBoundingClientRect().top) / Math.max(1, track.offsetHeight - panel.offsetHeight)))
      const expected = [0.24, 0.51, 0.78].filter(boundary => progress >= boundary).length
      return (element as HTMLElement).dataset.stage === String(expected) && (element as HTMLElement).dataset.transitioning === 'false'
    })
  }).toBe(true)
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
}

test.describe('run story resilience', () => {
  test.beforeEach(async ({ page }) => {
    // Preview feedback scripts are outside the application being tested.
    await page.route('https://vercel.live/**', route => route.abort())
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.emulateMedia({ reducedMotion: 'no-preference' })
  })

  test('blocked JavaScript keeps the complete static recording readable', async ({ page }) => {
    await page.route(chunks, route => route.abort())
    await page.goto('/')
    await staticStory(page)
    await page.locator('[data-chapter="verdict"]').scrollIntoViewIfNeeded()
    await expect(page.locator('.run-story-chapters .run-case-grid')).toBeInViewport()
  })

  test('late JavaScript does not replace a recording already being read', async ({ page }) => {
    let release!: () => void
    const held = new Promise<void>(resolve => { release = resolve })
    await page.route(chunks, async route => { await held; await route.continue() })
    try {
      await page.goto('/', { waitUntil: 'commit' })
      await staticStory(page)
      const heading = page.locator('[data-chapter="tests"] h3')
      await heading.scrollIntoViewIfNeeded()
      const top = await heading.evaluate(element => element.getBoundingClientRect().top)
      release()
      await page.waitForLoadState('load')
      await page.waitForTimeout(500)
      await staticStory(page)
      expect(Math.abs(await heading.evaluate(element => element.getBoundingClientRect().top) - top)).toBeLessThan(80)
    } finally { release() }
  })

  for (const api of ['IntersectionObserver', 'ResizeObserver'] as const) {
    test(`missing ${api} leaves the page and recording usable`, async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', error => errors.push(error.message))
      await page.addInitScript(name => { Object.defineProperty(window, name, { value: undefined, configurable: true }) }, api)
      await page.goto('/')
      await staticStory(page)
      await expect(page.getByRole('heading', { name: 'Daily makes news personal.' })).toBeVisible()
      expect(errors).toEqual([])
    })
  }

  for (const change of ['resize', 'reduced motion'] as const) {
    test(`${change} preserves keyboard focus when the rail becomes static`, async ({ page }) => {
      const errors: string[] = []
      page.on('pageerror', error => errors.push(error.message))
      await page.goto('/')
      const story = page.getByTestId('run-story')
      await expect(story).toHaveAttribute('data-mode', 'scroll')
      const tests = story.getByRole('button', { name: 'Tests', exact: true })
      await tests.press('Enter')
      await expect(story).toHaveAttribute('data-stage', '2')
      await expect(story).toHaveAttribute('data-transitioning', 'false')
      if (change === 'resize') await page.setViewportSize({ width: 800, height: 900 })
      else await page.emulateMedia({ reducedMotion: 'reduce' })
      await staticStory(page)
      await expect(story.locator('[data-chapter="tests"] h3')).toBeFocused()
      await expect(story.locator('[data-chapter="tests"] h3')).toBeInViewport()
      if (change === 'resize') await page.setViewportSize({ width: 1440, height: 900 })
      else await page.emulateMedia({ reducedMotion: 'no-preference' })
      await expect(story).toHaveAttribute('data-mode', 'scroll')
      await scrollToStage(story)
      await expect(story).toHaveAttribute('data-stage', '2')
      await expect(story).toHaveAttribute('data-transitioning', 'false')
      expect(errors).toEqual([])
    })
  }

  test('enlarged text falls back before the verdict overlaps its caption', async ({ page }) => {
    await page.goto('/')
    const story = page.getByTestId('run-story')
    await expect(story).toHaveAttribute('data-mode', 'scroll')
    await scrollToStage(story, 0.9)
    await story.evaluate(element => {
      const sizes = Array.from(element.querySelectorAll<HTMLElement>('*'), node => ({ node, size: parseFloat(getComputedStyle(node).fontSize) }))
      for (const { node, size } of sizes) node.style.fontSize = `${size * 2}px`
    })
    await staticStory(page)
    const verdict = story.locator('[data-chapter="verdict"]')
    const box = await verdict.boundingBox()
    const example = await verdict.locator('.run-failure-example').boundingBox()
    expect(example!.y + example!.height).toBeLessThanOrEqual(box!.y + box!.height)
  })

  test('wide print layout includes every chapter and removes scroll space', async ({ page }) => {
    await page.goto('/')
    const story = page.getByTestId('run-story')
    await scrollToStage(story)
    await page.emulateMedia({ media: 'print' })
    await expect(story.locator('.run-story-animation')).toBeHidden()
    for (const chapter of await story.locator('.run-story-chapter').all()) await expect(chapter).toBeVisible()
    await expect(story.locator('.run-story-sticky')).toHaveCSS('position', 'static')
    const dimensions = await story.locator('.run-story-track').evaluate(element => ({ track: (element as HTMLElement).offsetHeight, contents: Array.from(element.children).reduce((sum, child) => sum + (child as HTMLElement).offsetHeight, 0) }))
    expect(Math.abs(dimensions.track - dimensions.contents)).toBeLessThan(5)
  })

  test('page suspension stops work and resumption reads the current position', async ({ page }) => {
    await page.goto('/')
    const story = page.getByTestId('run-story')
    await scrollToStage(story, 0.3)
    await expect(story).toHaveAttribute('data-stage', '1')
    await page.evaluate(() => dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true })))
    await expect(story).toHaveAttribute('data-active', 'false')
    await scrollToStage(story, 0.9)
    await page.evaluate(() => dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })))
    await expect(story).toHaveAttribute('data-active', 'true')
    await expect(story).toHaveAttribute('data-stage', '3')
    await expect(story).toHaveAttribute('data-transitioning', 'false')
  })

  test('reload and history restoration keep the recording usable', async ({ page, browserName }, testInfo) => {
    const errors: { message: string; stack: string }[] = []
    page.on('pageerror', error => errors.push({ message: error.message, stack: error.stack ?? '' }))
    await page.goto('/')
    const story = page.getByTestId('run-story')
    await scrollToStage(story)
    await expect(story).toHaveAttribute('data-stage', '2')
    await expect(story).toHaveAttribute('data-transitioning', 'false')
    await page.reload()
    await usableRestoredStory(page)
    await page.goto('/engineering')
    await page.goBack()
    await usableRestoredStory(page)
    await page.goForward()
    await expect(page.getByRole('main')).toBeVisible()
    await page.goBack()
    await usableRestoredStory(page)
    // WebKit rejects in-flight Next prefetches during navigation on the production baseline too.
    const origin = new URL(page.url()).origin
    const prefetchCancellations = errors.filter(error => {
      const request = error.stack.match(/^Fetch API cannot load (https:\/\/\S+) due to access control checks\./)?.[1]
      if (browserName !== 'webkit' || !request || !error.stack.includes(`${origin}/_next/static/`)) return false
      const url = new URL(request)
      return url.origin === origin && url.searchParams.has('_rsc')
    })
    if (prefetchCancellations.length) await testInfo.attach('baseline-webkit-prefetch-cancellations', {
      body: JSON.stringify(prefetchCancellations, null, 2), contentType: 'application/json',
    })
    expect(errors.filter(error => !prefetchCancellations.includes(error))).toEqual([])
  })

  test('text spacing at the smallest cinematic viewport uses readable chapters', async ({ page }) => {
    await page.setViewportSize({ width: 1024, height: 720 })
    await page.goto('/')
    await page.addStyleTag({ content: `
      .run-story * { line-height: 1.5 !important; letter-spacing: .12em !important; word-spacing: .16em !important; }
      .run-story p { margin-bottom: 2em !important; }
    ` })
    await staticStory(page)
    const verdict = page.locator('[data-chapter="verdict"]')
    await verdict.scrollIntoViewIfNeeded()
    await expect(verdict.locator('.run-case-grid')).toBeVisible()
  })

  test('blocked fonts leave readable content in a layout that fits', async ({ page }) => {
    let blocked = 0
    await page.route(url => /\.(?:woff2?|ttf|otf)$/.test(url.pathname), async route => {
      blocked++
      await route.abort()
    })
    await page.goto('/')
    await page.evaluate(() => document.fonts.ready)
    expect(blocked).toBeGreaterThan(0)
    const story = page.getByTestId('run-story')
    if (await story.getAttribute('data-mode') === 'static') await staticStory(page)
    else {
      await scrollToStage(story, 0.9)
      await expect(story).toHaveAttribute('data-stage', '3')
      await expect(story).toHaveAttribute('data-transitioning', 'false')
      const panel = await story.locator('.run-story-sticky').boundingBox()
      expect(panel!.y + panel!.height).toBeLessThanOrEqual(900)
      const canvas = await story.locator('.run-scene-canvas').boundingBox()
      const verdict = await story.locator('.run-scene-result').boundingBox()
      expect(verdict!.y + verdict!.height).toBeLessThanOrEqual(canvas!.y + canvas!.height + 1)
    }
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
  })

  test('resuming inside the reverse buffer preserves the held chapter', async ({ page }) => {
    await page.goto('/')
    const story = page.getByTestId('run-story')
    await expect(story).toHaveAttribute('data-mode', 'scroll')
    await scrollToStage(story, 0.25)
    await expect(story).toHaveAttribute('data-stage', '1')
    await expect(story).toHaveAttribute('data-transitioning', 'false')
    await scrollToStage(story, 0.22)
    await expect(story).toHaveAttribute('data-progress', '0.220')
    await page.evaluate(() => dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true })))
    await expect(story).toHaveAttribute('data-active', 'false')
    await page.evaluate(() => dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true })))
    await expect(story).toHaveAttribute('data-active', 'true')
    await expect(story).toHaveAttribute('data-stage', '1')
    await expect(story).toHaveAttribute('data-transitioning', 'false')
    await expect(story).toHaveAttribute('data-visual-progress', '0.320')
  })

  test('a busy frame slows the transition without skipping its intermediate phases', async ({ page }) => {
    await page.goto('/')
    const story = page.getByTestId('run-story')
    await expect(story).toHaveAttribute('data-mode', 'scroll')
    await scrollToStage(story, 0.1)
    await expect(story).toHaveAttribute('data-active', 'true')
    await expect(story).toHaveAttribute('data-progress', '0.100')
    await expect(story).toHaveAttribute('data-transitioning', 'false')
    await scrollToStage(story, 0.25)
    await expect(story).toHaveAttribute('data-transitioning', 'true')
    const movement = await story.evaluate(async element => {
      const before = Number((element as HTMLElement).dataset.visualProgress)
      const end = performance.now() + 500
      while (performance.now() < end) { /* Simulate a long browser task. */ }
      await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
      return Number((element as HTMLElement).dataset.visualProgress) - before
    })
    expect(movement).toBeGreaterThan(0)
    expect(movement).toBeLessThan(0.08)
    await expect(story).toHaveAttribute('data-transitioning', 'false')
    await expect(story).toHaveAttribute('data-visual-progress', '0.320')
  })

})
