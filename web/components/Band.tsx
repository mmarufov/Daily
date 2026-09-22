/**
 * The site's only sectioning device: a full-width hairline carrying an index,
 * a name and an optional readout.
 *
 * It replaces the usual desktop-only sidebar rail deliberately. A rail that
 * only exists above 64rem leaves the organising idea missing for half the
 * traffic; a numbered band reads identically at every width and gives the
 * pages the rhythm of a plate series, which is what this site is.
 */
export function Band({
  index,
  title,
  note,
  as: Tag = 'h2',
}: {
  readonly index: string
  readonly title: string
  readonly note?: string | undefined
  readonly as?: 'h2' | 'h3' | 'p'
}) {
  return (
    <div className="band flex-wrap">
      <span className="band-index shrink-0">{index}</span>
      <Tag className="label-lg m-0 min-w-0 flex-1 text-ink">{title}</Tag>
      {note !== undefined ? (
        // Full width below `sm`, where competing for a line with the title
        // only squeezes the title into three words per row.
        <span className="label basis-full text-ink-40 sm:basis-auto">{note}</span>
      ) : null}
    </div>
  )
}
