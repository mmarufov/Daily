import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mountOcean } from '../../lib/ocean-controller'

const drawing = vi.hoisted(() => ({ render: vi.fn(), resize: vi.fn() }))
vi.mock('../../vendor/ascii-sharks/renderer', () => ({
  AsciiRenderer: class {
    cellWidth = 12
    cellHeight = 18
    setFontFamily() {}
    resize = drawing.resize
    render = drawing.render
  },
}))

function browser() {
  const win = Object.assign(new EventTarget(), { devicePixelRatio: 3 })
  const doc = Object.assign(new EventTarget(), { hidden: false })
  const preference = Object.assign(new EventTarget(), { matches: false })
  const canvas = Object.assign(new EventTarget(), {
    getBoundingClientRect: () => ({ width: 1440, height: 823 }),
  })
  let resize: () => void = () => {}
  let intersection: (entries: Array<{ isIntersecting: boolean }>) => void = () => {}
  const frames = new Map<number, FrameRequestCallback>()
  let id = 0
  vi.stubGlobal('window', Object.assign(win, { matchMedia: () => preference }))
  vi.stubGlobal('document', doc)
  vi.stubGlobal('getComputedStyle', () => ({ fontFamily: 'monospace' }))
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { frames.set(++id, callback); return id })
  vi.stubGlobal('cancelAnimationFrame', (frame: number) => frames.delete(frame))
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) { resize = callback }
    observe() {}
    disconnect() {}
  })
  vi.stubGlobal('IntersectionObserver', class {
    constructor(callback: typeof intersection) { intersection = callback }
    observe() {}
    disconnect() {}
  })
  return {
    win, doc, preference, canvas: canvas as unknown as HTMLCanvasElement, frames,
    intersect: (visible: boolean) => intersection([{ isIntersecting: visible }]),
    resize: () => resize(),
    frame(now: number) {
      const callbacks = Array.from(frames.values())
      frames.clear()
      callbacks.forEach(callback => callback(now))
    },
  }
}

beforeEach(() => { drawing.render.mockReset(); drawing.resize.mockReset() })
afterEach(() => vi.unstubAllGlobals())

describe('ocean lifecycle', () => {
  it('does no canvas work before intersection, then caps pixel density and stops offscreen', () => {
    const env = browser(), ready = vi.fn()
    const ocean = mountOcean(env.canvas, ready)
    env.resize()
    env.frame(0)
    expect(drawing.resize).not.toHaveBeenCalled()
    expect(drawing.render).not.toHaveBeenCalled()
    env.intersect(true)
    env.frame(0)
    expect(drawing.resize).toHaveBeenCalledWith(1440, 823, 1.5)
    expect(drawing.render).toHaveBeenCalled()
    expect(ready).toHaveBeenLastCalledWith(true)
    env.intersect(false)
    const draws = drawing.render.mock.calls.length
    env.resize()
    env.frame(1000)
    expect(drawing.render).toHaveBeenCalledTimes(draws)
    expect(env.frames.size).toBe(0)
    ocean.destroy()
  })

  it('preserves a manual pause through hidden tabs, resize and page restoration', () => {
    const env = browser(), times: number[] = []
    drawing.render.mockImplementation((world: { time: number }) => times.push(world.time))
    const ocean = mountOcean(env.canvas, vi.fn())
    env.intersect(true)
    env.frame(0)
    env.frame(34)
    ocean.setPaused(true)
    const time = times.at(-1)
    env.doc.hidden = true
    env.doc.dispatchEvent(new Event('visibilitychange'))
    const draws = times.length
    env.resize()
    env.win.dispatchEvent(new Event('pagehide'))
    env.win.dispatchEvent(new Event('pageshow'))
    env.frame(30_000)
    expect(times).toHaveLength(draws)
    env.doc.hidden = false
    env.doc.dispatchEvent(new Event('visibilitychange'))
    env.frame(60_000)
    expect(env.frames.size).toBe(0)
    expect(times.at(-1)).toBe(time)
    ocean.setPaused(false)
    env.frame(90_000)
    expect(times.at(-1)).toBe(time)
    env.frame(90_034)
    expect(times.at(-1)! - time!).toBeCloseTo(2 / 60)
    ocean.destroy()
  })

  it('uses the still during print and reduced motion, and cannot restart after teardown', () => {
    const env = browser(), ready = vi.fn()
    const ocean = mountOcean(env.canvas, ready)
    env.intersect(true)
    env.frame(0)
    env.win.dispatchEvent(new Event('beforeprint'))
    const draws = drawing.render.mock.calls.length
    env.resize()
    env.frame(500)
    expect(drawing.render).toHaveBeenCalledTimes(draws)
    env.win.dispatchEvent(new Event('afterprint'))
    env.preference.matches = true
    env.preference.dispatchEvent(new Event('change'))
    expect(ready).toHaveBeenLastCalledWith(false)
    env.frame(1000)
    expect(drawing.render).toHaveBeenCalledTimes(draws)
    ocean.destroy()
    env.preference.matches = false
    env.preference.dispatchEvent(new Event('change'))
    env.intersect(true)
    ocean.setPaused(false)
    env.frame(2000)
    expect(drawing.render).toHaveBeenCalledTimes(draws)
    expect(env.frames.size).toBe(0)
  })

  it('falls back after a render failure and releases the frame loop', () => {
    const env = browser(), ready = vi.fn()
    drawing.render.mockImplementation(() => { throw new Error('context lost') })
    const ocean = mountOcean(env.canvas, ready)
    env.intersect(true)
    expect(() => env.frame(0)).not.toThrow()
    expect(ready).toHaveBeenLastCalledWith(false)
    expect(env.frames.size).toBe(0)
    env.resize()
    env.frame(100)
    expect(drawing.render).toHaveBeenCalledTimes(1)
    ocean.destroy()
  })

  it('updates text after painting and stops both when paused or offscreen', () => {
    const env = browser(), paint = vi.fn()
    const ocean = mountOcean(env.canvas, vi.fn(), paint)
    env.intersect(true)
    env.frame(0)
    expect(paint).toHaveBeenCalledTimes(1)
    expect(drawing.render.mock.invocationCallOrder[0]).toBeLessThan(paint.mock.invocationCallOrder[0]!)
    ocean.setPaused(true)
    env.frame(34)
    expect(paint).toHaveBeenCalledTimes(1)
    ocean.setPaused(false)
    env.intersect(false)
    env.frame(68)
    expect(paint).toHaveBeenCalledTimes(1)
    ocean.destroy()
  })

  it('keeps the scene running when a text callback fails', () => {
    const env = browser()
    const ocean = mountOcean(env.canvas, vi.fn(), () => { throw new Error('text overlay failed') })
    env.intersect(true)
    env.frame(0)
    env.frame(34)
    expect(drawing.render).toHaveBeenCalledTimes(2)
    expect(env.frames.size).toBe(1)
    ocean.destroy()
  })
})
