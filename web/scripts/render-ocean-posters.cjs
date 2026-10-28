const path = require('node:path')
const fs = require('node:fs/promises')
const { build } = require('esbuild')
const { chromium } = require('playwright')
const sharp = require('sharp')

async function main() {
  const root = path.resolve(__dirname, '..')
  const output = path.join(root, 'public/ocean')
  await fs.mkdir(output, { recursive: true })
  const font = await fs.readFile(path.join(root, 'app/fonts/GeistMono-latin.woff2'))
  const bundle = await build({
    stdin: {
      contents: `import { AsciiRenderer } from './vendor/ascii-sharks/renderer';
        import { createOceanScene } from './lib/ocean-scene';
        window.paintPoster = (width, height) => {
          let seed = 42;
          Math.random = () => ((seed = Math.imul(1664525, seed) + 1013904223 >>> 0) / 4294967296);
          const canvas = document.querySelector('canvas');
          const renderer = new AsciiRenderer(canvas, { sharkGlyphs: false });
          renderer.setFontFamily('OceanMono');
          renderer.resize(width, height, 1);
          const world = createOceanScene(width, height, renderer.cellWidth, renderer.cellHeight);
          renderer.render(world, 1 / 60);
          return canvas.toDataURL('image/png');
        };`,
      resolveDir: root,
      loader: 'ts',
    },
    bundle: true, write: false, format: 'iife', platform: 'browser',
  })
  const browser = await chromium.launch()
  try {
    for (const [name, width, height] of [['desktop', 1440, 823], ['mobile', 390, 1120]]) {
      const page = await browser.newPage({ viewport: { width, height } })
      await page.setContent(`<style>@font-face{font-family:OceanMono;src:url(data:font/woff2;base64,${font.toString('base64')})}body{margin:0}canvas{display:block}</style><canvas></canvas>`)
      await page.evaluate(() => document.fonts.load('600 16px OceanMono'))
      await page.addScriptTag({ content: bundle.outputFiles[0].text })
      const data = await page.evaluate(({ width, height }) => window.paintPoster(width, height), { width, height })
      const file = path.join(output, `${name}.webp`)
      await sharp(Buffer.from(data.split(',')[1], 'base64')).webp({ quality: 82, effort: 6 }).toFile(file)
      console.log(`${name}: ${(await fs.stat(file)).size} bytes`)
      await page.close()
    }
  } finally { await browser.close() }
}
main().catch(error => { console.error(error); process.exitCode = 1 })
