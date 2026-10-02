'use client'

import Link from 'next/link'
import { MotionContent } from '@/components/MotionContent'
import { useId, useState } from 'react'

import type { RetrievalLossData } from '@/lib/home-evidence'
import { personaName } from '@/lib/personas'

export function RetrievalLoss({ data }: { readonly data: RetrievalLossData | null }) {
  const [selectedKey, setSelectedKey] = useState('lookback')
  const detailId = useId()
  if (data === null) {
    return <div className="finding-unavailable" role="status">Recorded retrieval evidence is unavailable.</div>
  }
  const selected = data.segments.find((segment) => segment.key === selectedKey) ?? data.segments[0]
  if (selected === undefined) {
    return <div className="finding-unavailable" role="status">No retrieval-loss stages were recorded.</div>
  }

  return (
    <div className="finding-panel retrieval-panel" data-testid="retrieval-loss-panel">
      <div className="retrieval-summary">
        <p className="retrieval-total">
          <span>{data.beforeScorer}</span><span className="retrieval-total-denominator">/ {data.total}</span>
        </p>
        <div>
          <p className="finding-summary-title">Lost before scoring</p>
          <p className="finding-muted">
            {data.total === 0 ? 'No losses recorded' : `${(data.beforeScorer / data.total * 100).toFixed(1)}% of recorded must-see losses`}.
          </p>
        </div>
      </div>

      <figure className="retrieval-figure">
        <figcaption className="finding-caption">Where the {data.total} losses occurred</figcaption>
        <div className="retrieval-strip" aria-hidden="true">
          {data.segments.map((segment, index) => (
            <span
              key={segment.key}
              className="retrieval-strip-segment"
              data-loss-tone={index}
              data-selected={segment.key === selected.key}
              style={{ width: `${data.total === 0 ? 0 : segment.count / data.total * 100}%` }}
            />
          ))}
        </div>
        <div className="retrieval-options" role="group" aria-label="Select a retrieval loss stage">
          {data.segments.map((segment, index) => (
            <button
              key={segment.key}
              type="button"
              className="retrieval-option"
              aria-label={`${segment.label}: ${segment.count} of ${data.total} losses`}
              aria-pressed={segment.key === selected.key}
              aria-controls={detailId}
              onClick={() => setSelectedKey(segment.key)}
            >
              <span className="retrieval-option-label">
                <span className="retrieval-key" data-loss-tone={index} aria-hidden="true" />
                {segment.label}
              </span>
              <span className="retrieval-option-value">{segment.count}</span>
            </button>
          ))}
        </div>
      </figure>

      <MotionContent changeKey={selected.key} className="retrieval-detail" id={detailId} aria-live="polite">
        <div className="retrieval-explanation">
          <p className="eyebrow">{selected.beforeScorer ? 'Before scoring' : 'At or after scoring'}</p>
          <h3>{selected.label} removed {selected.count}</h3>
          <p>{selected.explanation}</p>
        </div>
        {selected.example === null ? (
          <p className="finding-muted">No example story was recorded for this stage.</p>
        ) : (
          <div className="retrieval-story">
            <p className="eyebrow">Recorded example · {personaName(selected.example.persona)}</p>
            <p className="retrieval-story-title" data-verbatim>
              {selected.example.story.title ?? selected.example.story.id}
            </p>
            <p className="retrieval-story-id">{selected.example.story.id}</p>
            <Link
              href={selected.example.href}
              className="text-link"
              data-testid="retrieval-story-link"
            >
              Open recorded story <span aria-hidden="true">↗</span>
            </Link>
          </div>
        )}
      </MotionContent>

      <p className="finding-footnote">
        {data.total} {data.unit} across {data.fixtureCount} fixtures, from the {data.snapshot} corpus.
        {' '}Articles can appear in multiple fixtures. These pairs use provisional must-see labels.
      </p>
    </div>
  )
}
