export type CaseStatusTone = 'correct' | 'wrong' | 'unscored' | 'pending' | 'outside'

/** A second, non-color channel. The containing case or legend supplies the label. */
export function CaseStatusMark({ tone }: { tone: CaseStatusTone }) {
  return (
    <svg
      className="case-status-mark"
      data-case-mark={tone}
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {tone === 'correct' ? <path d="m3 8.5 3.4 3.5L13 4.5" /> : null}
      {tone === 'wrong' ? <path d="m4.25 4.25 7.5 7.5m0-7.5-7.5 7.5" /> : null}
      {tone === 'unscored' ? <path d="M4 8h8" /> : null}
      {tone === 'pending' ? <circle cx="8" cy="8" r="4.5" /> : null}
      {tone === 'outside' ? (
        <>
          <path d="M8 3.5v5" />
          <circle cx="8" cy="12" r=".9" fill="currentColor" stroke="none" />
        </>
      ) : null}
    </svg>
  )
}
