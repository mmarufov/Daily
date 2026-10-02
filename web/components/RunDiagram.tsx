import { useId, type CSSProperties } from 'react'
import type { RunStoryData } from '@/lib/run-story'
import { storyFrame, STORY_STOPS } from '@/lib/run-story-motion'

export function RunDiagram({ data, chapter }: { data: RunStoryData; chapter?: number }) {
  const id = useId().replaceAll(':', '')
  const staticStyle = chapter === undefined ? undefined : storyFrame(STORY_STOPS[chapter] ?? 0) as CSSProperties
  const viewBox = chapter === 0 ? '140 30 480 340' : chapter === 1 ? '320 0 390 360' : chapter === 2 ? '25 0 650 360' : '0 0 960 380'
  return <svg className="run-diagram" viewBox={viewBox} fill="none" aria-hidden="true" style={staticStyle}>
    <defs>
      <pattern id={`${id}-dots`} width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="1" cy="1" r=".65" fill="currentColor" /></pattern>
      <linearGradient id={`${id}-wash`} x1="0" y1="0" x2="1" y2="1"><stop stopColor="var(--d-paper)" /><stop offset="1" stopColor="var(--d-paper-2)" /></linearGradient>
    </defs>
    <rect className="run-drawing-grid" x="24" y="12" width="912" height="336" fill={`url(#${id}-dots)`} />
    <path className="run-path-base" d="M55 207H900" />
    <path className="run-path" d="M55 207H900" pathLength="1" />
    <circle className="run-start-dot" cx="55" cy="207" r="3" />
    <g className="run-system"><g className="run-machine">
      <rect className="run-machine-wash" x="345" y="36" width="300" height="294" rx="2" fill={`url(#${id}-wash)`} />
      <path className="run-machine-outline" d="M385 36h-40v40m260-40h40v40M345 290v40h40m220 0h40v-40" pathLength="1" />
      <path className="run-machine-guide" d="M397 36h194M345 90v186m300-186v186M397 330h194" />
      <text className="run-svg-label" x="367" y="65">VERCEL SANDBOX</text>
      <g className="run-machine-marks"><path d="M371 303h20m5 0h6m5 0h6" /><text className="run-svg-small" x="519" y="307">deny-all</text></g>
    </g>
    <g className="run-file-travel">
      <g transform="translate(200 83)">
        <path className="run-file-shadow" d="M0 0h140l30 30v176H0Z" transform="translate(4 6)" />
        <path className="run-file-paper" d="M0 0h140l30 30v176H0Z" />
        <path className="run-file-fold" d="M140 0v30h30" />
        <text className="run-file-type" x="20" y="48">py</text>
        <path className="run-file-rule" d="M20 67h130" />
        <text className="run-file-name" x="20" y="96">candidate.py</text>
        <text className="run-svg-small" x="20" y="117">{data.preset}</text>
        <path className="run-code-line" d="M20 141h64m-64 10h109m-97 10h54" />
        <circle cx="23" cy="185" r="2.5" fill="currentColor" />
        <text className="run-svg-small" x="34" y="188">Python parser</text>
      </g>
    </g>
    </g>
    <g className="run-inputs">
      <text className="run-svg-label" x="72" y="68">THE CASE SUITE</text>
      {data.cases.map((item, i) => <rect key={item.id} x={72 + i % 8 * 17} y={84 + Math.floor(i / 8) * 17} width="11" height="11" rx="2" className="run-input-cell" />)}
      <text className="run-input-count" x="72" y="260">{data.counts.total}</text>
      <text className="run-svg-small" x="109" y="259">cases</text>
      <text className="run-svg-small" x="72" y="283">{data.counts.faultInjected} fault-injected</text>
      <g className="run-test-packet"><rect x="225" y="254" width="10" height="10" rx="2" /><rect x="243" y="254" width="10" height="10" rx="2" /><rect x="261" y="254" width="10" height="10" rx="2" /></g>
    </g>
    <g className="run-grading-path"><path d="M445 207h100m-8-6 8 6-8 6" /><text className="run-svg-label" x="163" y="358">MICROVM STOPPED · {data.events[6]!.elapsed}s</text></g>
  </svg>
}
