import Link from 'next/link'

import { Band } from '@/components/Band'
import { FixtureStrip, toFixtureRows } from '@/components/FixtureStrip'
import { Sieve, type SieveFixture } from '@/components/Sieve'
import { defaultEntry, loadArtifact, loadIndex } from '@/lib/data'
import { explorerHref } from '@/lib/url-state'

export default async function HomePage() {
  const index = await loadIndex()
  const runs = index.entries.filter((e) => !e.is_baseline).length
  const snapshots = index.manifest?.snapshots ?? []
  const corpusTotal = snapshots.reduce((sum, s) => sum + (s.n_articles ?? 0), 0)

  const entry = defaultEntry(index.entries)
  const load = entry === undefined ? null : await loadArtifact(entry)
  const artifact = load?.ok === true ? load.artifact : null

  const fixtures: readonly SieveFixture[] =
    artifact?.personas.map((p) => ({ key: p.key, steps: p.funnel })) ?? []
  const lead = fixtures.find((f) => f.key === 'ray') ?? fixtures[0]
  const leadSteps = lead?.steps ?? []
  const pool = leadSteps[0]?.survivors ?? null
  const delivered = leadSteps[leadSteps.length - 1]?.survivors ?? null

  return (
    <div className="flex flex-col">
      <section className="hero frame rise relative flex flex-col gap-7 py-16 md:py-24">
        <p className="label m-0 flex items-center gap-2.5 text-ink-40">
          <span className="pip" aria-hidden="true" />
          News that knows you · never shipped
        </p>
        <h1 className="display m-0 max-w-5xl text-[clamp(2.5rem,7.5vw,5.5rem)]">
          A daily edition is mostly{' '}
          {/* The subject of the sentence and of the site. Marked rather than
              coloured: an underline that sits in the descender space reads as
              emphasis without spending the one colour that means loss. */}
          <span className="struck">the stories you never see.</span>
        </h1>
        <p className="lede measure m-0 text-ink-60">
          {pool !== null && delivered !== null ? (
            <>
              {pool.toLocaleString()} candidates became {delivered.toLocaleString()}.
            </>
          ) : null}{' '}
          Other feeds show you the survivors. This one shows the whole corpus, and which stage
          threw each candidate away.
        </p>
        <nav
          aria-label="Main"
          className="mt-2 grid gap-px border border-rule bg-rule sm:grid-cols-2 lg:grid-cols-4"
        >
          <Entry n="01" href="/reader" term="Reader" note="One edition, replayed from a frozen corpus" />
          <Entry n="02" href="/evidence" term="Evidence" note="Every metric, fixture and story trace" />
          <Entry n="03" href="/lab" term="Lab" note="A controlled experiment on the scorer" />
          <Entry n="04" href="/engineering" term="Defect report" note="One bug, followed end to end" />
        </nav>
      </section>

      {fixtures.length > 0 && lead !== undefined ? (
        <section className="frame flex flex-col gap-7 pb-20">
          <Band index="01" title="The sieve" note="One cell per candidate article" />
          <Sieve
            fixtures={fixtures}
            initialFixture={lead.key}
            snapshot={artifact?.provenance.snapshot.name ?? 'unknown'}
          />
        </section>
      ) : null}

      <section className="frame flex flex-col gap-7 pb-20">
        <Band index="02" title="Why a ruler exists" />
        <div className="grid gap-10 lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)]">
          <p className="prose m-0">
            &ldquo;The feed looks better to me&rdquo; is not evidence. So Daily carries an offline
            harness that replays frozen corpora against ten adversarial fixtures with the network
            off — same inputs, same numbers, every time. That is what lets a difference between two
            runs mean something, and what makes it possible to say out loud when a fix made the
            measured numbers worse.
          </p>
          <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-7 self-start">
            <Readout term="Stored runs" value={String(runs)} note="imported, not re-executed" />
            <Readout
              term="Frozen corpora"
              value={String(snapshots.length)}
              note={corpusTotal > 0 ? `${corpusTotal.toLocaleString()} articles` : 'content-hashed'}
            />
            <Readout term="Reader fixtures" value="10" note="adversarial, not users" />
            <Readout term="Replay spend" value="$0" note="cached, network off" />
          </dl>
        </div>
      </section>

      {artifact !== null ? (
        <section className="frame flex flex-col gap-7 pb-20">
          <Band
            index="03"
            title="Every fixture, no averaging"
            note={`${artifact.provenance.runner} · ${artifact.provenance.snapshot.name}`}
          />
          <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,20rem)]">
            <FixtureStrip
              rows={toFixtureRows(
                artifact.personas,
                (key) => explorerHref({ run: artifact.run_id }, { persona: key }),
                undefined,
              )}
            />
            <div className="flex flex-col gap-4 self-start border-t border-rule pt-4 lg:border-0 lg:pt-0">
              <p className="prose m-0 text-base">
                An average is a way of not looking at the worst case. These fixtures were written
                to be hard, and the run&rsquo;s mean of 22.1% hides two of them completely.
              </p>
              <Link href="/evidence" className="link label self-start">
                Open the explorer
              </Link>
            </div>
          </div>
        </section>
      ) : null}

      <section className="frame flex flex-col gap-7 pb-20">
        <Band index="04" title="Start with a real failure" />
        <div className="grid gap-10 lg:grid-cols-[minmax(0,30rem)_minmax(0,1fr)]">
          <div className="flex flex-col gap-5">
            <p className="prose m-0">
              The scorer asked a model to judge forty articles and return forty verdicts in order,
              and sent no article ids. When a response came back short, every later verdict landed
              on the wrong article — a New Jersey roster story rejected for{' '}
              <em>&ldquo;discussing a music EP&rdquo;</em>.
            </p>
            <p className="prose m-0">
              Fixing it made the measured numbers <em>worse</em>. The baseline was not re-recorded.
            </p>
            <Link href="/engineering" className="link label self-start">
              Read the defect report
            </Link>
          </div>
          <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-7 self-start">
            <Readout term="Guard fires" value="63" note="one run, ten fixtures" signal />
            <Readout term="Worst response" value="201" note="verdicts for 40 articles" signal />
            <Readout term="Unwanted rate" value="+15.6" note="points, after the fix" signal />
            <Readout term="Re-baselined" value="No" note="the gate still reports red" />
          </dl>
        </div>
      </section>

      <section className="frame pb-8">
        <Band index="05" title="What this site never claims" />
        <div className="mt-7 grid gap-x-10 gap-y-6 sm:grid-cols-2 lg:grid-cols-3">
          <Claim term="No readers">
            Never shipped. The ten profiles are evaluation fixtures, not people, and reading here
            creates no data.
          </Claim>
          <Claim term="Provisional ground truth">
            Labels are model-written with an agent pass. Human review is outstanding, so absolute
            values are provisional.
          </Claim>
          <Claim term="No significance">
            No confidence intervals; none were computed. &ldquo;Material&rdquo; is a fixed
            &plusmn;0.02 the harness&rsquo;s author chose.
          </Claim>
          <Claim term="Live mode unbuilt">
            Signing in is not implemented. Live end-to-end behaviour is unverified.
          </Claim>
          <Claim term="Unknown stays unknown">
            What the evidence cannot establish is recorded as{' '}
            <span className="text-unknown">unknown</span> — never null, never zero.
          </Claim>
          <Claim term="$0 of model spend">
            Costs shown are reconstructed token-equivalents. Actual provider spend is zero.
          </Claim>
        </div>
      </section>
    </div>
  )
}

