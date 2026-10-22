import type { Page } from '@playwright/test'
import { expect, test } from './fixtures'

async function enterStory(page: Page) {
  await page.goto('/')
  const story = page.getByTestId('run-story')
  await expect(story).toHaveAttribute('data-mode', 'scroll')
  await story.locator('.run-story-track').evaluate(track => {
    window.scrollTo({ top: scrollY + track.getBoundingClientRect().top - 216, behavior: 'instant' })
  })
  await page.mouse.move(720, 450)
  await page.mouse.wheel(0, 5000)
  await expect(story).toHaveAttribute('data-phase', 'ready')
  return story
}

test.describe('wheel targets inside the chapter scene', () => {
  test.beforeEach(async ({ page, isMobile }) => {
    test.skip(isMobile, 'Touch devices use normal document flow.')
    await page.setViewportSize({ width: 1440, height: 900 })
    await page.emulateMedia({ reducedMotion: 'no-preference' })
  })

  for (const target of ['chapter button', 'run link'] as const) {
    test(`hovering a ${target} cannot bypass an unfinished transition`, async ({ page }) => {
      const story = await enterStory(page)
      await page.mouse.wheel(0, 160)
      await expect(story).toHaveAttribute('data-transitioning', 'true')
      const control = target === 'chapter button'
        ? story.getByRole('button', { name: 'Tests', exact: true })
        : story.getByRole('link', { name: 'Run the default parser', exact: true }).first()
      await control.hover()
      await page.mouse.wheel(0, 5000)
      await page.waitForTimeout(200)
      await expect(story).toHaveAttribute('data-stage', '1')
      await expect(story).toHaveAttribute('data-transitioning', 'true')
      const panel = await story.locator('.run-story-sticky').boundingBox()
      expect(panel!.y).toBeGreaterThanOrEqual(95)
      expect(panel!.y).toBeLessThanOrEqual(97)
      await expect(story).toHaveAttribute('data-phase', 'ready')
      await expect(story).toHaveAttribute('data-stage', '1')
    })

    test(`wheel intent over a ${target} advances the settled scene`, async ({ page }) => {
      const story = await enterStory(page)
      const control = target === 'chapter button'
        ? story.getByRole('button', { name: 'Tests', exact: true })
        : story.getByRole('link', { name: 'Run the default parser', exact: true }).first()
      await control.hover()
      await page.mouse.wheel(0, 160)
      await expect(story).toHaveAttribute('data-transitioning', 'true')
      await expect(story).toHaveAttribute('data-phase', 'ready')
      await expect(story).toHaveAttribute('data-stage', '1')
    })
  }
})
