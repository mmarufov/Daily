import type { Metadata } from 'next'
import Link from 'next/link'

import { Band } from '@/components/Band'
import { mastheadFor, type DemoBundle, type DemoEdition, type DemoStory } from '@/lib/demo'
import { loadDemo } from '@/lib/demo-data'
import { personaLabel, personaName } from '@/lib/personas'

export const metadata: Metadata = {
  title: 'The reader',
  description:
    'A replay of an edition Daily assembled for one reader fixture against a dated, content-hashed corpus. Not today’s news, and not a person.',
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
      <div className="frame flex max-w-2xl flex-col gap-4 py-16">
        <h1 className="editorial m-0 text-3xl">The reader demo is unavailable</h1>
        <p className="prose m-0">
          The committed demo bundle could not be read. Run{' '}
          <span className="text-ink-60">npm run export:demo</span> in{' '}
          <span className="text-ink-60">web/</span> to rebuild it.
        </p>
        <ul className="m-0 flex list-none flex-col gap-1 p-0 text-xs text-signal">
          {demo.issues.map((issue, i) => (
            <li key={i}>{issue}</li>
          ))}
        </ul>
      </div>
    )
  }

  const bundle = demo.bundle
  const requested = Array.isArray(params.profile) ? params.profile[0] : params.profile
  const edition = bundle.editions.find((e) => e.persona === requested) ?? bundle.editions[0]

  if (edition === undefined) {
    return <p className="frame m-0 py-16">The demo bundle contains no editions.</p>
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
  const others = bundle.editions.filter((e) => e.persona !== edition.persona)

  return (
    <div className="flex flex-col">
      <section className="frame flex flex-col gap-6 py-12 md:py-16">
        <p className="label m-0 text-ink-40">
          Replay · corpus {bundle.snapshot} · {bundle.runner}
        </p>
        <h1 className="display m-0 text-[clamp(2rem,6vw,4.25rem)]">
          {mastheadFor(personaName(edition.persona), bundle.frozen_at)}
        </h1>
        <ReplayNotice dateLabel={dateLabel} bundle={bundle} />
      </section>

      <section className="frame flex flex-col gap-4 pb-8">
        <Band index="01" title="Read as" note="Ten fixtures, one corpus" />
        <ProfilePicker editions={bundle.editions} current={edition.persona} />
      </section>

      <section className="frame pb-20">
        {/*
          The one surface on this site that is the product rather than a
          measurement of it, so it is set on its own sheet: warmer ground,
          editorial type, no instrumentation. Daily's rule is that
          personalisation is felt and never displayed, which is why there is not
          a score, a match percentage or a "because you read X" anywhere below.
        */}
        <article className="sheet flex flex-col gap-8 p-6 sm:p-10">
          {hero !== undefined ? (
            <div className="flex flex-col gap-3">
              <Headline story={hero} className="editorial max-w-4xl text-[clamp(1.75rem,4.5vw,3.25rem)]" />
              <Publication story={hero} />
            </div>
          ) : null}

          {rows.length > 0 ? (
            <div className="flex flex-col">
              <p className="label m-0 border-b border-rule pb-2 text-ink-40">
                Also in this edition
              </p>
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
            <p className="prose m-0">
              The pipeline assembled no edition for this fixture against this corpus. That is a
              real recorded outcome, not a loading failure.
            </p>
          ) : null}
        </article>
      </section>

      <section className="frame flex flex-col gap-6 pb-20">
        <Band
          index="02"
          title="The same corpus, nine other readers"
          note={`${bundle.n_articles_in_corpus?.toLocaleString() ?? 'An unrecorded number of'} articles, one date`}
        />
        <p className="prose measure m-0 text-ink-60">
          Same corpus, same date, different newspaper — the product&rsquo;s whole claim, and the
          only place on the site you can check it without reading a number.
        </p>
        <ul className="m-0 grid list-none gap-px border border-rule bg-rule p-0 sm:grid-cols-2 lg:grid-cols-3">
          {others.map((other) => {
            const lead = other.stories[0]
            return (
              <li key={other.persona} className="bg-paper">
                <Link
                  href={{ pathname: '/reader', query: { profile: other.persona } }}
                  aria-label={`Read the ${personaName(other.persona)} edition, leading with ${lead?.headline ?? 'no stories'}`}
                  className="flex h-full flex-col gap-2 p-4 no-underline transition-colors duration-150 hover:bg-paper-secondary"
                >
                  <span className="label text-ink-40">{personaLabel(other.persona)}</span>
                  <span className="headline text-base text-ink">
                    {lead?.headline ?? 'No stories were assembled for this fixture.'}
                  </span>
                  <span className="mt-auto pt-1 text-xs text-ink-40">
                    {lead?.publication ?? 'Source not recorded'} ·{' '}
                    {other.stories.length} stor{other.stories.length === 1 ? 'y' : 'ies'}
                  </span>
                </Link>
              </li>
            )
          })}
        </ul>
      </section>

      <section className="frame flex flex-col gap-6 pb-8">
        <Band index="03" title="Live mode" note="Not implemented" />
        <div className="grid gap-10 lg:grid-cols-[minmax(0,32rem)_minmax(0,1fr)]">
          <p className="prose m-0">
            Signing in and receiving a feed built from your own words is{' '}
            <strong>not implemented here</strong>. Three things block it, all access rather than
            design — the honest version of &ldquo;coming soon&rdquo;.
          </p>
          <ol className="m-0 flex list-none flex-col gap-4 p-0">
            <Blocker n="01" term="No browser may call the API">
              CORS middleware is added only when <span className="text-ink">CORS_ORIGINS</span> is
              set. It is unset; the documented default is &ldquo;no web clients&rdquo;.
            </Blocker>
            <Blocker n="02" term="The sign-in token is the wrong audience">
              <span className="text-ink">POST /auth/google</span> verifies a token issued for the
              iOS client. A browser needs its own OAuth client for this origin.
            </Blocker>
            <Blocker n="03" term="Feedback needs a delivery that happened">
              It must echo the <span className="text-ink">feed_request_id</span>,{' '}
              <span className="text-ink">reader_generation</span> and{' '}
              <span className="text-ink">delivery_position</span> of the edition shown. Those exist
              only on a live delivery, so the contract cannot be exercised against frozen fixtures
              without inventing identifiers.
            </Blocker>
          </ol>
        </div>
        <p className="m-0 max-w-3xl border-t border-signal pt-3 text-sm text-ink-60">
          Live end-to-end behaviour is therefore <strong className="text-ink">unverified</strong>.
          These fixture editions are not reader evidence: no sessions, no impressions, no feedback.
        </p>
      </section>
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
      className={`${className} text-ink no-underline hover:text-signal`}
      rel="noreferrer"
    >
      {story.headline}
    </a>
  )
}

