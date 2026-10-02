import { readFileSync } from 'node:fs'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import {
  deriveRunStory,
  executionElapsed,
  ISOLATION_LABELS,
  loadRecordedExecution,
  parseRecordedExecution,
  RECORDED_EXECUTION_HREF,
  RECORDED_EXECUTION_ID,
} from '../../lib/recorded-execution'
import { RecordedRunTimelineView } from '../../components/RecordedRunTimeline'

const record = JSON.parse(readFileSync(`public${RECORDED_EXECUTION_HREF}`, 'utf8'))

describe('the pinned production execution timeline', () => {
  it('retains the recorded event order and exact elapsed times', async () => {
    const execution = await loadRecordedExecution()
    expect(execution?.response.run_id).toBe(RECORDED_EXECUTION_ID)
    const progress = execution!.response.progress
    expect(progress.map(event => executionElapsed(event.at, progress[0]!.at))).toEqual([
      '0.00', '0.84', '1.07', '1.20', '1.74', '2.61', '6.77',
    ])
    expect(progress).toEqual(record.response.progress)
    expect(execution?.response.outcome.sandbox.isolation.map(probe => probe.name)).toEqual(Object.keys(ISOLATION_LABELS))
  })

  it.each(['source', 'run', 'spec', 'hash', 'unfinished', 'missing event', 'stage', 'timestamp', 'reversed time', 'missing probe', 'duplicate probe'])(
    'rejects a malformed or mismatched %s instead of inventing a completed timeline', (failure) => {
      const changed = structuredClone(record)
      if (failure === 'source') changed.captured_from = 'https://other.example/run'
      if (failure === 'run') changed.response.run_id = 'other-run'
      if (failure === 'spec') changed.response.outcome.grading.spec_version = 1
      if (failure === 'hash') changed.response.outcome.grading.spec_hash = 'different'
      if (failure === 'unfinished') changed.response.finished = false
      if (failure === 'missing event') changed.response.progress.pop()
      if (failure === 'stage') changed.response.progress[0].stage = 'assumed ready'
      if (failure === 'timestamp') changed.response.progress[0].at = 'invalid'
      if (failure === 'reversed time') changed.response.progress[2].at = changed.response.progress[0].at
      if (failure === 'missing probe') changed.response.outcome.sandbox.isolation.pop()
      if (failure === 'duplicate probe') changed.response.outcome.sandbox.isolation[1] = changed.response.outcome.sandbox.isolation[0]
      expect(parseRecordedExecution(changed)).toBeNull()
    },
  )

  it('keeps missing recordings explicit without inventing timestamps or passing probes', async () => {
    expect(await loadRecordedExecution('public/runs/does-not-exist.json')).toBeNull()
    const html = renderToStaticMarkup(createElement(RecordedRunTimelineView, { execution: null }))
    expect(html).toContain('recorded execution is unavailable')
    expect(html).toContain('href="/lab#run"')
    expect(html).not.toContain('graded outside the microVM')
  })

  it('renders actual probes, criteria provenance and an untimed external grading step in server HTML', () => {
    const html = renderToStaticMarkup(createElement(RecordedRunTimelineView, { execution: parseRecordedExecution(record) }))
    expect(html).toContain('Recorded production execution')
    expect(html).toContain('October 1, 2026')
    expect(html).toContain('Spec 2')
    expect(html).toContain('f027762ab4d08b35')
    expect(html).not.toContain('result above')
    expect(html).toContain(`href="${RECORDED_EXECUTION_HREF}"`)
    for (const label of Object.values(ISOLATION_LABELS)) expect(html).toContain(label)
    expect(html.match(/data-case-mark="correct"/g)).toHaveLength(4)
    expect(html.match(/aria-label="[0-9.]+ seconds"/g)).toHaveLength(7)
    expect(html).toContain('<span class="recorded-timeline-time"></span><span class="recorded-timeline-dot" aria-hidden="true"></span><div class="recorded-timeline-step">graded outside the microVM</div>')
  })

  it('marks a failed probe with a cross and explicit failed text', () => {
    const changed = structuredClone(record)
    changed.response.outcome.sandbox.isolation[0].held = false
    const html = renderToStaticMarkup(createElement(RecordedRunTimelineView, { execution: parseRecordedExecution(changed) }))
    expect(html).toContain('data-held="false"')
    expect(html).toContain('data-case-mark="wrong"')
    expect(html).toContain('DNS lookup fails<span class="sr-only">: failed</span>')
  })
})

