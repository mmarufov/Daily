/**
 * A claim the site declines to make.
 *
 * The heading is the claim; the sentence under it is the footnote. Six of
 * these printed in full is a hundred and fifty words of small type in the
 * section that exists to be *skimmed* — so the footnote opens on demand and
 * the six headings read as a list, which is what they are.
 *
 * Shared rather than local because it existed twice, identically, and the two
 * copies had already drifted: the home page's had been made a disclosure and
 * the Lab's had not, so the same section behaved differently on two pages of
 * one site. One definition removes the class of bug rather than this instance
 * of it.
 *
 * `<details>` and not React state: it is disclosure, the platform has an
 * element for it, and it is keyboard- and screen-reader-correct before
 * hydration.
 */

export function Claim({
  term,
  children,
}: {
  readonly term: string
  readonly children: React.ReactNode
}) {
  return (
    <details className="claim">
      <summary className="claim-summary">
        <span className="label text-ink">{term}</span>
        <span className="claim-more" aria-hidden="true" />
      </summary>
      <p className="m-0 mt-2 text-sm text-ink-60">{children}</p>
    </details>
  )
}
