import Link from 'next/link'

import type { EditionPreviewData } from '@/lib/home-evidence'

export function EditionPreview({ edition }: { readonly edition: EditionPreviewData | null }) {
  if (edition === null) return (
    <aside className="edition-preview edition-unavailable" data-testid="edition-preview">
      <p className="eyebrow">Ray's edition</p>
      <p>The recorded Ray edition is unavailable.</p>
      <Link href="/reader" prefetch={false} className="text-link">Open the Reader <span aria-hidden="true">→</span></Link>
    </aside>
  )
  const date = new Date(edition.frozenAt).toLocaleDateString('en-US', {
    month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC',
  })
  return (
    <aside className="edition-preview" data-testid="edition-preview" aria-label="A recorded edition from Daily">
      <div className="edition-preview-top">
        <span className="edition-wordmark" aria-hidden="true">Daily</span>
        <span className="edition-fixture">For Ray</span>
      </div>
      <p className="edition-date">{date}</p>
      <ol className="edition-stories">
        {edition.stories.map((story) => (
          <li key={story.id}>
            <p className="edition-publication">{story.publication ?? 'Publication not recorded'}{story.synthetic ? <span className="edition-synthetic"> · Authored test story</span> : null}</p>
            <h2 data-verbatim>{story.headline}</h2>
          </li>
        ))}
      </ol>
      <Link href="/reader?profile=ray" prefetch={false} className="text-link edition-open">Read Ray&apos;s edition <span aria-hidden="true">→</span></Link>
    </aside>
  )
}
