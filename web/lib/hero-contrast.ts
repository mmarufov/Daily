// The upstream grid peaks at 14/255. A small margin also excludes poster compression noise.
const WATER_FLOOR = 18

export function buildOverlapPath(pixels: Uint8ClampedArray, columns: number, rows: number,
  width: number, height: number) {
  let path = ''
  const x = width / columns, y = height / rows
  const number = (value: number) => +value.toFixed(2)
  for (let row = 0; row < rows; row++) {
    let start = -1
    for (let column = 0; column <= columns; column++) {
      const offset = (row * columns + column) * 4
      const occupied = column < columns && Math.max(pixels[offset]!, pixels[offset + 1]!, pixels[offset + 2]!)
        * pixels[offset + 3]! / 255 > WATER_FLOOR
      if (occupied && start < 0) start = column
      if (!occupied && start >= 0) {
        path += `M${number(start * x)} ${number(row * y)}h${number((column - start) * x)}v${number(y)}h-${number((column - start) * x)}Z`
        start = -1
      }
    }
  }
  return `path("${path || 'M0 0'}")`
}

export function mountHeroContrast(canvas: HTMLCanvasElement) {
  const targets = typeof canvas.closest === 'function'
    ? canvas.closest('.hero-scene')?.querySelectorAll<HTMLElement>('[data-hero-overlap]') : undefined
  const masks = Array.from(targets ?? [], target => mountTextOverlap(canvas, target))
  return {
    paint() { masks.forEach(mask => mask.paint()) },
    setReady(ready: boolean) { masks.forEach(mask => mask.setReady(ready)) },
    destroy() { masks.forEach(mask => mask.destroy()) },
  }
}

function mountTextOverlap(canvas: HTMLCanvasElement, target: HTMLElement) {
  const noop = { paint() {}, setReady(_ready: boolean) {}, destroy() {} }
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function' || typeof canvas.closest !== 'function'
    || typeof ResizeObserver !== 'function' || typeof IntersectionObserver !== 'function') return noop
  const scene = canvas.closest<HTMLElement>('.hero-scene')
  const accent = target.querySelector<HTMLElement>('.hero-overlap-ink')
  const poster = scene?.querySelector<HTMLImageElement>('.shark-still img')
  if (!scene || !accent || !poster) return noop
  let sample: HTMLCanvasElement, context: CanvasRenderingContext2D | null
  let forced: MediaQueryList
  try {
    sample = document.createElement('canvas')
    context = sample.getContext('2d', { willReadFrequently: true })
    forced = window.matchMedia('(forced-colors: active)')
  } catch { return noop }
  if (!context) return noop
  let ready = false, visible = false, disposed = false, failed = false, dirty = true, printing = false
  let geometry = { left: 0, top: 0, width: 0, height: 0, sceneWidth: 0, sceneHeight: 0 }
  let path = ''
  const removers: Array<() => void> = []
  const clear = () => {
    accent.style.clipPath = 'path("M0 0")'
    path = ''
  }
  function paint() {
    if (disposed || failed || !visible || document.hidden || printing || forced.matches) return
    try {
      if (dirty) {
        const bounds = canvas.getBoundingClientRect(), text = target.getBoundingClientRect()
        geometry = { left: text.left - bounds.left, top: text.top - bounds.top, width: text.width, height: text.height, sceneWidth: bounds.width, sceneHeight: bounds.height }
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
      const next = buildOverlapPath(context!.getImageData(0, 0, sample.width, sample.height).data,
        sample.width, sample.height, g.width, g.height)
      if (next !== path) accent!.style.clipPath = next
      path = next
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
    resize.observe(target)
    const copy = target.closest('.hero-copy')
    if (copy) resize.observe(copy)
    intersection.observe(scene)
    listen(window, 'resize', invalidate)
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
