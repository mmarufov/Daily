import { expect, test } from './fixtures'

type ContrastWindow = Window & { contrastShade: string; contrastReads: number }

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference' })
  await page.addInitScript(() => {
    const state = window as ContrastWindow
    state.contrastShade = ''
    state.contrastReads = 0
    const proto = CanvasRenderingContext2D.prototype
    const draw = proto.drawImage, read = proto.getImageData
    proto.drawImage = function (...args: Parameters<typeof draw>) {
      Reflect.apply(draw, this, args)
      if (state.contrastShade && this.canvas instanceof HTMLCanvasElement
        && this.canvas.matches('[data-testid="shark-background"] canvas')) {
        this.save()
        this.resetTransform()
        this.fillStyle = state.contrastShade
        this.fillRect(0, 0, this.canvas.width, this.canvas.height)
        this.restore()
      }
    }
    proto.getImageData = function (...args: Parameters<typeof read>) {
      state.contrastReads++
      return Reflect.apply(read, this, args)
    }
  })
})

for (const theme of ['light', 'dark'] as const) {
  test(`the paragraph responds to dark, light and gray cells in ${theme} mode`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: theme })
    await page.goto('/')
    await expect(page.getByTestId('shark-background')).toHaveAttribute('data-ready', 'true')
    const light = page.locator('.hero-description-light'), dark = page.locator('.hero-description-dark')
    const path = (selector: string) => page.locator(selector).evaluate(el => getComputedStyle(el).clipPath)
    await page.evaluate(() => { (window as ContrastWindow).contrastShade = '#000' })
    await expect.poll(() => path('.hero-description-light')).toMatch(/M\s*0\s*0["') ]*$/)
    await expect.poll(() => path('.hero-description-dark')).toMatch(/M\s*0\s*0["') ]*$/)
    await page.evaluate(() => { (window as ContrastWindow).contrastShade = '#fff' })
    const changed = theme === 'light' ? light : dark
    await expect.poll(() => changed.evaluate(el => el.style.clipPath)).toMatch(/[hHL]/)
    await page.evaluate(() => { (window as ContrastWindow).contrastShade = '#808080' })
    await expect.poll(() => dark.evaluate(el => el.style.clipPath)).toMatch(/[hHL]/)
    await expect(page.locator('.hero-copy')).toHaveCSS('isolation', 'isolate')
    const paragraph = page.locator('.hero-description')
    const text = await paragraph.textContent()
    expect(text?.match(/Daily builds/g)).toHaveLength(1)
    expect((await paragraph.ariaSnapshot()).match(/Daily builds/g)).toHaveLength(1)
    const selected = await paragraph.evaluate(el => {
      const range = document.createRange()
      range.selectNodeContents(el)
      getSelection()!.removeAllRanges()
      getSelection()!.addRange(range)
      return getSelection()!.toString()
    })
    expect(selected).toBe(text)
    await expect(page.getByRole('link', { name: 'Explore the Lab' })).toHaveAttribute('href', '/lab')
  })
}

test('text sampling stops with pause and offscreen drawing', async ({ page }) => {
  await page.goto('/')
  await expect.poll(() => page.evaluate(() => (window as ContrastWindow).contrastReads)).toBeGreaterThan(0)
  await page.getByRole('button', { name: 'Pause background animation' }).click()
  await page.waitForTimeout(100)
  const paused = await page.evaluate(() => (window as ContrastWindow).contrastReads)
  await page.waitForTimeout(250)
  expect(await page.evaluate(() => (window as ContrastWindow).contrastReads)).toBe(paused)
  await page.getByRole('button', { name: 'Play background animation' }).click()
  await expect.poll(() => page.evaluate(() => (window as ContrastWindow).contrastReads)).toBeGreaterThan(paused)
  await page.getByRole('contentinfo').scrollIntoViewIfNeeded()
  await page.waitForTimeout(150)
  const offscreen = await page.evaluate(() => (window as ContrastWindow).contrastReads)
  await page.waitForTimeout(250)
  expect(await page.evaluate(() => (window as ContrastWindow).contrastReads)).toBe(offscreen)
})

test('print and forced colors use the single native paragraph', async ({ page }) => {
  await page.goto('/')
  for (const media of [{ media: 'print' as const }, { media: 'screen' as const, forcedColors: 'active' as const }]) {
    await page.emulateMedia(media)
    await expect(page.locator('.hero-description-light')).toBeHidden()
    await expect(page.locator('.hero-description-dark')).toBeHidden()
    await expect(page.locator('.hero-description')).toBeVisible()
  }
})

test('a text sampling failure leaves the paragraph and swimming scene usable', async ({ page }) => {
  await page.addInitScript(() => {
    CanvasRenderingContext2D.prototype.getImageData = () => { throw new Error('sampling unavailable') }
  })
  await page.goto('/')
  await expect(page.getByTestId('shark-background')).toHaveAttribute('data-ready', 'true')
  const frame = () => page.locator('[data-testid="shark-background"] canvas').evaluate((canvas: HTMLCanvasElement) => canvas.toDataURL())
  const before = await frame()
  await expect.poll(frame).not.toBe(before)
  await expect(page.locator('.hero-description')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Explore the Lab' })).toBeVisible()
})
