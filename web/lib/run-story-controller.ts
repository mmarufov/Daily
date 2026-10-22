import { clamp, storyFrame, STORY_MEDIA, STORY_TOP } from './run-story-motion'
import { normalizeStoryDelta, StoryGate } from './run-story-gate'

type Callbacks = {
  stage: (stage: number) => void
  enhanced: (enhanced: boolean) => void
  active: (active: boolean) => void
}

const WHEEL_CONTROLS = 'input, textarea, select, [contenteditable]:not([contenteditable="false"]), [role="slider"], [role="listbox"], [role="menu"], dialog, [role="dialog"], [popover]'
const KEY_CONTROLS = `a[href], button, ${WHEEL_CONTROLS}`

function ownsInput(target: EventTarget | null, controls: string) {
  if (!(target instanceof Element)) return false
  if (target.closest(controls)) return true
  for (let node = target; node && node !== document.body && node !== document.documentElement; node = node.parentElement!) {
    if (node.scrollHeight > node.clientHeight && /auto|scroll/.test(getComputedStyle(node).overflowY)) return true
  }
  return false
}

/** Static chapters remain available until the layout and input capabilities are ready. */
export function mountRunStory(element: HTMLElement, area: HTMLElement, panel: HTMLElement, callbacks: Callbacks) {
  const noop = { select: (_index: number) => {}, skip: () => {}, destroy: () => {} }
  element.dataset.mode = 'static'
  callbacks.enhanced(false)
  callbacks.active(false)
  if (typeof window.matchMedia !== 'function' || typeof IntersectionObserver !== 'function' ||
    typeof ResizeObserver !== 'function' || typeof requestAnimationFrame !== 'function' || typeof cancelAnimationFrame !== 'function') return noop

  const media = window.matchMedia(STORY_MEDIA)
  const print = window.matchMedia('print')
  const chapters = Array.from(element.querySelectorAll<HTMLElement>('.run-story-chapter'))
  const rail = element.querySelector<HTMLElement>('.run-rail')!
  const canvas = element.querySelector<HTMLElement>('.run-scene-canvas')!
  const details = element.querySelector<HTMLElement>('.run-inspect')!
  const layers = Array.from(element.querySelectorAll<HTMLElement>('.run-scene-result, .run-scene-checks'))
  const alreadyReading = area.getBoundingClientRect().top < STORY_TOP
  const gate = new StoryGate()
  let enhanced = false, visible = false, suspended = false, printing = false, disposed = false, failed = false, touched = false
  let frame = 0, layoutFrame = 0, deadline = 0, listening = false, active = false
  let entry = 0, travel = 1, trackHeight = area.offsetHeight, viewportWidth = innerWidth, viewportHeight = innerHeight
  let expectedScroll: number | null = null
  let focused: Element | null = document.activeElement
  let painted = NaN, renderedStage = -1

  const available = () => !disposed && !failed && enhanced && !document.hidden && !suspended && !printing && !print.matches
  const owned = () => gate.phase === 'ready' || gate.phase === 'transitioning' || gate.phase === 'settling'
  const busy = () => gate.phase === 'transitioning' || gate.phase === 'settling'
  const anchor = (stage: number) => entry + travel * stage / 3
  const atStage = () => Math.round(clamp((window.scrollY - entry) / travel) * 3)
  const outside = () => window.scrollY < entry - 2 || window.scrollY > entry + travel + 2
  const attr = (name: string, value: string) => { if (element.getAttribute(name) !== value) element.setAttribute(name, value) }
  const render = () => {
    if (gate.stage !== renderedStage) { renderedStage = gate.stage; callbacks.stage(gate.stage) }
    if (gate.visual !== painted) {
      for (const [key, value] of Object.entries(storyFrame(gate.visual))) element.style.setProperty(key, value)
      painted = gate.visual
      attr('data-visual-progress', gate.visual.toFixed(3))
    }
    attr('data-phase', gate.phase)
    attr('data-transitioning', String(gate.phase === 'transitioning'))
  }
  const cancelWork = () => {
    cancelAnimationFrame(frame)
    clearTimeout(deadline)
    frame = deadline = 0
  }
  const release = () => {
    cancelWork()
    expectedScroll = null
    gate.bypass()
    render()
  }
  const setScroll = (top: number) => {
    expectedScroll = top
    window.scrollTo({ top, behavior: 'instant' })
    expectedScroll = window.scrollY
  }
  const updateVisibility = () => {
    visible = entry + STORY_TOP + trackHeight > window.scrollY && entry + STORY_TOP < window.scrollY + innerHeight
    const next = available() && visible
    if (active !== next) { active = next; callbacks.active(next) }
  }
  const readPosition = () => {
    updateVisibility()
    if (!visible && gate.phase === 'outside' && gate.stage === atStage()) return
    if (expectedScroll !== null && Math.abs(window.scrollY - expectedScroll) <= 2) return
    cancelWork()
    expectedScroll = null
    if (outside()) gate.leave(atStage())
    else gate.bypass(atStage())
    attr('data-progress', clamp((window.scrollY - entry) / travel).toFixed(3))
    render()
  }
  const inputListeners = (enabled: boolean) => {
    if (enabled === listening) return
    listening = enabled
    if (enabled) {
      // Arm before entry so the first large wheel event cannot cross the entire track.
      window.addEventListener('wheel', wheel, { passive: false })
      window.addEventListener('keydown', keydown)
      window.addEventListener('scroll', scroll, { passive: true })
    } else {
      window.removeEventListener('wheel', wheel)
      window.removeEventListener('keydown', keydown)
      window.removeEventListener('scroll', scroll)
    }
  }
  const sync = () => {
    inputListeners(available())
    updateVisibility()
    if (!available()) release()
  }
  const failOpen = () => {
    failed = true
    cancelWork()
    inputListeners(false)
    element.dataset.mode = 'static'
    enhanced = active = false
    callbacks.enhanced(false)
    callbacks.active(false)
    if (rail.contains(document.activeElement)) chapters[gate.stage]?.querySelector<HTMLElement>('h3')?.focus({ preventScroll: true })
  }
  const safely = (work: () => void) => { if (!disposed) { try { work() } catch { failOpen() } } }
  const update = (now: number) => safely(() => {
    frame = 0
    if (!available()) { release(); return }
    const timedOut = gate.tick(now)
    if (timedOut) expectedScroll = null
    render()
    if (busy()) frame = requestAnimationFrame(update)
    else { clearTimeout(deadline); deadline = 0 }
  })
  const startStep = (stage: number) => {
    setScroll(anchor(stage))
    attr('data-progress', (stage / 3).toFixed(3))
    updateVisibility()
    render()
    clearTimeout(deadline)
    deadline = window.setTimeout(() => safely(() => { if (busy()) release() }), 1500)
    if (!frame) frame = requestAnimationFrame(update)
  }
  const enter = (stage: number) => {
    cancelWork()
    gate.enter(stage)
    setScroll(anchor(stage))
    attr('data-progress', (stage / 3).toFixed(3))
    updateVisibility()
    render()
  }
  const intent = (delta: number, event: WheelEvent | KeyboardEvent) => {
    if (!available() || !Number.isFinite(delta) || delta === 0) return
    if (gate.phase === 'bypass' && outside()) gate.leave(atStage())
    if (!event.cancelable) { release(); return }
    const y = window.scrollY
    if (gate.phase === 'outside') {
      const forward = delta > 0 && y <= entry + 2 && y + delta >= entry
      const backward = delta < 0 && y >= entry + travel - 2 && y + delta <= entry + travel
      if (forward || backward) { event.preventDefault(); enter(forward ? 0 : 3) }
      return
    }
    const result = gate.input(delta, performance.now())
    if (result.consume) event.preventDefault()
    if (result.moveTo !== undefined) startStep(result.moveTo)
    else {
      if (!owned()) { cancelWork(); expectedScroll = null }
      render()
    }
  }
  const wheel = (event: WheelEvent) => safely(() => {
    if (event.defaultPrevented) return
    if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey || Math.abs(event.deltaX) > Math.abs(event.deltaY) || ownsInput(event.target, WHEEL_CONTROLS)) {
      if (owned()) release()
      return
    }
    intent(normalizeStoryDelta(event.deltaY, event.deltaMode, viewportHeight), event)
  })
  const keydown = (event: KeyboardEvent) => safely(() => {
    if (event.defaultPrevented) return
    if (event.key === 'Escape' || event.key === 'Home' || event.key === 'End') { release(); return }
    if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey && event.key !== ' ' || ownsInput(event.target, KEY_CONTROLS)) return
    const direction = event.key === 'ArrowDown' || event.key === 'PageDown' || event.key === ' ' && !event.shiftKey ? 1
      : event.key === 'ArrowUp' || event.key === 'PageUp' || event.key === ' ' && event.shiftKey ? -1 : 0
    if (!direction) return
    if (event.repeat && busy()) { event.preventDefault(); return }
    intent(direction * (owned() ? 160 : event.key.startsWith('Arrow') ? 40 : viewportHeight * .85), event)
  })
  const scroll = () => safely(readPosition)
  const fits = () => {
    if (!media.matches || alreadyReading || touched || failed) return false
    if (window.visualViewport && window.visualViewport.scale > 1.01) return false
    const previous = element.dataset.mode
    element.dataset.mode = 'scroll'
    const fits = panel.offsetHeight <= innerHeight - STORY_TOP - 8 &&
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
    const reading = enhanced ? gate.stage : chapters.reduce((current, chapter, index) => chapter.getBoundingClientRect().top <= STORY_TOP + 1 ? index : current, 0)
    const next = fits()
    const modeChanged = next !== enhanced
    if (modeChanged) {
      const fromRail = focused instanceof HTMLElement && rail.contains(focused)
      const fromChapter = focused instanceof HTMLElement && chapters.some(chapter => chapter.contains(focused))
      release()
      enhanced = next
      element.dataset.mode = next ? 'scroll' : 'static'
      callbacks.enhanced(next)
      if (inside) {
        const top = next
          ? window.scrollY + area.getBoundingClientRect().top - STORY_TOP + reading / 3 * Math.max(0, area.offsetHeight - panel.offsetHeight)
          : window.scrollY + chapters[reading]!.getBoundingClientRect().top - STORY_TOP
        setScroll(top)
        gate.bypass(reading)
      } else if (below) setScroll(window.scrollY + details.getBoundingClientRect().top - detailTop)
      if (!next && fromRail) chapters[reading]?.querySelector<HTMLElement>('h3')?.focus({ preventScroll: true })
      if (next && fromChapter) rail.querySelectorAll<HTMLButtonElement>('[data-story-stage]')[reading]?.focus({ preventScroll: true })
    }
    const nextEntry = window.scrollY + area.getBoundingClientRect().top - STORY_TOP
    const nextTravel = Math.max(1, area.offsetHeight - panel.offsetHeight)
    const viewportChanged = viewportWidth !== innerWidth || viewportHeight !== innerHeight
    const moved = Math.abs(nextEntry - entry) > 2 || Math.abs(area.offsetHeight - trackHeight) > 2
    const resizedPanel = Math.abs(nextTravel - travel) > 2
    entry = nextEntry
    travel = nextTravel
    trackHeight = area.offsetHeight
    viewportWidth = innerWidth
    viewportHeight = innerHeight
    if (!modeChanged && owned() && (viewportChanged || moved)) release()
    // A caption reflow can move an anchor without changing the active transition's clock.
    else if (!modeChanged && owned() && resizedPanel) setScroll(anchor(gate.stage))
    sync()
    if (enhanced) readPosition()
    render()
  }
  const resize = () => { if (!layoutFrame && !disposed) layoutFrame = requestAnimationFrame(() => safely(reconcile)) }
  const focus = (event: FocusEvent) => safely(() => {
    focused = event.target as Element
    if (owned() && !panel.contains(focused)) release()
  })
  const pointer = (event: PointerEvent) => safely(() => {
    focused = event.target as Element
    if (event.pointerType === 'touch') { touched = true; release(); reconcile() }
    else if (owned() && !panel.contains(focused)) release()
  })
  const click = (event: MouseEvent) => safely(() => { if (event.target instanceof Element && event.target.closest('a[href]')) release() })
  const navigation = () => safely(release)
  const visibility = () => safely(() => { release(); sync(); if (!document.hidden) resize() })
  const hide = () => safely(() => { suspended = true; release(); sync() })
  const show = () => safely(() => { suspended = false; release(); resize() })
  const beforePrint = () => safely(() => { printing = true; release(); sync() })
  const afterPrint = () => safely(() => { printing = false; resize() })
  const printChange = () => safely(() => { release(); sync(); if (!print.matches) resize() })

  let observer: IntersectionObserver, resizeObserver: ResizeObserver
  try {
    observer = new IntersectionObserver(() => safely(() => { updateVisibility(); if (!visible && owned()) release() }))
    resizeObserver = new ResizeObserver(resize)
  } catch { return noop }
  observer.observe(area)
  for (const target of [area, panel, canvas, ...layers]) resizeObserver.observe(target)
  media.addEventListener('change', resize)
  print.addEventListener('change', printChange)
  window.addEventListener('resize', resize)
  window.visualViewport?.addEventListener('resize', resize)
  document.fonts?.addEventListener('loadingdone', resize)
  document.addEventListener('visibilitychange', visibility)
  document.addEventListener('focusin', focus)
  document.addEventListener('pointerdown', pointer, { passive: true })
  document.addEventListener('click', click)
  window.addEventListener('pagehide', hide)
  window.addEventListener('pageshow', show)
  window.addEventListener('popstate', navigation)
  window.addEventListener('hashchange', navigation)
  window.addEventListener('beforeprint', beforePrint)
  window.addEventListener('afterprint', afterPrint)
  safely(reconcile)

  return {
    select(index: number) { safely(() => { if (available() && Number.isInteger(index) && index >= 0 && index < 4) enter(index) }) },
    skip() { safely(() => {
      release()
      details.scrollIntoView({ block: 'start', behavior: 'instant' })
      details.querySelector<HTMLElement>('summary')?.focus({ preventScroll: true })
    }) },
    destroy() {
      disposed = true
      cancelWork()
      cancelAnimationFrame(layoutFrame)
      inputListeners(false)
      media.removeEventListener('change', resize)
      print.removeEventListener('change', printChange)
      window.removeEventListener('resize', resize)
      window.visualViewport?.removeEventListener('resize', resize)
      document.fonts?.removeEventListener('loadingdone', resize)
      document.removeEventListener('visibilitychange', visibility)
      document.removeEventListener('focusin', focus)
      document.removeEventListener('pointerdown', pointer)
      document.removeEventListener('click', click)
      window.removeEventListener('pagehide', hide)
      window.removeEventListener('pageshow', show)
      window.removeEventListener('popstate', navigation)
      window.removeEventListener('hashchange', navigation)
      window.removeEventListener('beforeprint', beforePrint)
      window.removeEventListener('afterprint', afterPrint)
      observer.disconnect()
      resizeObserver.disconnect()
    },
  }
}
