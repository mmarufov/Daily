export const STORY_TOP = 96
export const STORY_DURATION = 360
export const STORY_STOPS = [0.08, 0.32, 0.59, 0.92] as const
export const STORY_MEDIA = '(min-width: 1024px) and (min-height: 720px) and (prefers-reduced-motion: no-preference)'

export function clamp(value: number) { return Math.min(1, Math.max(0, value)) }
export function storyStage(progress: number) {
  return progress < 0.2 ? 0 : progress < 0.45 ? 1 : progress < 0.75 ? 2 : 3
}
const ramp = (p: number, from: number, to: number) => {
  const t = clamp((p - from) / (to - from))
  return t * t * (3 - 2 * t)
}

export function storyFrame(p: number): Record<string, string> {
  const sandbox = ramp(p, 0.2, 0.28)
  const tests = ramp(p, 0.45, 0.5)
  const testExit = ramp(p, 0.68, 0.73)
  const systemMove = ramp(p, 0.73, 0.81)
  const verdict = ramp(p, 0.82, 0.88)
  return {
    '--run-file-x': `${200 * ramp(p, 0.15, 0.28)}px`,
    '--run-file-opacity': `${1 - 0.85 * systemMove}`,
    '--run-sandbox': `${sandbox}`,
    '--run-boundary-offset': `${1 - sandbox}`,
    '--run-tests': `${tests * (1 - testExit)}`,
    '--run-checks': `${ramp(p, 0.5, 0.57) * (1 - testExit)}`,
    '--run-packet-x': `${260 * ramp(p, 0.48, 0.58)}px`,
    '--run-verdict': `${verdict}`,
    '--run-machine-opacity': `${1 - 0.78 * systemMove}`,
    '--run-system-x': `${-200 * systemMove}px`,
    '--run-line-offset': `${1 - ramp(p, 0.08, 0.85)}`,
    '--run-progress': `${clamp(p)}`,
  }
}
