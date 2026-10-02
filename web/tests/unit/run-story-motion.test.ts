import { describe, expect, it } from 'vitest'
import { clamp, storyFrame, storyStage, storyDuration, STORY_DURATION, STORY_STOPS } from '../../lib/run-story-motion'

const value = (progress: number, property: string) => Number.parseFloat(storyFrame(progress)[property]!)

describe('recorded run scroll progress', () => {
  it('holds the opening and verdict beyond the scroll region', () => {
    expect(clamp(-10)).toBe(0)
    expect(clamp(10)).toBe(1)
    expect(clamp(0.37)).toBe(0.37)
    expect(storyFrame(-10)).toEqual(storyFrame(0))
    expect(storyFrame(10)).toEqual(storyFrame(1))
    expect(storyStage(-10)).toBe(0)
    expect(storyStage(10)).toBe(3)
  })

  it.each([
    [0, 0], [0.2399, 0], [0.24, 1], [0.5099, 1],
    [0.51, 2], [0.7799, 2], [0.78, 3], [1, 3],
  ])('selects the correct chapter at progress %s', (progress, chapter) => {
    expect(storyStage(progress)).toBe(chapter)
  })

  it('requires a deliberate reverse pull after a forward transition', () => {
    for (const [boundary, stage] of [[0.24, 1], [0.51, 2], [0.78, 3]] as const) {
      expect(storyStage(boundary - 0.001, stage - 1)).toBe(stage - 1)
      expect(storyStage(boundary, stage - 1)).toBe(stage)
      expect(storyStage(boundary - 0.02, stage)).toBe(stage)
      expect(storyStage(boundary - 0.039, stage)).toBe(stage)
      expect(storyStage(boundary - 0.041, stage)).toBe(stage - 1)
    }
    expect(storyStage(0.9, 0)).toBe(3)
    expect(storyStage(0.1, 3)).toBe(0)
  })

  it('gives each transition a full second', () => {
    expect(STORY_DURATION).toBe(1000)
  })

  it('keeps skipped chapters from accelerating the visual sequence', () => {
    for (let index = 1; index < STORY_STOPS.length; index++) {
      const previous = STORY_STOPS[index - 1]!
      const next = STORY_STOPS[index]!
      expect(storyDuration(previous, next)).toBeCloseTo(1000)
      expect(storyDuration(next, previous)).toBeCloseTo(1000)
    }
    const skipped = storyDuration(STORY_STOPS[0], STORY_STOPS[3])
    expect(skipped).toBeCloseTo(1000 * (0.92 - 0.08) / 0.33)
    expect(storyDuration(STORY_STOPS[3], STORY_STOPS[0])).toBeCloseTo(skipped)
    expect(storyDuration(0.58, 0.59)).toBe(1000)
  })

  it('keeps result visuals hidden until the grading chapter', () => {
    for (let step = 0; step <= 80; step++) {
      expect(value(step / 100, '--run-verdict')).toBe(0)
    }
    expect(value(0.85, '--run-verdict')).toBeGreaterThan(0)
    expect(value(0.92, '--run-verdict')).toBe(1)
  })

  it('clears the case suite and isolation checks before revealing the verdict', () => {
    for (let step = 0; step <= 1000; step++) {
      const progress = step / 1000
      const resultVisible = value(progress, '--run-verdict') > 0
      if (resultVisible) {
        expect(value(progress, '--run-tests'), `suite at ${progress}`).toBe(0)
        expect(value(progress, '--run-checks'), `checks at ${progress}`).toBe(0)
      }
    }
    expect(value(0.59, '--run-checks')).toBe(1)
    expect(value(0.63, '--run-checks')).toBeGreaterThan(0)
    expect(value(0.63, '--run-checks')).toBeLessThan(1)
    expect(value(0.68, '--run-checks')).toBe(0)
    expect(value(0.68, '--run-tests')).toBe(0)
    expect(value(0.8, '--run-verdict')).toBe(0)
    expect(value(0.68, '--run-system-x')).toBe(0)
    expect(value(0.74, '--run-system-x')).toBeGreaterThan(-200)
    expect(value(0.74, '--run-system-x')).toBeLessThan(0)
    expect(value(0.8, '--run-system-x')).toBe(-200)
  })

  it('starts with the file alone and ends with the result held in place', () => {
    for (const property of ['--run-file-x', '--run-sandbox', '--run-tests', '--run-checks', '--run-verdict']) {
      expect(value(0, property), property).toBe(0)
    }
    expect(value(0, '--run-file-opacity')).toBe(1)
    expect(value(1, '--run-file-x')).toBe(200)
    expect(value(1, '--run-boundary-offset')).toBe(0)
    expect(value(1, '--run-line-offset')).toBe(0)
    expect(value(1, '--run-tests')).toBe(0)
    expect(value(1, '--run-checks')).toBe(0)
    expect(value(1, '--run-verdict')).toBe(1)
    expect(value(1, '--run-file-opacity')).toBeLessThan(0.2)
    expect(value(1, '--run-machine-opacity')).toBeLessThan(0.25)
  })

  it('spreads motion across each chapter instead of concentrating it near the end', () => {
    expect(value(0.22, '--run-sandbox')).toBeCloseTo(0.5)
    expect(value(0.19, '--run-file-x')).toBeCloseTo(100)
    expect(value(0.39, '--run-tests')).toBeCloseTo(0.5)
    expect(value(0.515, '--run-checks')).toBeCloseTo(0.5)
    expect(value(0.465, '--run-packet-x')).toBeCloseTo(130)
    expect(value(0.74, '--run-system-x')).toBeCloseTo(-100)
    expect(value(0.86, '--run-verdict')).toBeCloseTo(0.5)
  })

  it('keeps opacity, path progress and spatial movement within their bounds', () => {
    const unitProperties = [
      '--run-file-opacity', '--run-sandbox', '--run-boundary-offset', '--run-tests',
      '--run-checks', '--run-verdict', '--run-machine-opacity', '--run-line-offset', '--run-progress',
    ]
    for (let step = -10; step <= 110; step++) {
      const progress = step / 100
      for (const property of unitProperties) {
        expect(value(progress, property), property).toBeGreaterThanOrEqual(0)
        expect(value(progress, property), property).toBeLessThanOrEqual(1)
      }
      expect(value(progress, '--run-file-x')).toBeGreaterThanOrEqual(0)
      expect(value(progress, '--run-file-x')).toBeLessThanOrEqual(200)
      expect(value(progress, '--run-packet-x')).toBeGreaterThanOrEqual(0)
      expect(value(progress, '--run-packet-x')).toBeLessThanOrEqual(260)
      expect(value(progress, '--run-system-x')).toBeGreaterThanOrEqual(-200)
      expect(value(progress, '--run-system-x')).toBeLessThanOrEqual(0)
    }
  })

  it('resolves reverse and skipped scrolling directly to the requested frame', () => {
    const middle = storyFrame(0.59)
    storyFrame(1)
    storyFrame(0)
    expect(storyFrame(0.59)).toEqual(middle)
    expect(storyFrame(-1)).toEqual(storyFrame(0))
  })

  it('places each static scene and milestone button within its chapter', () => {
    expect(STORY_STOPS).toEqual([0.08, 0.32, 0.59, 0.92])
    expect(STORY_STOPS.map(progress => storyStage(progress))).toEqual([0, 1, 2, 3])
    expect(value(STORY_STOPS[0], '--run-sandbox')).toBe(0)
    expect(value(STORY_STOPS[1], '--run-sandbox')).toBe(1)
    expect(value(STORY_STOPS[1], '--run-boundary-offset')).toBe(0)
    expect(value(STORY_STOPS[1], '--run-file-x')).toBe(200)
    expect(value(STORY_STOPS[1], '--run-tests')).toBe(0)
    expect(value(STORY_STOPS[2], '--run-tests')).toBe(1)
    expect(value(STORY_STOPS[2], '--run-checks')).toBe(1)
    expect(value(STORY_STOPS[2], '--run-packet-x')).toBe(260)
    expect(value(STORY_STOPS[2], '--run-verdict')).toBe(0)
    expect(value(STORY_STOPS[3], '--run-verdict')).toBe(1)
    expect(value(STORY_STOPS[3], '--run-tests')).toBe(0)
  })
})
