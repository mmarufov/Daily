/**
 * Two runs, one shared scale.
 *
 * A column of percentages makes you do the subtraction in your head and then
 * decide, per metric, whether up is good. This draws the movement instead:
 * every fraction metric on the same 0–100% track, the baseline as a hollow
 * tick, the comparison as a filled one, and the segment between them coloured
 * only when the move is the bad direction for that metric.
 *
 * Restricted to fraction metrics on purpose. Costs, latencies and call counts
 * do not share a scale with a recall rate, and stretching each row to its own
 * maximum would make a 0.4-point move look identical to a 40-point one.
 */

export interface SlopeRow {
  readonly key: string
  readonly label: string
  /** Baseline value, 0..1. */
  readonly a: number | null
  /** Comparison value, 0..1. */
  readonly b: number | null
  readonly verdict: 'better' | 'worse' | 'unchanged' | 'not-computable' | 'no-direction'
  readonly display: string
  readonly material: boolean
}

export function Slope({
  rows,
  aLabel,
  bLabel,
  note,
}: {
  readonly rows: readonly SlopeRow[]
  readonly aLabel: string
  readonly bLabel: string
  readonly note?: string
}) {
  const usable = rows.filter((r) => r.a !== null && r.b !== null)
  if (usable.length === 0) return null

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5">
        <span className="flex items-center gap-1.5 text-xs text-ink-60">
          <span className="inline-block h-2.5 w-2.5 border border-ink" aria-hidden="true" />
          {aLabel}
        </span>
        <span className="flex items-center gap-1.5 text-xs text-ink-60">
          <span className="inline-block h-2.5 w-2.5 bg-ink" aria-hidden="true" />
          {bLabel}
        </span>
        <span className="flex items-center gap-1.5 text-xs text-ink-60">
          <span className="inline-block h-0.5 w-4 bg-signal" aria-hidden="true" />
          moved the wrong way
        </span>
      </div>

      <ul className="m-0 flex list-none flex-col gap-px border-y border-rule p-0">
        {usable.map((row) => {
          const a = row.a ?? 0
          const b = row.b ?? 0
          const lo = Math.min(a, b)
          const hi = Math.max(a, b)
          const worse = row.verdict === 'worse'

          return (
            <li
              key={row.key}
              className="grid grid-cols-[9rem_1fr_5rem] items-center gap-3 py-2 sm:grid-cols-[12rem_1fr_5.5rem]"
            >
              <span className="truncate text-xs text-ink-60" title={row.label}>
                {row.label}
              </span>

              <span className="relative block h-4" aria-hidden="true">
                {/* 0, 50 and 100 per cent gridlines, so a position is readable
                    without a tooltip. */}
                {[0, 0.5, 1].map((t) => (
                  <span
                    key={t}
                    className="absolute inset-y-1 w-px bg-rule"
                    style={{ left: `${t * 100}%` }}
                  />
                ))}
                <span
                  className={`absolute top-1/2 h-0.5 -translate-y-1/2 ${worse ? 'bg-signal' : 'bg-ink'}`}
                  style={{ left: `${lo * 100}%`, width: `${Math.max(hi - lo, 0) * 100}%` }}
                />
                <span
                  className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 border border-ink bg-paper"
                  style={{ left: `${a * 100}%` }}
                />
                <span
                  className={`absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 ${worse ? 'bg-signal' : 'bg-ink'}`}
                  style={{ left: `${b * 100}%` }}
                />
              </span>

              <span
                className={`text-right text-xs ${worse ? 'text-signal' : 'text-ink-60'}`}
              >
                {row.display}
                {row.material ? (
                  <span aria-hidden="true" className="ml-1 align-middle text-[9px]">
                    ●
                  </span>
                ) : null}
              </span>

              <span className="sr-only">
                {row.label}: {aLabel} {(a * 100).toFixed(1)} per cent, {bLabel}{' '}
                {(b * 100).toFixed(1)} per cent, a difference of {row.display}
                {row.material ? ', past the fixed materiality cutoff' : ''}.
              </span>
            </li>
          )
        })}
      </ul>

      <p className="m-0 max-w-2xl text-xs text-ink-40">
        Every row is on the same 0–100% scale, with ticks at 0, 50 and 100. Only fraction metrics
        are drawn; counts, costs and latencies have no shared scale with a recall rate and are
        listed in the table instead. A filled dot beside a difference means it clears the
        harness&rsquo;s fixed &plusmn;0.02 cutoff — a threshold its author chose, not a
        significance test.
        {note !== undefined ? ` ${note}` : ''}
      </p>
    </div>
  )
}
