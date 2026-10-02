import { clamp, storyDuration, storyFrame, storyStage, STORY_MEDIA, STORY_STOPS, STORY_TOP } from './run-story-motion'

type Callbacks = {
  stage: (stage: number) => void
  enhanced: (enhanced: boolean) => void
  active: (active: boolean) => void
}

/** The server-rendered chapters remain the fallback until enhancement is ready. */
export function mountRunStory(element: HTMLElement, area: HTMLElement, panel: HTMLElement, callbacks: Callbacks) {
  const noop = { select: (_index: number) => {}, destroy: () => {} }
  if (typeof window.matchMedia !== 'function' || typeof IntersectionObserver !== 'function' ||
    typeof ResizeObserver !== 'function' || typeof requestAnimationFrame !== 'function' || typeof cancelAnimationFrame !== 'function') return noop

  const media = window.matchMedia(STORY_MEDIA)
  const print = window.matchMedia('print')
  const chapters = Array.from(element.querySelectorAll<HTMLElement>('.run-story-chapter'))
  const rail = element.querySelector<HTMLElement>('.run-rail')!
  const canvas = element.querySelector<HTMLElement>('.run-scene-canvas')!
  const details = element.querySelector<HTMLElement>('.run-inspect')!
  const layers = Array.from(element.querySelectorAll<HTMLElement>('.run-scene-result, .run-scene-checks'))
  // Late hydration must not replace the chapter a visitor has already reached.
  const alreadyReading = area.getBoundingClientRect().top < STORY_TOP
  let enhanced = false, visible = false, suspended = false, printing = false, disposed = false
  let frame = 0, layoutFrame = 0, listening = false, needsRead = true, immediate = true
  let lastStage = 0, moving = false, visual: number = STORY_STOPS[0], from = visual, target = visual
  let elapsed = 0, lastTick = 0, duration = 1000
  let trackHeight = area.offsetHeight
  let focused: Element | null = document.activeElement

  const paint = (progress: number) => {
    for (const [key, value] of Object.entries(storyFrame(progress))) element.style.setProperty(key, value)
    element.dataset.visualProgress = progress.toFixed(3)
  }
  const stop = () => {
    cancelAnimationFrame(frame)
    frame = 0
    if (moving) { moving = false; visual = target; paint(visual) }
    element.dataset.transitioning = 'false'
  }
  const running = () => enhanced && visible && !document.hidden && !suspended && !printing && !print.matches
  const update = (now: number) => {
    frame = 0
    if (!running()) return
    if (needsRead) {
      needsRead = false
      const travel = Math.max(1, area.offsetHeight - panel.offsetHeight)
      const progress = clamp((STORY_TOP - area.getBoundingClientRect().top) / travel)
      element.dataset.progress = progress.toFixed(3)
      const next = storyStage(progress, lastStage)
      if (next !== lastStage || immediate) {
        lastStage = next
        callbacks.stage(next)
        from = visual
        target = STORY_STOPS[next]!
        duration = storyDuration(from, target)
        elapsed = 0
        lastTick = now
        moving = !immediate && Math.abs(target - from) > 0.0001
        if (!moving) visual = target
        element.dataset.transitioning = String(moving)
        immediate = false
        paint(visual)
      }
    }
    if (moving) {
      // Resume smoothly after a busy frame instead of jumping through phases.
      elapsed += Math.min(Math.max(0, now - lastTick), 64)
      lastTick = now
      const fraction = clamp(elapsed / duration)
      visual = from + (target - from) * fraction
      paint(visual)
      if (fraction === 1) { moving = false; element.dataset.transitioning = 'false' }
      else frame = requestAnimationFrame(update)
    }
  }
  const schedule = () => {
    needsRead = true
    if (!frame && running()) frame = requestAnimationFrame(update)
  }
  const sync = () => {
    const active = running()
    callbacks.active(active)
    if (active && !listening) {
      immediate = true
      window.addEventListener('scroll', schedule, { passive: true })
      listening = true
    } else if (!active && listening) {
      window.removeEventListener('scroll', schedule)
      listening = false
    }
    if (active) schedule()
    else stop()
  }
  const fits = () => {
    if (!media.matches || alreadyReading) return false
    const previous = element.dataset.mode
    element.dataset.mode = 'scroll'
    const fits = panel.offsetHeight <= window.innerHeight - STORY_TOP - 8 &&
      layers.every(layer => layer.offsetTop + layer.scrollHeight <= canvas.clientHeight + 1 &&
        layer.offsetLeft >= 0 && layer.offsetLeft + layer.offsetWidth <= canvas.clientWidth + 1)
    element.dataset.mode = previous
    return fits
  }
  const reconcile = () => {
    layoutFrame = 0
    if (disposed || printing || print.matches) return
    const bounds = area.getBoundingClientRect()
    const inside = bounds.top <= STORY_TOP && bounds.top + trackHeight > STORY_TOP
    const below = bounds.top + trackHeight <= STORY_TOP
    const detailTop = details.getBoundingClientRect().top
    const reading = enhanced ? lastStage : chapters.reduce((current, chapter, index) => chapter.getBoundingClientRect().top <= STORY_TOP + 1 ? index : current, 0)
    const next = fits()
    if (next !== enhanced) {
      const fromRail = focused instanceof HTMLElement && rail.contains(focused)
      const fromChapter = focused instanceof HTMLElement && chapters.some(chapter => chapter.contains(focused))
      stop()
      enhanced = next
      element.dataset.mode = next ? 'scroll' : 'static'
      callbacks.enhanced(next)
      if (inside) {
        const top = next
          ? window.scrollY + area.getBoundingClientRect().top - STORY_TOP + STORY_STOPS[reading]! * Math.max(0, area.offsetHeight - panel.offsetHeight)
          : window.scrollY + chapters[reading]!.getBoundingClientRect().top - STORY_TOP
        window.scrollTo({ top, behavior: 'instant' })
      } else if (below) {
        window.scrollBy({ top: details.getBoundingClientRect().top - detailTop, behavior: 'instant' })
      }
      if (!next && fromRail) chapters[reading]?.querySelector<HTMLElement>('h3')?.focus({ preventScroll: true })
      if (next && fromChapter) rail.querySelectorAll<HTMLButtonElement>('button')[reading]?.focus({ preventScroll: true })
    }
    trackHeight = area.offsetHeight
    const current = area.getBoundingClientRect()
    visible = current.bottom > 0 && current.top < window.innerHeight
    immediate = true
    sync()
  }
  const resize = () => { if (!layoutFrame && !disposed) layoutFrame = requestAnimationFrame(reconcile) }
  const focus = (event: FocusEvent) => { focused = event.target as Element }
  const pointer = (event: PointerEvent) => { focused = event.target as Element }
  const visibility = () => { immediate = true; sync() }
  const hide = () => { suspended = true; sync() }
  const show = () => { suspended = false; immediate = true; resize() }
  const beforePrint = () => { printing = true; sync() }
  const afterPrint = () => { printing = false; resize() }

  let observer: IntersectionObserver, resizeObserver: ResizeObserver
  try {
    observer = new IntersectionObserver(([entry]) => { visible = entry?.isIntersecting === true; sync() })
    resizeObserver = new ResizeObserver(resize)
  } catch {
    return noop
  }
  observer.observe(area)
  for (const target of [area, panel, canvas, ...layers]) resizeObserver.observe(target)
  media.addEventListener('change', resize)
  window.addEventListener('resize', resize)
  window.visualViewport?.addEventListener('resize', resize)
  document.fonts?.addEventListener('loadingdone', resize)
  document.addEventListener('visibilitychange', visibility)
  document.addEventListener('focusin', focus)
  document.addEventListener('pointerdown', pointer, { passive: true })
  window.addEventListener('pagehide', hide)
  window.addEventListener('pageshow', show)
  window.addEventListener('beforeprint', beforePrint)
  window.addEventListener('afterprint', afterPrint)
  reconcile()

  return {
    select(index: number) {
      if (!enhanced || !media.matches || index < 0 || index >= STORY_STOPS.length) return
      const top = window.scrollY + area.getBoundingClientRect().top - STORY_TOP
      window.scrollTo({ top: top + STORY_STOPS[index]! * Math.max(0, area.offsetHeight - panel.offsetHeight), behavior: 'smooth' })
    },
    destroy() {
      disposed = true
      stop()
      cancelAnimationFrame(layoutFrame)
      window.removeEventListener('scroll', schedule)
      media.removeEventListener('change', resize)
      window.removeEventListener('resize', resize)
      window.visualViewport?.removeEventListener('resize', resize)
      document.fonts?.removeEventListener('loadingdone', resize)
      document.removeEventListener('visibilitychange', visibility)
      document.removeEventListener('focusin', focus)
      document.removeEventListener('pointerdown', pointer)
      window.removeEventListener('pagehide', hide)
      window.removeEventListener('pageshow', show)
      window.removeEventListener('beforeprint', beforePrint)
      window.removeEventListener('afterprint', afterPrint)
      observer.disconnect()
      resizeObserver.disconnect()
    },
  }
}
