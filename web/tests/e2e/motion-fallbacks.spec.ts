import type { Locator } from '@playwright/test'

import { expect, test } from './fixtures'

async function holdClosingAnimation(summary: Locator) {
  await summary.evaluate(element => {
    ;(element as HTMLElement).click()
    const animation = element.parentElement!.getAnimations()[0]
    if (!animation) throw new Error('The closing animation did not start')
    // Hold the closing interval so slow test runners exercise the focus race.
    animation.pause()
    animation.currentTime = 100
  })
}

async function finishClosingAnimation(summary: Locator) {
  await summary.evaluate(element => element.parentElement!.getAnimations()[0]!.finish())
  await expect(summary.locator('xpath=..')).toHaveJSProperty('open', false)
}

test.describe('motion fallbacks', () => {
  test.beforeEach(async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' })
  })

  test('closing a disclosure restores focus if its content receives focus during the animation', async ({ page }) => {
    await page.goto('/engineering')
    await page.waitForLoadState('networkidle')
    const summary = page.locator('summary').filter({ hasText: /^Experiment provenance$/ })
    const details = summary.locator('xpath=..')
    await summary.click()
    await expect.poll(() => details.evaluate(element => element.getAnimations().length)).toBe(0)
    await holdClosingAnimation(summary)
    const source = details.getByRole('link', { name: /Inspect summary and source hashes/ })
    await source.focus()
    await expect(source).toBeFocused()
    await finishClosingAnimation(summary)
    await expect(summary).toBeFocused()
    await expect(source).toBeHidden()
  })

  test('closing a disclosure leaves focus outside that disclosure alone', async ({ page }) => {
    await page.goto('/engineering')
    await page.waitForLoadState('networkidle')
    const summary = page.locator('summary').filter({ hasText: /^Experiment provenance$/ })
    const details = summary.locator('xpath=..')
    await summary.click()
    await expect.poll(() => details.evaluate(element => element.getAnimations().length)).toBe(0)
    await holdClosingAnimation(summary)
    const outside = page.getByRole('link', { name: 'Daily', exact: true }).first()
    await outside.focus()
    await finishClosingAnimation(summary)
    await expect(outside).toBeFocused()
  })

  test('disclosures and finding controls work when Web Animations is unavailable', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(Element.prototype, 'animate', { configurable: true, value: undefined })
    })
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await page.goto('/engineering')
    await page.waitForLoadState('networkidle')
    const comparison = page.getByTestId('guard-experiment-panel')
    await comparison.getByRole('button', { name: 'Guard experiment', exact: true }).click()
    await expect(comparison.getByTestId('guard-metric-recall')).toContainText('18.7%')
    const summary = comparison.locator('summary').filter({ hasText: /^Experiment provenance$/ })
    const details = summary.locator('xpath=..')
    await summary.click()
    await expect(details).toHaveJSProperty('open', true)
    await expect(details.getByRole('link', { name: /Inspect summary and source hashes/ })).toBeVisible()
    await summary.click()
    await expect(details).toHaveJSProperty('open', false)
    expect(await details.evaluate(element => (element as HTMLElement).style.overflow)).toBe('')
    expect(errors).toEqual([])
  })
})
