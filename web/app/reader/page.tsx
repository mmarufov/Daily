import type { Metadata } from 'next'
import Link from 'next/link'

import type { DemoBundle, DemoEdition, DemoStory } from '@/lib/demo'
import { loadDemo } from '@/lib/demo-data'

export const metadata: Metadata = {
  title: 'The reader',
  description:
    'A replay of an edition Daily assembled for one reader profile against a dated, content-hashed corpus.',
}

export default async function ReaderPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>
}) {
  const params = await searchParams
  const demo = await loadDemo()

  if (!demo.ok) {
    return (
      <div className="flex max-w-2xl flex-col gap-3">
        <h1 className="hero-headline m-0 text-3xl">The reader demo is unavailable</h1>
        <p className="body-reading m-0">
          The committed demo bundle could not be read. Run{' '}
          <code className="font-mono text-sm">npm run export:demo</code> in{' '}
          <code className="font-mono text-sm">web/</code> to rebuild it.
        </p>
        <ul className="m-0 flex list-none flex-col gap-1 p-0 text-sm text-ink-60">
          {demo.issues.map((issue, i) => (
            <li key={i} className="font-mono text-xs">
              {issue}
            </li>
          ))}
        </ul>
      </div>
    )
  }

  const bundle = demo.bundle
  const requested = Array.isArray(params.profile) ? params.profile[0] : params.profile
  const edition =
    bundle.editions.find((e) => e.persona === requested) ?? bundle.editions[0]

  if (edition === undefined) {
    return <p className="m-0">The demo bundle contains no editions.</p>
  }

  const frozen = new Date(bundle.frozen_at)
  const dateLabel = Number.isNaN(frozen.getTime())
    ? bundle.frozen_at
    : frozen.toLocaleDateString('en-GB', {
        day: 'numeric',
        month: 'long',
        year: 'numeric',
        timeZone: 'UTC',
      })

  const [hero, ...rows] = edition.stories

  return (
    <div className="flex flex-col gap-8">
      <DemoBanner dateLabel={dateLabel} bundle={bundle} />

      <ProfilePicker editions={bundle.editions} current={edition.persona} />

      <article className="flex flex-col gap-7">
        <h1 className="signature-caps m-0 text-ochre">{edition.masthead}</h1>

        {hero !== undefined ? (
          <div className="flex flex-col gap-2.5">
            <Headline story={hero} className="hero-headline text-3xl sm:text-4xl" />
            <Publication story={hero} />
          </div>
        ) : null}

        {rows.length > 0 ? (
          <div className="flex flex-col">
            <h2 className="meta-caps m-0 border-b border-sepia pb-2 text-ink-60">
              Also in this edition
            </h2>
            <ul className="m-0 flex list-none flex-col p-0">
              {rows.map((story) => (
                <li key={story.id} className="border-b border-sepia py-4">
                  <div className="flex flex-col gap-1.5">
                    <Headline story={story} className="row-headline" />
                    <Publication story={story} />
                  </div>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {edition.stories.length === 0 ? (
          <p className="body-reading m-0 max-w-2xl">
            The pipeline assembled no edition for this profile against this corpus. That is a real
            recorded outcome, not a loading failure.
          </p>
        ) : null}
      </article>

      <LiveModeNote />
    </div>
  )
}

function Headline({ story, className }: { story: DemoStory; className: string }) {
  if (story.url === null) {
    return (
      <span className={`${className} text-ink`}>
        {story.headline}
        <span className="sr-only"> (no link recorded for this story)</span>
      </span>
    )
  }
  return (
    <a
      href={story.url}
      className={`${className} text-ink no-underline hover:underline`}
      rel="noreferrer"
    >
      {story.headline}
    </a>
  )
}

function Publication({ story }: { story: DemoStory }) {
  return (
    <p className="meta-caps m-0 text-ink-60">
      {story.publication ?? 'Source not recorded'}
      {story.synthetic ? (
        <span className="ml-2 normal-case tracking-normal text-ochre">
          written for the evaluation, not a real publication
        </span>
      ) : null}
      {story.url === null && !story.synthetic ? (
        <span className="ml-2 normal-case tracking-normal">no link recorded</span>
      ) : null}
    </p>
  )
}

function ProfilePicker({
  editions,
  current,
}: {
  editions: readonly DemoEdition[]
  current: string
}) {
  return (
    <nav aria-label="Reader profile" className="flex flex-col gap-2">
      <h2 className="meta-caps m-0 text-ink-60">Read as</h2>
      <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
        {editions.map((edition) => {
          const selected = edition.persona === current
          return (
            <li key={edition.persona}>
              <Link
                href={{ pathname: '/reader', query: { profile: edition.persona } }}
                aria-current={selected ? 'page' : undefined}
                className={[
                  'rounded-button border px-3 py-1.5 text-sm no-underline',
                  selected
                    ? 'border-ink bg-ink text-paper'
                    : 'border-sepia text-ink hover:border-ink',
                ].join(' ')}
              >
                {edition.persona}
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

function DemoBanner({
  dateLabel,
  bundle,
}: {
  dateLabel: string
  bundle: Pick<DemoBundle, 'snapshot' | 'n_articles_in_corpus' | 'runner' | 'run_id'>
}) {
  return (
    <aside className="border-l-2 border-ochre pl-4">
      <p className="m-0 text-sm">
        <strong>This is a replay, not today&rsquo;s news.</strong> Every story below was published
        on or before <strong>{dateLabel}</strong> and comes from a frozen, content-hashed corpus of{' '}
        {bundle.n_articles_in_corpus?.toLocaleString() ?? 'an unrecorded number of'} articles.
      </p>
      <p className="m-0 mt-1.5 text-xs text-ink-60">
        The profiles are adversarial evaluation fixtures, not people, and this edition is the one
        the <span className="font-mono">{bundle.runner}</span> pipeline actually assembled for
        that fixture. Reading here does not create reader data and is not evidence of readership.{' '}
        <Link
          href={{ pathname: '/evidence', query: { run: bundle.run_id } }}
          className="text-ink-blue underline"
        >
          See how this edition scored
        </Link>
        .
      </p>
    </aside>
  )
}

function LiveModeNote() {
  return (
    <section className="flex flex-col gap-2 border-t border-sepia pt-6">
      <h2 className="meta-caps m-0 text-ink-60">Live mode</h2>
      <p className="m-0 max-w-2xl text-sm text-ink-60">
        Signing in and receiving a feed built for you is <strong>not implemented here</strong>, and
        this page does not pretend otherwise. Three things block it, all of them access rather than
        design:
      </p>
      <ol className="m-0 flex list-decimal flex-col gap-1 pl-6 text-sm text-ink-60">
        <li>
          The backend adds its CORS middleware only when{' '}
          <code className="font-mono text-xs">CORS_ORIGINS</code> is set, and it is unset — the
          default is documented as &ldquo;no web clients&rdquo;. No browser can call the API until
          that changes.
        </li>
        <li>
          <code className="font-mono text-xs">POST /auth/google</code> verifies a Google ID token
          issued for the iOS client. A browser flow needs a separate web OAuth client registered
          for this origin.
        </li>
        <li>
          Feedback must echo the{' '}
          <code className="font-mono text-xs">feed_request_id</code>,{' '}
          <code className="font-mono text-xs">reader_generation</code> and{' '}
          <code className="font-mono text-xs">delivery_position</code> from the edition that was
          actually shown. Those identifiers only exist on a live delivery, so the contract cannot
          be exercised against frozen fixtures without inventing them — which would be worse than
          leaving it unbuilt.
        </li>
      </ol>
      <p className="m-0 max-w-2xl text-xs text-ink-60">
        Live end-to-end behaviour is therefore <strong>unverified</strong>, and nothing on this
        site should be read as evidence that it works.
      </p>
    </section>
  )
}