function Entry({
  n,
  href,
  term,
  note,
}: {
  n: string
  href: '/reader' | '/evidence' | '/lab' | '/engineering'
  term: string
  note: string
}) {
  return (
    <Link href={href} className="entry group">
      <span className="flex items-baseline justify-between gap-3">
        <span className="label text-ink">{term}</span>
        <span className="band-index transition-colors duration-200 group-hover:text-ink">{n}</span>
      </span>
      <span className="mt-1.5 block text-xs text-ink-60">{note}</span>
      {/* The rule fills left-to-right on hover. A colour change says "this is
          a link"; a rule that draws itself says "this one, now" — and it is
          the same gesture the sieve makes, which is the page's own idiom. */}
      <span className="entry-rule" aria-hidden="true" />
    </Link>
  )
}

function Readout({
  term,
  value,
  note,
  signal,
}: {
  term: string
  value: string
  note: string
  signal?: boolean
}) {
  return (
    <div>
      <dt className="label m-0 text-ink-40">{term}</dt>
      <dd className={`readout-sm m-0 mt-1.5 text-3xl ${signal === true ? 'text-signal' : ''}`}>
        {value}
        {/* Inside the <dd>, not beside it: a <div> within a <dl> may contain
            only <dt> and <dd>, and the note describes the value anyway. */}
        <span className="block font-sans text-xs font-normal tracking-normal text-ink-40">
          {note}
        </span>
      </dd>
    </div>
  )
}

function Claim({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="claim">
      <p className="label m-0 text-ink">{term}</p>
      <p className="m-0 mt-2 text-sm text-ink-60">{children}</p>
    </div>
  )
}
