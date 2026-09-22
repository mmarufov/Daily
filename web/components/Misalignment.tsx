'use client'

import { useState } from 'react'

/**
 * The defect, drawn.
 *
 * Daily's production scorer sends N articles, asks for N verdicts "in the same
 * order", and sends no article identifiers. The parse is positional. So the
 * moment a response comes back with a different number of entries, every
 * verdict after the discrepancy is applied to the wrong article — and the log
 * records a confident rationale for a decision that was never made about that
 * story.
 *
 * This figure is a SCHEMATIC and says so on the page. The scorecards record
 * how many verdicts came back for how many articles (27 for 40, 33 for 40, 18
 * for 20, and once 201 for 40); they do not record which entry the model
 * merged. So the merge point here is illustrative, and the three cases printed
 * beneath the figure are the recorded evidence.
 */

const ROWS = 12
const MERGE_AFTER = 4

const ROW_H = 26
/** Gutter opened at the merge point, reserved in both states so the figure
 *  does not change height when you toggle it. */
const GAP = 16
const TOP = 26
const LEFT_X = 132
const RIGHT_X = 300
const WIDTH = 432
const HEIGHT = TOP + ROWS * ROW_H + GAP + 14

type Mode = 'assumed' | 'actual'

function y(i: number): number {
  return TOP + i * ROW_H + (i >= MERGE_AFTER ? GAP : 0)
}

export function Misalignment() {
  const [mode, setMode] = useState<Mode>('assumed')
  const actual = mode === 'actual'

  // In the actual response two articles were folded into one verdict, so the
  // returned list is one shorter and every later verdict describes the article
  // below the one it lands on.
  const returned = actual ? ROWS - 1 : ROWS

  return (
    <figure className="m-0 flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          role="group"
          aria-label="Response shape"
          className="flex gap-px border border-rule bg-rule"
        >
          {(
            [
              ['assumed', `${ROWS} verdicts returned`],
              ['actual', `${ROWS - 1} verdicts returned`],
            ] as const
          ).map(([value, text]) => (
            <button
              key={value}
              type="button"
              onClick={() => setMode(value)}
              aria-pressed={mode === value}
              className={[
                'px-3 py-1.5 text-xs transition-colors duration-150',
                mode === value ? 'bg-ink text-paper' : 'bg-paper text-ink hover:bg-paper-secondary',
              ].join(' ')}
            >
              {text}
            </button>
          ))}
        </div>
        <p className="m-0 text-xs text-ink-40">Schematic · merge point illustrative</p>
      </div>

      <div className="border border-rule bg-paper-secondary p-4">
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          className="h-auto w-full"
          role="img"
          aria-label={
            actual
              ? `Eleven verdicts returned for twelve articles. The first four land on the right article; from the fifth onward each verdict is applied to the article above the one it describes, and the twelfth article receives no verdict at all.`
              : `Twelve verdicts returned for twelve articles: every verdict lands on the article it describes.`
          }
        >
          <text x={LEFT_X} y="12" textAnchor="end" className="fig-label">
            ARTICLE SENT
          </text>
          <text x={RIGHT_X} y="12" className="fig-label">
            VERDICT APPLIED
          </text>

          {Array.from({ length: ROWS }, (_, i) => {
            // Which returned entry the positional parse hands to article i.
            const slot = i
            const hasVerdict = slot < returned
            // Which article that entry actually describes.
            const describes = actual && slot >= MERGE_AFTER ? slot + 1 : slot
            const wrong = hasVerdict && describes !== i

            return (
              <g key={i}>
                <text x={LEFT_X - 26} y={y(i) + 4} textAnchor="end" className="fig-num">
                  {String(i + 1).padStart(2, '0')}
                </text>
                <rect x={LEFT_X - 18} y={y(i) - 5} width="10" height="10" className="fig-tick" />

                {hasVerdict ? (
                  <>
                    <line
                      x1={LEFT_X}
                      y1={y(i)}
                      x2={RIGHT_X - 22}
                      y2={y(i)}
                      className={wrong ? 'fig-wire-wrong' : 'fig-wire'}
                    />
                    <rect
                      x={RIGHT_X - 18}
                      y={y(i) - 5}
                      width="10"
                      height="10"
                      className={wrong ? 'fig-tick-wrong' : 'fig-tick'}
                    />
                    <text
                      x={RIGHT_X}
                      y={y(i) + 4}
                      className={wrong ? 'fig-num-wrong' : 'fig-num'}
                    >
                      {wrong
                        ? `says article ${String(describes + 1).padStart(2, '0')}`
                        : `about article ${String(describes + 1).padStart(2, '0')}`}
                    </text>
                  </>
                ) : (
                  <>
                    <line
                      x1={LEFT_X}
                      y1={y(i)}
                      x2={RIGHT_X - 22}
                      y2={y(i)}
                      className="fig-wire-absent"
                    />
                    <text x={RIGHT_X} y={y(i) + 4} className="fig-num-wrong">
                      no verdict at all
                    </text>
                  </>
                )}
              </g>
            )
          })}

          <g>
            <line
              x1={8}
              y1={y(MERGE_AFTER) - ROW_H / 2 - GAP / 2}
              x2={WIDTH - 8}
              y2={y(MERGE_AFTER) - ROW_H / 2 - GAP / 2}
              className={actual ? 'fig-cut' : 'fig-cut-idle'}
            />
            <text
              x={8}
              y={y(MERGE_AFTER) - ROW_H / 2 - GAP / 2 - 5}
              className={actual ? 'fig-cut-label' : 'fig-label'}
            >
              {actual ? 'TWO ARTICLES MERGED INTO ONE VERDICT' : 'NOTHING MERGED'}
            </text>
          </g>
        </svg>
      </div>

      <figcaption className="m-0 max-w-2xl text-xs text-ink-60">
        {actual ? (
          <>
            One merged entry is enough: the parse assigns{' '}
            <span className="text-ink">results[i]</span> to{' '}
            <span className="text-ink">articles[i]</span> regardless of length, so seven of twelve
            articles are judged on another story&rsquo;s reasoning. At batches of forty this fires
            63 times in one run.
          </>
        ) : (
          <>
            What the code assumes. No article identifier is sent and the model is never asked to
            echo an index, so this assumption is the only thing holding the pairing together.
          </>
        )}
      </figcaption>
    </figure>
  )
}
