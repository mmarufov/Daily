'use client'

import { useState } from 'react'

/**
 * The recorded batch, shown instead of described.
 *
 * A companion to `Misalignment.tsx`, which is a *schematic* and says so. This
 * is the opposite: one real recorded batch, printed as it was recorded, with
 * nothing illustrative in it.
 *
 * This section used to be fifty-five words of prose explaining that the
 * scorer sent forty articles, got a different number of verdicts back, and
 * had no way to tell which verdict belonged to which article. That is the
 * single most important fact on the site and it was a paragraph.
 *
 * It is now the recorded batch itself. The reader sees an article on the left
 * and, on the right, the verdict production attached to it — and finds the
 * mismatch without being told. "Singapore's AI future" sitting beside "the
 * creator economy" argues better than any sentence about it could.
 *
 * Every connector is slate, not vermilion, and that is the whole point rather
 * than a styling choice: the site's rule is that slate means unverifiable,
 * and the recorded note is explicit that no article identifier appears
 * anywhere in the request or the response. Position is the only thing joining
 * these two columns. Colouring a connector red would be claiming to know
 * which pairs are wrong, and nothing in the evidence establishes that — the
 * reader's own judgement is the only thing that does.
 */

export interface BatchPair {
  readonly position: number
  readonly title: string
  readonly reason: string
}

export function OffendingBatch({
  pairs,
  sent,
  returned,
}: {
  readonly pairs: readonly BatchPair[]
  readonly sent: number
  readonly returned: number
}) {
  const [active, setActive] = useState<number | null>(null)

  return (
    <div className="flex flex-col gap-6">
      <div className="tally" aria-hidden="true">
        <Tally n={sent} label="articles sent" />
        <span className="tally-arrow">→</span>
        <Tally n={returned} label="verdicts returned" off />
      </div>
      <p className="sr-only">
        {sent} articles were sent and {returned} verdicts came back. The pairs below show which
        verdict the scorer attached to which article.
      </p>

      <ol className="pairs">
        {pairs.map((pair) => {
          const on = active === pair.position
          return (
            <li key={pair.position}>
              <button
                type="button"
                className={`pair ${on ? 'pair-on' : ''}`}
                onMouseEnter={() => setActive(pair.position)}
                onMouseLeave={() => setActive(null)}
                onFocus={() => setActive(pair.position)}
                onBlur={() => setActive(null)}
                onClick={() => setActive(on ? null : pair.position)}
                aria-expanded={on}
              >
                <span className="pair-pos">{String(pair.position).padStart(2, '0')}</span>
                <span className="pair-title">{pair.title}</span>
                <span className="pair-link" aria-hidden="true" />
                <span className="pair-reason">{pair.reason}</span>
              </button>
            </li>
          )
        })}
      </ol>

      <p className="m-0 max-w-2xl text-xs text-ink-40">
        Nothing in the response names an article —{' '}
        <span className="text-unknown">position is the only join</span>.
      </p>
    </div>
  )
}

function Tally({ n, label, off }: { n: number; label: string; off?: boolean }) {
  return (
    <span className="tally-item">
      <span className={`tally-n ${off === true ? 'text-signal' : 'text-ink'}`}>{n}</span>
      <span className="tally-label">{label}</span>
    </span>
  )
}
