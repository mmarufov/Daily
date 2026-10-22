import type { Locator, Page } from '@playwright/test'
import { expect, test } from './fixtures'

async function approachStory(page: Page): Promise<Locator> {
  await page.goto('/')
  const story = page.getByTestId('run-story')
  await expect(story).toHaveAttribute('data-mode', 'scroll')
  await story.locator('.run-story-track').evaluate(track => {
    window.scrollTo({ top: window.scrollY + track.getBoundingClientRect().top - 216, behavior: 'instant' })
  })
  await page.mouse.move(720, 450)
  return story
}

test.describe('controlled run chapters', () => {
  test.beforeEach(async ({ page, isMobile }) => {
    test.skip(isMobile, 'Controlled chapters require a fine pointer; touch fallbacks have separate coverage.')
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.emulateMedia({ reducedMotion: 'no-preference' })
  })

  test('a large incoming wheel lands on Parser instead of passing the recording', async ({ page }) => {
    const story = await approachStory(page)
    await page.mouse.wheel(0, 5000)
    await page.waitForTimeout(250)
    const panel = await story.locator('.run-story-sticky').boundingBox()
    expect(panel!.y).toBeGreaterThanOrEqual(95)
    expect(panel!.y).toBeLessThanOrEqual(97)
    await expect(story).toHaveAttribute('data-stage', '0')
    await expect(story).toHaveAttribute('data-transitioning', 'false')
  })
})

async function enterStory(page: Page) {
  const story = await approachStory(page)
  await page.mouse.wheel(0, 5000)
  await expect(story).toHaveAttribute('data-phase', 'ready')
  await expect(story).toHaveAttribute('data-stage', '0')
  return story
}

async function ready(story: Locator, stage: number) {
  await expect(story).toHaveAttribute('data-phase', 'ready')
  await expect(story).toHaveAttribute('data-stage', String(stage))
  await expect(story).toHaveAttribute('data-transitioning', 'false')
}

async function beginSamples(story: Locator) {
  await story.evaluate(element => {
    const root = element as HTMLElement & { samples?: { time: number; y: number; phase: string; stage: string }[] }
    root.samples = []
    const start = performance.now()
    const sample = () => {
      root.samples!.push({ time: performance.now() - start, y: element.querySelector('.run-story-sticky')!.getBoundingClientRect().top, phase: root.dataset.phase ?? '', stage: root.dataset.stage ?? '' })
      if (performance.now() - start < 1500) requestAnimationFrame(sample)
    }
    requestAnimationFrame(sample)
  })
}

async function samples(story: Locator) {
  return story.evaluate(element => (element as HTMLElement & { samples: { time: number; y: number; phase: string; stage: string }[] }).samples)
}

