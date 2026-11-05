import type { Metadata } from 'next'
import Link from 'next/link'

import { AnimatedDetails } from '@/components/AnimatedDetails'
import { mastheadFor, type DemoBundle, type DemoEdition, type DemoStory } from '@/lib/demo'
import { loadDemo } from '@/lib/demo-data'
import { personaName } from '@/lib/personas'

export const metadata: Metadata = {
  title: 'Reader · Daily',
  description: 'A recorded Daily edition for an evaluation fixture, built from a dated, content-hashed corpus.',
}

export default async function ReaderPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const params = await searchParams
  const demo = await loadDemo()

  if (!demo.ok) return <ReaderUnavailable issues={demo.issues} />

  const bundle = demo.bundle
  const requested = Array.isArray(params.profile) ? params.profile[0] : params.profile
  const edition = bundle.editions.find((e) => e.persona === requested) ?? bundle.editions[0]
  if (edition === undefined) return <ReaderUnavailable issues={['The recording contains no editions.']} />

  const frozen = new Date(bundle.frozen_at)
  const dateLabel = Number.isNaN(frozen.getTime())
    ? bundle.frozen_at
    : frozen.toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' })
  const [hero, ...rows] = edition.stories

  return (
    <div className="frame support-page support-reader">
      <header className="support-intro">
        <h1>{mastheadFor(personaName(edition.persona), bundle.frozen_at)}</h1>
        <ReplayNotice dateLabel={dateLabel} bundle={bundle} />
        <ProfilePicker editions={bundle.editions} current={edition.persona} />
      </header>

      <article className="sheet flex flex-col gap-8 p-6 sm:p-10">
        {hero !== undefined ? (
          <div className="flex flex-col gap-3">
            <Headline story={hero} className="editorial max-w-4xl text-[clamp(1.75rem,4.5vw,3.25rem)]" />
            <Publication story={hero} />
          </div>
        ) : null}
        {rows.length > 0 ? (
          <div className="flex flex-col">
            <p className="label m-0 border-b border-rule pb-2 text-ink-40">Also in this edition</p>
            <ul className="m-0 grid list-none grid-cols-1 gap-x-10 p-0 lg:grid-cols-2">
              {rows.map((story) => (
                <li key={story.id} className="border-b border-rule py-4">
                  <div className="flex flex-col gap-1.5">
                    <Headline story={story} className="headline text-lg" />
                    <Publication story={story} />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {edition.stories.length === 0 ? (
          <p className="prose m-0">The recorded pipeline run produced no edition for this fixture.</p>
        ) : null}
      </article>
    </div>
  )
}

function ReaderUnavailable({ issues }: { issues: readonly string[] }) {
  return (
    <div className="frame support-page support-reader">
      <header className="support-intro">
        <h1>Reader unavailable</h1>
        <p>The recorded edition could not be loaded.</p>
        <div className="flex flex-wrap gap-6">
          <Link href="/" className="text-link">Daily home</Link>
          <Link href="/lab" className="text-link">Explore the Lab</Link>
        </div>
      </header>
      <AnimatedDetails className="support-disclosure">
        <summary>Inspect loading details</summary>
        <ul className="m-0 list-disc space-y-2 pl-5 text-sm text-ink-60">
          {issues.map((issue, i) => <li key={i}>{issue}</li>)}
        </ul>
      </AnimatedDetails>
    </div>
  )
}

function Headline({ story, className }: { story: DemoStory; className: string }) {
  if (story.url === null) {
    return (
      <span className={`${className} text-ink`} data-verbatim>
        {story.headline}
        <span className="sr-only"> (no link recorded for this story)</span>
      </span>
    )
  }
  return (
    <a href={story.url} className={`${className} text-ink no-underline hover:text-ink-60`} rel="noreferrer" data-verbatim>
      {story.headline}
    </a>
  )
}

function Publication({ story }: { story: DemoStory }) {
  return (
    <p className="label m-0 text-ink-40">
      {story.publication ?? 'Source not recorded'}
      {story.synthetic ? <span className="ml-2 text-signal">synthetic evaluation story</span> : null}
      {story.url === null && !story.synthetic ? <span className="ml-2">no link recorded</span> : null}
    </p>
  )
}

function ProfilePicker({ editions, current }: { editions: readonly DemoEdition[]; current: string }) {
  return (
    <nav className="reader-profile-picker" aria-label="Reader fixture">
      <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
        {editions.map((edition) => (
          <li key={edition.persona}>
            <Link
              href={{ pathname: '/reader', query: { profile: edition.persona } }}
              aria-current={edition.persona === current ? 'page' : undefined}
              className={`chip ${edition.persona === current ? 'chip-on' : ''}`}
            >
              {personaName(edition.persona)}
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  )
}

function ReplayNotice({ dateLabel, bundle }: {
  dateLabel: string
  bundle: Pick<DemoBundle, 'snapshot' | 'snapshot_sha256' | 'n_articles_in_corpus' | 'runner' | 'run_id'>
}) {
  return (
    <div className="reader-recording">
      <p className="m-0 text-ink-60">
        <strong className="text-ink">Recorded edition.</strong> Stories were published on or before {dateLabel}. Profiles are evaluation fixtures.
      </p>
      <Link href={{ pathname: '/evidence', query: { run: bundle.run_id } }} className="text-link">
        See how this edition scored <span aria-hidden="true">↗</span>
      </Link>
      <AnimatedDetails className="support-disclosure">
        <summary>Inspect recording</summary>
        <dl className="m-0 grid gap-4 text-sm sm:grid-cols-2">
          <div><dt className="text-ink-60">Corpus</dt><dd className="m-0">{bundle.snapshot}</dd></div>
          <div><dt className="text-ink-60">Articles</dt><dd className="m-0">{bundle.n_articles_in_corpus?.toLocaleString() ?? 'Unavailable'}</dd></div>
          <div><dt className="text-ink-60">Runner</dt><dd className="m-0 break-all font-mono">{bundle.runner}</dd></div>
          <div><dt className="text-ink-60">Run</dt><dd className="m-0 break-all font-mono">{bundle.run_id}</dd></div>
          <div className="sm:col-span-2"><dt className="text-ink-60">SHA-256</dt><dd className="m-0 break-all font-mono">{bundle.snapshot_sha256}</dd></div>
        </dl>
        <p className="mb-0 text-sm text-ink-60">Reading here records no sessions, impressions, or feedback.</p>
      </AnimatedDetails>
    </div>
  )
}
