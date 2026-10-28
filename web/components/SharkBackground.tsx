'use client'

import { useEffect, useId, useRef, useState } from 'react'
import { drawSharks, getSharkScene, SHARK_PATH } from '@/lib/shark-background'
import './shark-background.css'

export function SharkBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const elapsed = useRef(0)
  const [ready, setReady] = useState(false)
  const [paused, setPaused] = useState(false)
  const patternId = useId()

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || !window.matchMedia || !window.IntersectionObserver || !window.ResizeObserver) return
    const reduced = matchMedia('(prefers-reduced-motion: reduce)')
    const theme = matchMedia('(prefers-color-scheme: dark)')
    let context: CanvasRenderingContext2D | null
    try { context = canvas.getContext('2d') } catch { return }
    if (!context) return
    const ctx = context
    let frame = 0
    let visible = false
    let suspended = false
    let failed = false
    let last = 0
    let width = 0
    let height = 0

    const stop = () => { cancelAnimationFrame(frame); frame = 0; last = 0 }
    const fail = () => { failed = true; stop(); setReady(false) }
    const draw = () => {
      try {
        drawSharks(ctx, width, height, elapsed.current, theme.matches)
        setReady(true)
      } catch { fail() }
    }
    const canRun = () => !failed && visible && !paused && !suspended && !reduced.matches && !document.hidden
    const tick = (now: number) => {
      frame = 0
      if (!canRun()) return
      if (!last || now - last >= 1000 / 24) {
        if (last) elapsed.current += Math.min((now - last) / 1000, .1)
        last = now
        draw()
      }
      if (canRun()) frame = requestAnimationFrame(tick)
    }
    const sync = () => {
      stop()
      if (reduced.matches) setReady(false)
      if (canRun()) frame = requestAnimationFrame(tick)
    }
    const resize = () => {
      const bounds = canvas.getBoundingClientRect()
      width = bounds.width
      height = bounds.height
      if (!width || !height) return
      const scale = Math.min(window.devicePixelRatio || 1, 1.5, 1920 / width)
      canvas.width = Math.round(width * scale)
      canvas.height = Math.round(height * scale)
      ctx.setTransform(scale, 0, 0, scale, 0, 0)
      if (!reduced.matches && !failed) draw()
    }
    const recolor = () => { if (!reduced.matches && !failed) draw() }
    const suspend = () => { suspended = true; sync() }
    const resume = () => { suspended = false; resize(); sync() }
    const intersection = new IntersectionObserver(([entry]) => { visible = entry?.isIntersecting ?? false; sync() })
    const observer = new ResizeObserver(resize)
    intersection.observe(canvas)
    observer.observe(canvas)
    reduced.addEventListener('change', sync)
    theme.addEventListener('change', recolor)
    document.addEventListener('visibilitychange', sync)
    window.addEventListener('pagehide', suspend)
    window.addEventListener('pageshow', resume)
    window.addEventListener('beforeprint', suspend)
    window.addEventListener('afterprint', resume)
    resize()
    return () => {
      stop()
      intersection.disconnect()
      observer.disconnect()
      reduced.removeEventListener('change', sync)
      theme.removeEventListener('change', recolor)
      document.removeEventListener('visibilitychange', sync)
      window.removeEventListener('pagehide', suspend)
      window.removeEventListener('pageshow', resume)
      window.removeEventListener('beforeprint', suspend)
      window.removeEventListener('afterprint', resume)
    }
  }, [paused])

  return <>
    <div className="shark-background" data-testid="shark-background" data-ready={ready} aria-hidden="true">
      <svg className="shark-still" viewBox="0 0 1440 720" preserveAspectRatio="xMidYMid slice" focusable="false">
        <defs>
          <pattern id={patternId} patternUnits="userSpaceOnUse" width=".055" height=".065">
            <text x="0" y=".052" fontSize=".053" fontFamily="monospace" fill="currentColor">:</text>
            <text x=".027" y=".052" fontSize=".053" fontFamily="monospace" fill="currentColor">+</text>
          </pattern>
        </defs>
        {getSharkScene(1440, 720, 0).map((shark, index) => <path key={index} d={SHARK_PATH} fill={`url(#${patternId})`} opacity={shark.opacity} transform={`translate(${shark.x} ${shark.y}) rotate(${shark.angle * 180 / Math.PI}) scale(${shark.scale})`} />)}
      </svg>
      <canvas ref={canvasRef} />
    </div>
    {ready && <button type="button" className="shark-motion-toggle" onClick={() => setPaused(value => !value)} aria-label={paused ? 'Play background animation' : 'Pause background animation'}>
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">{paused ? <path d="m5 3 7 5-7 5Z" fill="currentColor" /> : <path d="M5 4v8M11 4v8" fill="none" stroke="currentColor" strokeWidth="1.5" />}</svg>
      <span>{paused ? 'Play' : 'Pause'}</span>
    </button>}
  </>
}
