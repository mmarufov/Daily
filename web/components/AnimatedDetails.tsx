'use client'

import { useEffect, useRef, type ComponentProps, type MouseEvent } from 'react'

/** Native disclosure first; animation only owns its height during a gesture. */
export function AnimatedDetails({ children, className = '', onClick, ...props }: ComponentProps<'details'>) {
  const ref = useRef<HTMLDetailsElement>(null)
  const active = useRef<Animation | null>(null)
  const destination = useRef<boolean | null>(null)

  function settle() {
    const element = ref.current
    active.current?.cancel()
    active.current = null
    if (element) {
      if (destination.current !== null) element.open = destination.current
      element.style.removeProperty('overflow')
      delete element.dataset.motion
    }
    destination.current = null
  }

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)')
    const finish = () => settle()
    const hidden = () => { if (document.hidden) settle() }
    media.addEventListener('change', finish)
    window.addEventListener('resize', finish)
    document.addEventListener('visibilitychange', hidden)
    return () => {
      settle()
      media.removeEventListener('change', finish)
      window.removeEventListener('resize', finish)
      document.removeEventListener('visibilitychange', hidden)
    }
  }, [])

  function toggle(event: MouseEvent<HTMLDetailsElement>) {
    onClick?.(event)
    const element = event.currentTarget
    const target = event.target as HTMLElement
    const summary = target.closest('summary')
    // Nested disclosures and links inside a summary retain their own behavior.
    if (event.defaultPrevented || summary?.parentElement !== element ||
      target.closest('a, button, input, select, textarea')) return
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches || !element.animate) {
      settle()
      return
    }
    event.preventDefault()
    const opening = !(destination.current ?? element.open)
    const from = element.getBoundingClientRect().height
    active.current?.cancel()
    element.open = opening
    const to = element.getBoundingClientRect().height
    // Keep the content rendered while closing, then restore native hidden state.
    element.open = true
    destination.current = opening
    element.dataset.motion = opening ? 'opening' : 'closing'
    element.style.overflow = 'clip'
    const animation = element.animate(
      { height: [`${from}px`, `${to}px`] },
      { duration: 280, easing: 'cubic-bezier(.22, 1, .36, 1)' },
    )
    active.current = animation
    animation.onfinish = () => { if (active.current === animation) settle() }
  }

  return <details {...props} ref={ref} className={`animated-disclosure ${className}`} onClick={toggle}>{children}</details>
}