function Publication({ story }: { story: DemoStory }) {
  return (
    <p className="label m-0 text-ink-40">
      {story.publication ?? 'Source not recorded'}
      {story.synthetic ? (
        <span className="ml-2 text-signal">written for the evaluation, not a real publication</span>
      ) : null}
      {story.url === null && !story.synthetic ? <span className="ml-2">no link recorded</span> : null}
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
    <nav aria-label="Reader fixture">
      <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
        {editions.map((edition) => {
          const selected = edition.persona === current
          return (
            <li key={edition.persona}>
              <Link
                href={{ pathname: '/reader', query: { profile: edition.persona } }}
                aria-current={selected ? 'page' : undefined}
                className={`chip ${selected ? 'chip-on' : ''}`}
              >
                {personaName(edition.persona)}
              </Link>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

function ReplayNotice({
  dateLabel,
  bundle,
}: {
  dateLabel: string
  bundle: Pick<DemoBundle, 'snapshot' | 'snapshot_sha256' | 'n_articles_in_corpus' | 'runner' | 'run_id'>
}) {
  return (
    <aside className="grid max-w-4xl gap-x-8 gap-y-4 border-y border-signal py-4 md:grid-cols-[minmax(0,1fr)_14rem]">
      <div>
        <p className="prose m-0 text-base">
          <strong>This is a replay, not today&rsquo;s news.</strong> Every story below was
          published on or before <strong>{dateLabel}</strong>, from a frozen corpus of{' '}
          {bundle.n_articles_in_corpus?.toLocaleString() ?? 'an unrecorded number of'} articles.
        </p>
        <p className="m-0 mt-2 text-xs text-ink-60">
          The profiles are adversarial evaluation fixtures, not people; reading here creates no
          reader data.{' '}
          <Link href={{ pathname: '/evidence', query: { run: bundle.run_id } }} className="link">
            See how this edition scored
          </Link>
          .
        </p>
      </div>
      <dl className="m-0 grid grid-cols-2 gap-y-3 self-start md:grid-cols-1">
        <div>
          <dt className="label m-0 text-ink-40">Corpus</dt>
          <dd className="m-0 text-xs">{bundle.snapshot}</dd>
        </div>
        <div>
          <dt className="label m-0 text-ink-40">sha256</dt>
          <dd className="m-0 break-all text-xs text-ink-60">
            {bundle.snapshot_sha256.slice(0, 16)}…
          </dd>
        </div>
      </dl>
    </aside>
  )
}

function Blocker({ n, term, children }: { n: string; term: string; children: React.ReactNode }) {
  return (
    <li className="border-t border-rule pt-3">
      <p className="m-0 flex items-baseline gap-3">
        <span className="band-index shrink-0">{n}</span>
        <span className="label text-ink">{term}</span>
      </p>
      <p className="m-0 mt-2 pl-9 text-sm text-ink-60">{children}</p>
    </li>
  )
}
