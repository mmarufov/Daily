'use client'

import { useLayoutEffect, useRef, type ComponentProps } from 'react'

/** Animate an explicit selection change, never initial rendering or live data. */
export function MotionContent({ changeKey, children, ...props }: ComponentProps<'div'> & { changeKey: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const previousHeight = useRef<number | null>(null)

  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    const to = element.getBoundingClientRect().height
    const from = previousHeight.current
    previousHeight.current = to
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const animations: Animation[] = []
    if (from !== null && !media.matches && !document.hidden && element.animate) {
      animations.push(element.animate(
        { height: [`${from}px`, `${to}px`] },
        { duration: 260, easing: 'cubic-bezier(.22, 1, .36, 1)' },
      ))
      for (const child of element.children) {
        animations.push(child.animate(
          { opacity: [0.55, 1], transform: ['translateY(3px)', 'translateY(0)'] },
          { duration: 220, easing: 'cubic-bezier(.22, 1, .36, 1)' },
        ))
      }
    }
    const finish = () => animations.forEach((animation) => animation.cancel())
    const resize = () => {
      finish()
      previousHeight.current = element.getBoundingClientRect().height
    }
    const hidden = () => { if (document.hidden) finish() }
    media.addEventListener('change', finish)
    window.addEventListener('resize', resize)
    document.addEventListener('visibilitychange', hidden)
    return () => {
      if (animations.some((animation) => animation.playState === 'running')) {
        previousHeight.current = element.getBoundingClientRect().height
      }
      finish()
      media.removeEventListener('change', finish)
      window.removeEventListener('resize', resize)
      document.removeEventListener('visibilitychange', hidden)
    }
  }, [changeKey])

  return <div {...props} ref={ref}>{children}</div>
}
