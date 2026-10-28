'use client'

import { useEffect, useRef, useState } from 'react'
import type { mountOcean } from '@/lib/ocean-controller'
import './shark-background.css'

type Ocean = ReturnType<typeof mountOcean>

export function SharkBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const oceanRef = useRef<Ocean | null>(null)
  const pausedRef = useRef(false)
  const [ready, setReady] = useState(false)
  const [paused, setPaused] = useState(false)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    let disposed = false
    import('@/lib/ocean-controller').then(({ mountOcean }) => {
      if (disposed) return
      const ocean = mountOcean(canvas, value => { if (!disposed) setReady(value) })
      oceanRef.current = ocean
      ocean.setPaused(pausedRef.current)
    }).catch(() => { if (!disposed) setReady(false) })
    return () => {
      disposed = true
      oceanRef.current?.destroy()
      oceanRef.current = null
    }
  }, [])

  const toggle = () => {
    pausedRef.current = !pausedRef.current
    oceanRef.current?.setPaused(pausedRef.current)
    setPaused(pausedRef.current)
  }

  return <>
    <div className="shark-background" data-testid="shark-background" data-ready={ready} aria-hidden="true">
      <picture className="shark-still">
        <source media="(max-width: 767px)" srcSet="/ocean/mobile.webp" />
        <img src="/ocean/desktop.webp" width="1440" height="823" alt="" decoding="async" fetchPriority="low" />
      </picture>
      <canvas ref={canvasRef} />
    </div>
    {ready && <button type="button" className="shark-motion-toggle" onClick={toggle} aria-label={paused ? 'Play background animation' : 'Pause background animation'}>
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">{paused ? <path d="m5 3 7 5-7 5Z" fill="currentColor" /> : <path d="M5 4v8M11 4v8" fill="none" stroke="currentColor" strokeWidth="1.5" />}</svg>
      <span>{paused ? 'Play' : 'Pause'}</span>
    </button>}
  </>
}