describe('the homepage run story', () => {
  it('derives timeline, probes and verdict from one execution', () => {
    const story = deriveRunStory(parseRecordedExecution(record))!
    expect(story).toMatchObject({
      runId: RECORDED_EXECUTION_ID,
      preset: 'count-guard-v1',
      date: record.response.progress[0].at,
      sourceHref: RECORDED_EXECUTION_HREF,
      specVersion: 2,
      specHash: 'f027762ab4d08b35',
      counts: { total: 64, correct: 48, failed: 4, notApplicable: 12, faultInjected: 22 },
      failure: { id: 'syn-positional-reordered', summary: 'Reordered verdicts passed the count check.' },
    })
    expect(story.date.slice(0, 10)).toBe('2026-10-01')
    expect(story.events.map(event => event.elapsed)).toEqual(['0.00', '0.84', '1.07', '1.20', '1.74', '2.61', '6.77'])
    expect(story.events.map(event => event.stage)).toEqual(record.response.progress.map((event: { stage: string }) => event.stage))
    expect(story.probes).toEqual(Object.entries(ISOLATION_LABELS).map(([name, label]) => ({ name, label, held: true })))
    expect(story.cases.filter(item => item.status === 'correct')).toHaveLength(story.counts.correct)
    expect(story.cases.filter(item => item.status === 'failed')).toHaveLength(story.counts.failed)
    expect(story.cases.filter(item => item.status === 'not-applicable')).toHaveLength(story.counts.notApplicable)
    expect(story.cases.find(item => item.id === story.failure.id)?.status).toBe('failed')
    expect(story).not.toHaveProperty('response')
    expect(story.cases[0]).not.toHaveProperty('why')
  })

  it.each(['mismatched count', 'negative count', 'missing case', 'duplicate case', 'missing example', 'changed example result', 'changed example refusal', 'wrong origin', 'wrong applicability', 'unknown status', 'unknown probe'])(
    'rejects %s before constructing the story', (failure) => {
      const changed = structuredClone(record)
      const grading = changed.response.outcome.grading
      const example = grading.cases.find((item: { case_id: string }) => item.case_id === 'syn-positional-reordered')
      if (failure === 'mismatched count') grading.counts.correct++
      if (failure === 'negative count') grading.counts.crashed = -1
      if (failure === 'missing case') grading.cases.pop()
      if (failure === 'duplicate case') grading.cases[1] = grading.cases[0]
      if (failure === 'missing example') example.case_id = 'different-case'
      if (failure === 'changed example result') {
        example.status = 'correct'
        grading.counts.correct++
        grading.counts['should-have-refused']--
      }
      if (failure === 'changed example refusal') example.observed_refusal_kind = 'count_mismatch'
      if (failure === 'wrong origin') example.origin = 'recorded-replay'
      if (failure === 'wrong applicability') example.applicability = 'not-applicable'
      if (failure === 'unknown status') example.status = 'unknown'
      if (failure === 'unknown probe') changed.response.outcome.sandbox.isolation[0].name = 'unrecorded-check'
      expect(deriveRunStory(parseRecordedExecution(changed))).toBeNull()
    },
  )

  it('preserves failed isolation results and explicit missing data', () => {
    const changed = structuredClone(record)
    changed.response.outcome.sandbox.isolation[0].held = false
    expect(deriveRunStory(parseRecordedExecution(changed))?.probes[0]).toEqual({
      name: 'egress-dns', label: 'DNS lookup fails', held: false,
    })
    expect(deriveRunStory(null)).toBeNull()
  })
})
