import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { RunStory } from '../../components/RunStory'

vi.mock('../../components/run-story.css', () => ({}))
vi.mock('../../components/recorded-run-timeline.css', () => ({}))

describe('the recorded run story fallback', () => {
  it('renders an explicit unavailable state and Lab action without invented evidence', () => {
    const html = renderToStaticMarkup(createElement(RunStory, { data: null }))
    expect(html).toContain('The recorded run is unavailable.')
    expect(html).toContain('href="/lab#run"')
    expect(html).toContain('Run the default parser')
    expect(html).not.toContain('data-run-id=')
    expect(html).not.toContain('data-testid="recorded-case-field"')
    expect(html).not.toContain('Recorded production execution timeline')
    expect(html).not.toContain('Recorded isolation checks')
    expect(html).not.toContain('Inspect run details')
    expect(html).not.toContain('Rejected')
  })
})
