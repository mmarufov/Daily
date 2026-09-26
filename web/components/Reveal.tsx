/**
 * A list that collapses to its own count.
 *
 * The pattern this replaces: a label, then five to eight rows of equal-weight
 * small type, twice, side by side. Every row the same size, the same colour,
 * the same rule above it — so the eye has nowhere to land and the reader has
 * to decide what matters before they know what any of it says. The four
 * figures beside it were the only scannable thing on the screen.
 *
 * Reference material should announce its shape and stay shut. "What it
 * measures · 6" tells you there are six and that you do not have to read them
 * yet, which is the whole job of a summary. The content is unchanged and one
 * click away.
 *
 * `<details>` and not React state, deliberately: it is disclosure, the
 * platform has an element for it, it is keyboard- and screen-reader-correct
 * for free, and it works before hydration. There is no reason to own this.
 */

export function Reveal({
  label,
  items,
  tone = 'ink',
  verbatim = false,
}: {
  readonly label: string
  readonly items: readonly string[]
  /** `signal` for the things the experiment declines to claim. */
  readonly tone?: 'ink' | 'signal'
  /**
   * The items are reproduced from frozen data rather than written here.
   * `specHash` digests the spec, so its wording cannot be edited without
   * rewriting the hash eight committed artifacts already carry. Marking it
   * says so in the DOM, and keeps the house style from being applied to text
   * that is not the house's to change.
   */
  readonly verbatim?: boolean
}) {
  if (items.length === 0) return null
  return (
    <details className="reveal">
      <summary className="reveal-summary">
        <span className={`label ${tone === 'signal' ? 'text-signal' : 'text-ink'}`}>{label}</span>
        <span className="reveal-count">{items.length}</span>
        <span className="reveal-mark" aria-hidden="true" />
      </summary>
      <ul className="reveal-list" {...(verbatim ? { 'data-verbatim': true } : {})}>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </details>
  )
}
