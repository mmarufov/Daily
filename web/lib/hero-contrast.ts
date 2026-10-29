type RGB = readonly [number, number, number]
const DARK_PAPER: RGB = [23, 23, 23], LIGHT_PAPER: RGB = [250, 250, 249]
const linear = Array.from({ length: 256 }, (_, value) => {
  const channel = value / 255
  return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4
})
const luminance = (rgb: RGB) => linear[Math.round(rgb[0])]! * .2126 + linear[Math.round(rgb[1])]! * .7152 + linear[Math.round(rgb[2])]! * .0722
const ratio = (a: number, b: number) => (Math.max(a, b) + .05) / (Math.min(a, b) + .05)
const darkLuminance = 0, lightLuminance = 1

export function buildContrastPaths(pixels: Uint8ClampedArray, columns: number, rows: number,
  width: number, height: number, paper: RGB, ink: RGB, darkTheme: boolean) {
  const paths = ['', ''], inkLuminance = luminance(ink)
  const x = width / columns, y = height / rows
  const number = (value: number) => +value.toFixed(2)
  const colors = paper.map(channel => linear.map((_, value) => {
    const source = value / 255
    return darkTheme ? 255 * source + channel * (1 - source) : channel * (1 - source)
  }))
  for (let row = 0; row < rows; row++) {
    let previous = -1, start = 0
    for (let column = 0; column <= columns; column++) {
      let choice = -1
      if (column < columns) {
        const offset = (row * columns + column) * 4, alpha = pixels[offset + 3]! / 255
        let background = 0
        for (let channel = 0; channel < 3; channel++) {
          const blended = colors[channel]![pixels[offset + channel]!]!
          const value = Math.round(paper[channel]! + (blended - paper[channel]!) * alpha)
          background += linear[value]! * (channel === 0 ? .2126 : channel === 1 ? .7152 : .0722)
        }
        if (ratio(background, inkLuminance) < 4.5) {
          choice = ratio(background, lightLuminance) > ratio(background, darkLuminance) ? 0 : 1
        }
      }
      if (choice === previous) continue
      if (previous >= 0) paths[previous] += `M${number(start * x)} ${number(row * y)}h${number((column - start) * x)}v${number(y)}h-${number((column - start) * x)}Z`
      start = column
      previous = choice
    }
  }
  return { light: `path("${paths[0] || 'M0 0'}")`, dark: `path("${paths[1] || 'M0 0'}")` }
}

