/**
 * The site's only sectioning device: a full-width hairline carrying an index,
 * a name and an optional readout.
 *
 * It replaces the usual desktop-only sidebar rail deliberately. A rail that
 * only exists above 64rem leaves the organising idea missing for half the
 * traffic; a numbered band reads identically at every width and gives the
 * pages the rhythm of a plate series, which is what this site is.
 *
 * `slug` turns the band into a jump target for PageIndex. On the long pages
 * both are derived from one shared list, so an index entry cannot point at a
 * section that is not there.
 */
export function Band({
  index,
  title,
  note,
  slug,
  as: Tag = 'h2',
}: {
  readonly index: string
  readonly title: string
  readonly note?: string | undefined
  readonly slug?: string | undefined
  readonly as?: 'h2' | 'h3' | 'p'
}) {
  return (
    <div className="band flex-wrap" id={slug}>
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

export interface Section {
  readonly index: string
  readonly slug: string
  readonly title: string
  readonly note?: string
}

/**
 * A page's own contents, as jump links.
 *
 * Only on the long pages. They are a sequence of separate arguments, and a
 * reader who wants the fourth one should not have to scroll through the first
 * three to discover it exists.
 */
export function PageIndex({ sections }: { readonly sections: readonly Section[] }) {
  return (
    <nav aria-label="On this page" className="border-y border-rule py-3">
      <ul className="m-0 flex list-none flex-wrap gap-x-5 gap-y-1.5 p-0">
        {sections.map((s) => (
          <li key={s.slug}>
            <a
              href={`#${s.slug}`}
              className="label text-ink-60 no-underline transition-colors duration-150 hover:text-signal"
            >
              <span className="text-ink-40">{s.index}</span> {s.title}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}
