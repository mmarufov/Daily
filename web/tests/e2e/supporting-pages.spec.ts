import { expect, test } from './fixtures'

const PAGES = ['/lab', '/reader?profile=ray', '/evidence', '/engineering'] as const

for (const mode of ['no-script', 'reduced-motion'] as const) {
  test.describe(`${mode} supporting disclosures`, () => {
    test.use(mode === 'no-script' ? { javaScriptEnabled: false } : { reducedMotion: 'reduce' })
    for (const route of PAGES) {
      test(`${route} exposes retained details without changing the URL`, async ({ page }) => {
        await page.goto(route)
        const url = page.url()
        const disclosures = page.locator('.support-page details')
        const count = await disclosures.count()
        expect(count).toBeGreaterThan(0)
        for (let i = 0; i < count; i++) {
          const details = disclosures.nth(i)
          const summary = details.locator(':scope > summary')
          await expect(summary).toBeVisible()
          await expect(details).not.toHaveAttribute('open')
          await summary.click()
          await expect(details).toHaveAttribute('open', '')
          expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
        }
        for (let i = count - 1; i >= 0; i--) {
          const details = disclosures.nth(i)
          await details.locator(':scope > summary').click()
          await expect(details).not.toHaveAttribute('open')
        }
        expect(page.url()).toBe(url)
      })
    }
  })
}

test('Reader retains recording metadata while removing duplicate and unfinished sections', async ({ page }) => {
  await page.goto('/reader?profile=ray')
  await expect(page.getByText('Profiles are evaluation fixtures.')).toBeVisible()
  await expect(page.getByText('The same corpus, nine other readers')).toHaveCount(0)
  await expect(page.getByText('Live mode', { exact: true })).toHaveCount(0)
  await expect(page.getByRole('navigation', { name: 'Reader fixture' }).getByRole('link')).toHaveCount(10)
  await expect(page.getByRole('article').getByText('synthetic evaluation story', { exact: true }).first()).toBeVisible()
  await page.locator('summary', { hasText: 'Inspect recording' }).click()
  await expect(page.getByText('SHA-256', { exact: true })).toBeVisible()
  await expect(page.getByText('prod-llm__2026-09-02__47edb50', { exact: true })).toBeVisible()
})

test('Case study retains all three exact trace destinations with one example initially visible', async ({ page }) => {
  await page.goto('/engineering')
  await expect(page).toHaveTitle('Case study · Daily Lab')
  const traces = page.getByRole('link', { name: 'Inspect story trace', exact: true })
  await expect(traces).toHaveCount(1)
  await expect(traces.first()).toHaveAttribute('href', /story=a00407/)
  await page.locator('summary', { hasText: 'More recorded examples' }).click()
  await expect(traces).toHaveCount(3)
  await expect(traces.nth(1)).toHaveAttribute('href', /story=n-dil-02/)
  await expect(traces.nth(2)).toHaveAttribute('href', /story=a00037/)
  const panel = page.getByTestId('guard-experiment-panel')
  await expect(panel.getByRole('link', { name: 'Read the investigation' })).toHaveCount(0)
  await expect(panel.getByText(/Historical working-tree experiment/)).toBeVisible()
})

test('collapsed fixture results still filter the selected run', async ({ page }) => {
  await page.goto('/evidence?run=prod-llm__2026-09-02__47edb50')
  const details = page.locator('details').filter({ has: page.locator('summary', { hasText: 'Inspect fixture results' }) })
  await details.locator('summary').click()
  await details.getByRole('link').filter({ hasText: 'Ray' }).click()
  await expect(page).toHaveURL(url => url.searchParams.get('run') === 'prod-llm__2026-09-02__47edb50' && url.searchParams.get('persona') === 'ray')
})