export function mountHeroContrast(canvas: HTMLCanvasElement) {
  const noop = { paint() {}, setReady(_ready: boolean) {}, destroy() {} }
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function' || typeof canvas.closest !== 'function'
    || typeof ResizeObserver !== 'function' || typeof IntersectionObserver !== 'function') return noop
  const scene = canvas.closest<HTMLElement>('.hero-scene')
  const paragraph = scene?.querySelector<HTMLElement>('.hero-description')
  const light = paragraph?.querySelector<HTMLElement>('.hero-description-light')
  const dark = paragraph?.querySelector<HTMLElement>('.hero-description-dark')
  const poster = scene?.querySelector<HTMLImageElement>('.shark-still img')
  if (!scene || !paragraph || !light || !dark || !poster) return noop
  let sample: HTMLCanvasElement, context: CanvasRenderingContext2D | null
  let theme: MediaQueryList, forced: MediaQueryList
  try {
    sample = document.createElement('canvas')
    context = sample.getContext('2d', { willReadFrequently: true })
    theme = window.matchMedia('(prefers-color-scheme: dark)')
    forced = window.matchMedia('(forced-colors: active)')
  } catch { return noop }
  if (!context) return noop
  let ready = false, visible = false, disposed = false, failed = false, dirty = true, printing = false
  let geometry = { left: 0, top: 0, width: 0, height: 0, sceneWidth: 0, sceneHeight: 0 }
  let paper: RGB = LIGHT_PAPER, ink: RGB = DARK_PAPER
  let paths = { light: '', dark: '' }
  const removers: Array<() => void> = []
  const clear = () => {
    light.style.clipPath = dark.style.clipPath = 'path("M0 0")'
    paths = { light: '', dark: '' }
  }
  const readColor = (value: string, fallback: RGB): RGB => {
    const channels = value.match(/[\d.]+/g)?.slice(0, 3).map(Number)
    return channels?.length === 3 ? channels as unknown as RGB : fallback
  }
  function paint() {
    if (disposed || failed || !visible || document.hidden || printing || forced.matches) return
    try {
      if (dirty) {
        const bounds = canvas.getBoundingClientRect(), text = paragraph!.getBoundingClientRect()
        geometry = { left: text.left - bounds.left, top: text.top - bounds.top, width: text.width, height: text.height, sceneWidth: bounds.width, sceneHeight: bounds.height }
        paper = readColor(getComputedStyle(scene!).backgroundColor, theme.matches ? DARK_PAPER : LIGHT_PAPER)
        ink = readColor(getComputedStyle(paragraph!).color, theme.matches ? LIGHT_PAPER : DARK_PAPER)
        sample.width = Math.ceil(text.width / 2)
        sample.height = Math.ceil(text.height / 2)
        dirty = false
      }
      const g = geometry
      if (!g.width || !g.height || !g.sceneWidth || !g.sceneHeight) { clear(); return }
      const source = ready ? canvas : poster!
      if (!ready && (!poster!.complete || !poster!.naturalWidth)) { clear(); return }
      const sx = ready ? canvas.width / g.sceneWidth : 1 / Math.max(g.sceneWidth / poster!.naturalWidth, g.sceneHeight / poster!.naturalHeight)
      const sy = ready ? canvas.height / g.sceneHeight : sx
      const crop = ready ? 0 : (poster!.naturalWidth - g.sceneWidth * sx) / 2
      context!.clearRect(0, 0, sample.width, sample.height)
      context!.drawImage(source, g.left * sx + crop, g.top * sy, g.width * sx, g.height * sy, 0, 0, sample.width, sample.height)
      const next = buildContrastPaths(context!.getImageData(0, 0, sample.width, sample.height).data,
        sample.width, sample.height, g.width, g.height, paper, ink, theme.matches)
      if (next.light !== paths.light) light!.style.clipPath = next.light
      if (next.dark !== paths.dark) dark!.style.clipPath = next.dark
      paths = next
    } catch { failed = true; clear() }
  }
  const invalidate = () => { if (disposed) return; dirty = true; clear(); paint() }
  const listen = (target: EventTarget, event: string, callback: () => void) => {
    target.addEventListener(event, callback)
    removers.push(() => target.removeEventListener(event, callback))
  }
  let resize: ResizeObserver | undefined, intersection: IntersectionObserver | undefined
  try {
    resize = new ResizeObserver(invalidate)
    intersection = new IntersectionObserver(entries => { visible = entries[0]?.isIntersecting ?? false; if (visible) paint() })
    resize.observe(scene)
    resize.observe(paragraph)
    intersection.observe(scene)
    listen(window, 'resize', invalidate)
    listen(theme, 'change', invalidate)
    listen(forced, 'change', invalidate)
    listen(poster, 'load', invalidate)
    listen(document, 'visibilitychange', () => { if (!document.hidden) paint() })
    listen(window, 'beforeprint', () => { printing = true; clear() })
    listen(window, 'afterprint', () => { printing = false; invalidate() })
    void document.fonts?.ready.then(() => { if (!disposed) invalidate() })
  } catch { failed = true; resize?.disconnect(); intersection?.disconnect(); removers.splice(0).forEach(remove => remove()); clear() }
  return {
    paint,
    setReady(value: boolean) { if (disposed || value === ready) return; ready = value; clear(); paint() },
    destroy() { disposed = true; resize?.disconnect(); intersection?.disconnect(); removers.forEach(remove => remove()); clear() },
  }
}
