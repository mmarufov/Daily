'use client'

import { useEffect, useRef, useState } from 'react'

/**
 * A living strip of the sieve, used as the seam between the landing and the
 * dark band below it.
 *
 * The landing page had nothing on it that moved. A static page can be
 * beautiful, but a *first screen* with no sign of life reads as a document
 * rather than a product, and this site's whole subject is a process that
 * removes things continuously.
 *
 * So the seam is a row of candidate cells with one being removed every beat.
 * It is the same grammar as the sieve below — ink survives, vermilion is the
 * one being taken — at a scale small enough to read as a rule rather than a
 * figure. By the time the reader reaches the black band the idiom is already
 * familiar.
 *
 * Deliberately *not* driven by real data: this is a decorative seam, and
 * dressing it up as a measurement would put an unsourced figure on the page
 * in a repository whose entire argument is that its figures are sourced. It
 * is `aria-hidden` and announces nothing.
 */

const CELLS = 120
const BEAT_MS = 130

export function CellTicker() {
  const [dead, setDead] = useState<ReadonlySet<number>>(() => new Set())
  const [cursor, setCursor] = useState<number | null>(null)
  const frame = useRef(0)

  useEffect(() => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return

    const order = Array.from({ length: CELLS }, (_, i) => i)
    for (let i = order.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1))
      ;[order[i], order[j]] = [order[j] as number, order[i] as number]
    }

    const tick = setInterval(() => {
      const next = order[frame.current % order.length] as number
      frame.current += 1
      setCursor(next)
      setDead((prev) => {
        // Reset once most of the row is gone, so the strip breathes instead
        // of filling up and stopping. A loop that ends is a loop you notice.
        if (prev.size > CELLS * 0.55) return new Set([next])
        const copy = new Set(prev)
        copy.add(next)
        return copy
      })
    }, BEAT_MS)

    return () => clearInterval(tick)
  }, [])

  return (
    <div className="ticker" aria-hidden="true">
      {Array.from({ length: CELLS }, (_, i) => (
        <span
          key={i}
          className="ticker-cell"
          data-state={cursor === i ? 'dying' : dead.has(i) ? 'gone' : 'alive'}
        />
      ))}
    </div>
  )
}
