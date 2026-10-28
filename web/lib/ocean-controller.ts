import { AsciiRenderer } from '../vendor/ascii-sharks/renderer'
import { createOceanScene, OceanClock, resizeOceanScene } from './ocean-scene'

export function mountOcean(canvas: HTMLCanvasElement, onReady: (ready: boolean) => void) {
  let disposed = false, failed = false, paused = false, visible = false
  let suspended = false, printing = false, needsResize = true
  let ready: boolean | undefined, frameId = 0
  let width = 0, height = 0, density = 0
  let renderer: AsciiRenderer | undefined
  let world: ReturnType<typeof createOceanScene> | undefined
  let intersection: IntersectionObserver | undefined, resize: ResizeObserver | undefined
  const clock = new OceanClock()
  const listeners: Array<() => void> = []

  function report(value: boolean) {
    if (disposed || ready === value) return
    ready = value
    try { onReady(value) } catch { /* The canvas lifecycle must still be released if its owner throws. */ }
  }

  function stop() {
    if (frameId) cancelAnimationFrame(frameId)
    frameId = 0
    clock.reset()
  }

  function release() {
    stop()
    intersection?.disconnect()
    resize?.disconnect()
    listeners.splice(0).forEach(remove => remove())
  }

  const controls = {
    setPaused(value: boolean) {
      if (disposed || failed || paused === value) return
      paused = value
      stop()
      reconcile()
    },
    destroy() {
      if (disposed) return
      disposed = true
      release()
      world = undefined
      renderer = undefined
    },
  }

  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function'
    || typeof IntersectionObserver !== 'function' || typeof ResizeObserver !== 'function'
    || typeof requestAnimationFrame !== 'function') {
    failed = true
    report(false)
    return controls
  }

  const still = window.matchMedia('(prefers-reduced-motion: reduce), (forced-colors: active)')

  function active() {
    return !disposed && !failed && visible && !suspended && !printing && !document.hidden && !still.matches
  }

  function fail() {
    failed = true
    release()
    report(false)
  }

  function measure() {
    if (!needsResize && renderer && world) return true
    const bounds = canvas.getBoundingClientRect()
    const nextWidth = Math.round(bounds.width), nextHeight = Math.round(bounds.height)
    if (nextWidth <= 0 || nextHeight <= 0) return false
    const nextDensity = Math.min(1.5, window.devicePixelRatio || 1)
    renderer ??= new AsciiRenderer(canvas, { sharkGlyphs: false })
    if (nextWidth !== width || nextHeight !== height || nextDensity !== density) {
      renderer.setFontFamily(getComputedStyle(canvas).fontFamily)
      renderer.resize(nextWidth, nextHeight, nextDensity)
      world = world
        ? resizeOceanScene(world, nextWidth, nextHeight, renderer.cellWidth, renderer.cellHeight)
        : createOceanScene(nextWidth, nextHeight, renderer.cellWidth, renderer.cellHeight)
      width = nextWidth
      height = nextHeight
      density = nextDensity
    }
    needsResize = false
    return Boolean(world)
  }

  function paint(steps: number) {
    try {
      if (!active() || !measure() || !renderer || !world) return false
      for (let step = 0; step < steps; step++) world.step(1 / 60)
      renderer.render(world, steps / 60)
      report(true)
      return true
    } catch {
      fail()
      return false
    }
  }

  function frame(now: number) {
    frameId = 0
    if (!active() || paused) { stop(); return }
    const steps = clock.advance(now)
    if (steps !== null && !paint(steps)) { stop(); return }
    frameId = requestAnimationFrame(frame)
  }

  function reconcile() {
    if (!active()) { stop(); return }
    if (paused) {
      if (needsResize) paint(0)
      return
    }
    if (!frameId) frameId = requestAnimationFrame(frame)
  }

  function listen(target: EventTarget, event: string, callback: () => void) {
    target.addEventListener(event, callback)
    listeners.push(() => target.removeEventListener(event, callback))
  }

  try {
    intersection = new IntersectionObserver(entries => {
      const entry = entries[0]
      if (!entry || disposed || failed) return
      visible = entry.isIntersecting
      reconcile()
    })
    resize = new ResizeObserver(() => {
      needsResize = true
      reconcile()
    })
    intersection.observe(canvas)
    resize.observe(canvas)
    listen(window, 'resize', () => { needsResize = true; reconcile() })
    listen(document, 'visibilitychange', reconcile)
    listen(window, 'pagehide', () => { suspended = true; reconcile() })
    listen(window, 'pageshow', () => { suspended = false; needsResize = true; reconcile() })
    listen(window, 'beforeprint', () => { printing = true; reconcile() })
    listen(window, 'afterprint', () => { printing = false; needsResize = true; reconcile() })
    listen(still, 'change', () => {
      stop()
      if (still.matches) report(false)
      else needsResize = true
      reconcile()
    })
    listen(canvas, 'contextlost', fail)
    if (still.matches) report(false)
  } catch {
    fail()
  }

  return controls
}