test.describe('controlled chapter input', () => {
  test.beforeEach(async ({ page, isMobile }) => {
    test.skip(isMobile, 'These gestures require a fine pointer; touch chapters are covered separately.')
    await page.route('https://vercel.live/**', route => route.abort())
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.emulateMedia({ reducedMotion: 'no-preference' })
  })

  test('small pulls accumulate and reversing direction discards previous intent', async ({ page }) => {
    const story = await enterStory(page)
    for (const delta of [80, -40, 100]) {
      await page.mouse.wheel(0, delta)
      await page.waitForTimeout(50)
      await ready(story, 0)
    }
    await page.mouse.wheel(0, 59)
    await page.waitForTimeout(50)
    await ready(story, 0)
    await page.mouse.wheel(0, 1)
    await expect(story).toHaveAttribute('data-transitioning', 'true')
    await ready(story, 1)
  })

  test('large repeated wheels keep the panel pinned until one transition and settled beat finish', async ({ page }) => {
    const story = await enterStory(page)
    await beginSamples(story)
    await page.mouse.wheel(0, 160)
    await expect(story).toHaveAttribute('data-transitioning', 'true')
    for (const delta of [5000, -5000, 5000]) {
      await page.waitForTimeout(200)
      await page.mouse.wheel(0, delta)
    }
    await expect.poll(() => story.getAttribute('data-phase'), { intervals: [10, 20, 50] }).toBe('settling')
    await page.mouse.wheel(0, 5000)
    await ready(story, 1)
    const frames = await samples(story)
    const moving = frames.filter(frame => frame.phase === 'transitioning')
    const settling = frames.filter(frame => frame.phase === 'settling')
    expect(moving.length).toBeGreaterThan(5)
    expect(moving.at(-1)!.time - moving[0]!.time).toBeGreaterThanOrEqual(850)
    expect(settling.length).toBeGreaterThan(1)
    for (const frame of [...moving, ...settling]) expect(frame.y).toBeGreaterThanOrEqual(95)
    for (const frame of [...moving, ...settling]) expect(frame.y).toBeLessThanOrEqual(97)
    await page.waitForTimeout(400)
    await ready(story, 1)
    await page.mouse.wheel(0, 159)
    await page.waitForTimeout(60)
    await ready(story, 1)
    await page.mouse.wheel(0, 1)
    await ready(story, 2)
  })

  test('decaying momentum is discarded during the transition and never queues another chapter', async ({ page }) => {
    const story = await enterStory(page)
    await page.mouse.wheel(0, 220)
    for (const delta of [140, 100, 70, 45, 25, 10, 2]) {
      await page.waitForTimeout(70)
      await page.mouse.wheel(0, delta)
    }
    await ready(story, 1)
    await page.waitForTimeout(500)
    await ready(story, 1)
  })

  test('fresh sustained input advances through completed adjacent chapters and then leaves', async ({ page }) => {
    const story = await enterStory(page)
    for (const stage of [1, 2, 3]) {
      await page.mouse.wheel(0, 180)
      await expect(story).toHaveAttribute('data-stage', String(stage))
      await expect(story).toHaveAttribute('data-transitioning', 'true')
      for (let i = 0; i < 5; i++) {
        await page.waitForTimeout(100)
        await page.mouse.wheel(0, 180)
        await expect(story).toHaveAttribute('data-stage', String(stage))
      }
      await ready(story, stage)
    }
    const atVerdict = await page.evaluate(() => scrollY)
    await page.mouse.wheel(0, 300)
    await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(atVerdict + 100)
    await expect(story).toHaveAttribute('data-transitioning', 'false')
  })

  test('continuous scrolling still completes every chapter before advancing again', async ({ page }) => {
    const story = await enterStory(page)
    const capture = story.evaluate(async element => {
      const root = element as HTMLElement
      const frames: { time: number; stage: string; phase: string; top: number }[] = []
      const started = performance.now()
      await new Promise<void>(resolve => {
        const sample = () => {
          frames.push({ time: performance.now() - started, stage: root.dataset.stage!, phase: root.dataset.phase!, top: element.querySelector('.run-story-sticky')!.getBoundingClientRect().top })
          if (performance.now() - started < 4400) requestAnimationFrame(sample)
          else resolve()
        }
        requestAnimationFrame(sample)
      })
      return frames
    })
    for (let i = 0; i < 38; i++) {
      await page.mouse.wheel(0, 220)
      await page.waitForTimeout(90)
    }
    const frames = await capture
    const moving = frames.filter(frame => frame.phase === 'transitioning')
    expect([...new Set(moving.map(frame => frame.stage))]).toEqual(['1', '2', '3'])
    for (const stage of ['1', '2', '3']) {
      const chapter = moving.filter(frame => frame.stage === stage)
      expect(chapter.at(-1)!.time - chapter[0]!.time).toBeGreaterThanOrEqual(850)
      expect(chapter.every(frame => frame.top >= 95 && frame.top <= 97)).toBe(true)
    }
  })

  test('reverse input moves one chapter after settlement and can exit above Parser', async ({ page }) => {
    const story = await enterStory(page)
    await story.getByRole('button', { name: 'Tests', exact: true }).click()
    await ready(story, 2)
    await page.mouse.move(720, 450)
    for (const stage of [1, 0]) {
      await page.mouse.wheel(0, -160)
      await expect(story).toHaveAttribute('data-transitioning', 'true')
      await ready(story, stage)
    }
    const atParser = await page.evaluate(() => scrollY)
    await page.mouse.wheel(0, -300)
    await expect.poll(() => page.evaluate(() => scrollY)).toBeLessThan(atParser - 100)
  })

  test('chapter controls select immediately and do not queue animation', async ({ page }) => {
    const story = await enterStory(page)
    await page.mouse.wheel(0, 160)
    await expect(story).toHaveAttribute('data-transitioning', 'true')
    const verdict = story.getByRole('button', { name: 'Verdict', exact: true })
    await verdict.click()
    await ready(story, 3)
    await expect(verdict).toBeFocused()
    await expect(story).toHaveAttribute('data-visual-progress', '0.920')
    await page.waitForTimeout(1100)
    await ready(story, 3)
  })

  test('Skip animation exits mid-transition and focuses the run details', async ({ page }) => {
    const story = await enterStory(page)
    await page.mouse.wheel(0, 160)
    await expect(story).toHaveAttribute('data-transitioning', 'true')
    await story.getByRole('button', { name: 'Skip animation', exact: true }).click()
    const summary = story.locator('summary').filter({ hasText: /^Inspect run details/ })
    await expect(summary).toBeFocused()
    await expect(summary).toBeInViewport()
    await expect(story).toHaveAttribute('data-transitioning', 'false')
    await expect(story).toHaveAttribute('data-phase', /bypass|outside/)
    await summary.press('Enter')
    await expect(story.getByTestId('recorded-run-timeline')).toBeVisible()
  })

  test('Escape releases scrolling during an unfinished transition', async ({ page }) => {
    const story = await enterStory(page)
    await page.mouse.wheel(0, 160)
    await expect(story).toHaveAttribute('data-transitioning', 'true')
    await page.keyboard.press('Escape')
    await expect(story).toHaveAttribute('data-transitioning', 'false')
    await expect(story).toHaveAttribute('data-phase', 'bypass')
    const top = await page.evaluate(() => scrollY)
    await page.mouse.wheel(0, 400)
    await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(top + 200)
  })

  test('page keys advance chapters while repeats during a transition are discarded', async ({ page }) => {
    const story = await enterStory(page)
    await page.keyboard.down('PageDown')
    await expect(story).toHaveAttribute('data-transitioning', 'true')
    for (let i = 0; i < 4; i++) await page.keyboard.down('PageDown')
    await page.keyboard.up('PageDown')
    await ready(story, 1)
    await page.waitForTimeout(250)
    await ready(story, 1)
    await page.keyboard.press('Space')
    await ready(story, 2)
    await page.keyboard.press('PageUp')
    await ready(story, 1)
  })

  test('Tab can leave the section and releases an unfinished transition', async ({ page }) => {
    const story = await enterStory(page)
    await page.mouse.wheel(0, 160)
    await expect(story).toHaveAttribute('data-transitioning', 'true')
    await story.evaluate(element => {
      const link = document.createElement('a')
      link.href = '#experiment'
      link.textContent = 'Next section test link'
      element.after(link)
      element.querySelector<HTMLElement>('summary')!.focus({ preventScroll: true })
    })
    await page.keyboard.press('Tab')
    await expect(page.getByRole('link', { name: 'Next section test link' })).toBeFocused()
    await expect(story).toHaveAttribute('data-transitioning', 'false')
    await expect(story).toHaveAttribute('data-phase', /bypass|outside/)
  })

  test('modified Arrow and Page keys stay native while Shift+Space steps backward', async ({ page }) => {
    const story = await enterStory(page)
    for (const key of ['ArrowDown', 'ArrowUp', 'PageDown', 'PageUp']) {
      const allowed = await page.evaluate(key => document.body.dispatchEvent(new KeyboardEvent('keydown', { key, shiftKey: true, bubbles: true, cancelable: true })), key)
      expect(allowed).toBe(true)
      await ready(story, 0)
    }
    await story.getByRole('button', { name: 'Sandbox', exact: true }).click()
    await page.evaluate(() => (document.activeElement as HTMLElement)?.blur())
    await page.keyboard.press('Shift+Space')
    await expect(story).toHaveAttribute('data-transitioning', 'true')
    await ready(story, 0)
  })

  for (const navigation of ['hashchange', 'popstate']) {
    test(`${navigation} releases a transition even when the URL change does not scroll`, async ({ page }) => {
      const story = await enterStory(page)
      await page.mouse.wheel(0, 160)
      await expect(story).toHaveAttribute('data-transitioning', 'true')
      const top = await page.evaluate(() => scrollY)
      if (navigation === 'hashchange') await page.evaluate(() => { location.hash = 'motion-test-missing-target' })
      else await page.evaluate(() => { history.pushState({ motionTest: true }, '', location.href); history.back() })
      await expect(story).toHaveAttribute('data-transitioning', 'false')
      await expect(story).toHaveAttribute('data-phase', 'bypass')
      expect(await page.evaluate(() => scrollY)).toBe(top)
      await page.mouse.wheel(0, 300)
      await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(top + 100)
    })
  }

  test('Home and End retain native document navigation', async ({ page }) => {
    const story = await enterStory(page)
    await page.mouse.wheel(0, 160)
    await page.keyboard.press('End')
    await expect(page.getByRole('contentinfo')).toBeInViewport()
    await expect(story).toHaveAttribute('data-transitioning', 'false')
    await page.keyboard.press('Home')
    await expect.poll(() => page.evaluate(() => scrollY)).toBeLessThan(2)
  })

  test('explicit document scrolling bypasses and settles without pulling the visitor back', async ({ page }) => {
    const story = await enterStory(page)
    await page.mouse.wheel(0, 160)
    await expect(story).toHaveAttribute('data-transitioning', 'true')
    await page.evaluate(() => scrollBy({ top: 350, behavior: 'instant' }))
    const destination = await page.evaluate(() => scrollY)
    await expect(story).toHaveAttribute('data-transitioning', 'false')
    await expect(story).toHaveAttribute('data-phase', 'bypass')
    await page.waitForTimeout(1200)
    expect(await page.evaluate(() => scrollY)).toBe(destination)
  })

  test('a noncancelable wheel releases the sequence immediately', async ({ page }) => {
    const story = await enterStory(page)
    await page.mouse.wheel(0, 160)
    await expect(story).toHaveAttribute('data-transitioning', 'true')
    await story.dispatchEvent('wheel', { deltaY: 250, cancelable: false, bubbles: true })
    await expect(story).toHaveAttribute('data-phase', 'bypass')
    await expect(story).toHaveAttribute('data-transitioning', 'false')
    const top = await page.evaluate(() => scrollY)
    await page.mouse.wheel(0, 300)
    await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(top + 100)
  })

  test('line and page wheel units trigger one adjacent chapter', async ({ page }) => {
    const story = await enterStory(page)
    await story.dispatchEvent('wheel', { deltaY: 9, deltaMode: 1, cancelable: true, bubbles: true })
    await ready(story, 0)
    await story.dispatchEvent('wheel', { deltaY: 1, deltaMode: 1, cancelable: true, bubbles: true })
    await ready(story, 1)
    await story.dispatchEvent('wheel', { deltaY: 1, deltaMode: 2, cancelable: true, bubbles: true })
    await ready(story, 2)
  })

  test('zoom and horizontal gestures remain uncanceled', async ({ page }) => {
    const story = await enterStory(page)
    for (const init of [{ deltaY: 300, ctrlKey: true }, { deltaY: 300, metaKey: true }, { deltaX: 400, deltaY: 100 }]) {
      await story.getByRole('button', { name: 'Parser', exact: true }).click()
      const allowed = await story.evaluate((element, init) => element.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, ...init })), init)
      expect(allowed).toBe(true)
      await expect(story).toHaveAttribute('data-stage', '0')
      await expect(story).toHaveAttribute('data-transitioning', 'false')
    }
  })

  test('nested scrolling and editable input keep their native controls', async ({ page }) => {
    const story = await enterStory(page)
    await story.evaluate(element => {
      const nested = document.createElement('div')
      nested.id = 'nested-scroll-fixture'
      nested.style.cssText = 'position:fixed;z-index:100;left:20px;top:160px;width:220px;height:100px;overflow:auto;background:white'
      nested.innerHTML = '<div style="height:900px"><textarea aria-label="Motion test input"></textarea></div>'
      element.appendChild(nested)
    })
    await page.mouse.move(200, 240)
    await page.mouse.wheel(0, 300)
    await expect.poll(() => page.locator('#nested-scroll-fixture').evaluate(element => element.scrollTop)).toBeGreaterThan(0)
    await expect(story).toHaveAttribute('data-stage', '0')
    await expect(story).toHaveAttribute('data-transitioning', 'false')
    const input = page.getByRole('textbox', { name: 'Motion test input' })
    await input.fill('Keep this text editable')
    await input.press('Home')
    await input.press('ArrowDown')
    await input.press('Space')
    await expect(input).toHaveValue(/ /)
    await expect(story).toHaveAttribute('data-stage', '0')
  })

  test('a stalled main thread settles and releases the deadline instead of trapping scroll', async ({ page }) => {
    const story = await enterStory(page)
    await page.mouse.wheel(0, 160)
    await expect(story).toHaveAttribute('data-transitioning', 'true')
    await page.evaluate(() => {
      const end = performance.now() + 1650
      while (performance.now() < end) { /* Simulate an unresponsive browser task. */ }
    })
    await expect(story).toHaveAttribute('data-transitioning', 'false')
    await expect(story).toHaveAttribute('data-phase', 'bypass')
    await expect(story).toHaveAttribute('data-stage', '1')
    const top = await page.evaluate(() => scrollY)
    await page.mouse.wheel(0, 400)
    await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(top + 200)
  })

  test('an unexpected controller exception restores readable chapters and native scrolling', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    const story = await approachStory(page)
    await page.evaluate(() => {
      const original = window.scrollTo.bind(window)
      window.scrollTo = () => {
        window.scrollTo = original
        throw new Error('Injected scroll API failure')
      }
    })
    await page.mouse.wheel(0, 5000)
    await expect(story).toHaveAttribute('data-mode', 'static')
    for (const chapter of await story.locator('.run-story-chapter').all()) await expect(chapter).toBeVisible()
    const top = await page.evaluate(() => scrollY)
    await page.mouse.wheel(0, 350)
    await expect.poll(() => page.evaluate(() => scrollY)).toBeGreaterThan(top + 100)
    expect(errors).toEqual([])
  })

  test('touch input on a fine-pointer device exposes static chapters', async ({ page }) => {
    const story = await enterStory(page)
    await page.mouse.wheel(0, 160)
    await story.dispatchEvent('pointerdown', { pointerType: 'touch', bubbles: true })
    await expect(story).toHaveAttribute('data-mode', 'static')
    await expect(story).toHaveAttribute('data-transitioning', 'false')
    for (const chapter of await story.locator('.run-story-chapter').all()) await expect(chapter).toBeVisible()
    await page.mouse.wheel(0, 300)
    await expect(story).toHaveAttribute('data-mode', 'static')
  })
})

test('coarse-pointer devices keep all chapters in normal flow even at desktop widths', async ({ page, isMobile }) => {
  test.skip(!isMobile, 'The mobile browser projects supply a real coarse-pointer context.')
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.goto('/')
  const story = page.getByTestId('run-story')
  await expect(story).toHaveAttribute('data-mode', 'static')
  for (const chapter of await story.locator('.run-story-chapter').all()) await expect(chapter).toBeVisible()
  await expect(story.getByRole('button', { name: 'Skip animation' })).toBeHidden()
})
