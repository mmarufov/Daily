import { STORY_DURATION, STORY_STOPS } from './run-story-motion'

export type StoryPhase = 'outside' | 'ready' | 'transitioning' | 'settling' | 'bypass'

export class StoryGate {
  phase: StoryPhase = 'outside'
  stage = 0
  visual: number = STORY_STOPS[0]
  private intent = 0
  private from = this.visual
  private started = 0
  private lastTick = 0
  private elapsed = 0
  private settledAt = 0

  private settle(stage: number, phase: StoryPhase) {
    this.stage = stage
    this.visual = STORY_STOPS[stage]!
    this.phase = phase
    this.intent = 0
  }

  enter(stage: number) { this.settle(stage, 'ready') }
  bypass(stage = this.stage) { this.settle(stage, 'bypass') }
  leave(stage = this.stage) { this.settle(stage, 'outside') }

  input(delta: number, now: number): { consume: boolean; moveTo?: number } {
    this.tick(now)
    if (!Number.isFinite(delta) || delta === 0) return { consume: false }
    if (this.phase === 'outside' || this.phase === 'bypass') return { consume: false }
    if (this.phase !== 'ready') return { consume: true }
    if (Math.sign(delta) !== Math.sign(this.intent)) this.intent = 0
    this.intent += delta
    if (Math.abs(this.intent) < 160) return { consume: true }
    const next = this.stage + Math.sign(this.intent)
    this.intent = 0
    if (next < 0 || next >= STORY_STOPS.length) {
      this.bypass()
      return { consume: false }
    }
    this.from = this.visual
    this.started = this.lastTick = now
    this.elapsed = 0
    this.stage = next
    this.phase = 'transitioning'
    return { consume: true, moveTo: next }
  }

  tick(now: number): boolean {
    if (this.phase !== 'transitioning' && this.phase !== 'settling') return false
    if (now - this.started >= 1500) {
      this.bypass()
      return true
    }
    if (this.phase === 'settling') {
      if (now - this.settledAt >= 150) this.phase = 'ready'
      return false
    }
    // Bound visual catch-up after a busy frame; the wall-clock deadline still releases input.
    this.elapsed += Math.min(Math.max(0, now - this.lastTick), 64)
    this.lastTick = now
    const fraction = Math.min(1, this.elapsed / STORY_DURATION)
    const target = STORY_STOPS[this.stage]!
    this.visual = this.from + (target - this.from) * fraction
    if (fraction === 1) {
      this.visual = target
      this.phase = 'settling'
      this.settledAt = now
    }
    return false
  }
}

export function normalizeStoryDelta(delta: number, deltaMode: number, viewportHeight: number) {
  return delta * (deltaMode === 1 ? 16 : deltaMode === 2 ? viewportHeight : 1)
}
