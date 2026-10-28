export const STORY_TOP = 96
export const STORY_DURATION = 1000
export const STORY_STOPS = [0.08, 0.32, 0.59, 0.92] as const
export const STORY_MEDIA = '(min-width: 1024px) and (min-height: 720px) and (prefers-reduced-motion: no-preference)'

export function storyDuration(from: number, to: number) {
  return STORY_DURATION * Math.max(1, Math.abs(to - from) / 0.33)
}

export function clamp(value: number) { return Math.min(1, Math.max(0, value)) }
const STAGE_THRESHOLDS = [0.24, 0.51, 0.78] as const
const REVERSE_BUFFER = 0.04

export function storyStage(progress: number, previousStage = -1) {
  if (previousStage < 0) return STAGE_THRESHOLDS.filter(boundary => progress >= boundary).length
  let stage = previousStage
  while (stage < 3 && progress >= STAGE_THRESHOLDS[stage]!) stage++
  // A small reverse scroll should leave the current stage readable.
  while (stage > 0 && progress < STAGE_THRESHOLDS[stage - 1]! - REVERSE_BUFFER) stage--
  return stage
}
const ramp = (p: number, from: number, to: number) => {
  const t = clamp((p - from) / (to - from))
  return t * t * (3 - 2 * t)
}

export function storyFrame(p: number): Record<string, string> {
  const sandbox = ramp(p, 0.12, 0.32)
  const tests = ramp(p, 0.32, 0.46)
  const testExit = ramp(p, 0.59, 0.68)
  const systemMove = ramp(p, 0.68, 0.8)
  const verdict = ramp(p, 0.8, 0.92)
  return {
    '--run-file-x': `${200 * ramp(p, 0.08, 0.3)}px`,
    '--run-file-opacity': `${1 - 0.85 * systemMove}`,
    '--run-sandbox': `${sandbox}`,
    '--run-boundary-offset': `${1 - sandbox}`,
    '--run-tests': `${tests * (1 - testExit)}`,
    '--run-checks': `${ramp(p, 0.44, 0.59) * (1 - testExit)}`,
    '--run-packet-x': `${260 * ramp(p, 0.36, 0.57)}px`,
    '--run-verdict': `${verdict}`,
    '--run-machine-opacity': `${1 - 0.78 * systemMove}`,
    '--run-system-x': `${-200 * systemMove}px`,
    '--run-line-offset': `${1 - ramp(p, 0.08, 0.85)}`,
    '--run-progress': `${clamp(p)}`,
  }
}
