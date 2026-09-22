import Link from 'next/link'

import { FixtureStrip, toFixtureRows } from '@/components/FixtureStrip'
import { Sieve, type SieveFixture } from '@/components/Sieve'
import { Band } from '@/components/Band'
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
  const poolSize = leadSteps[0]?.survivors ?? null
  const delivered = leadSteps[leadSteps.length - 1]?.survivors ?? null
  const discardedShare =
    poolSize !== null && delivered !== null && poolSize > 0
      ? 1 - delivered / poolSize
      : null

  return (
    <div className="flex flex-col">
      <section className="frame rise flex flex-col gap-7 py-14 md:py-20">
        <p className="label m-0 text-ink-40">News that knows you · never shipped</p>
        <h1 className="display m-0 max-w-5xl text-[clamp(2.5rem,7.5vw,5.5rem)]">
          A daily edition is mostly the stories you never see.
        </h1>
        <p className="lede measure m-0 text-ink-60">
          Daily assembles one for each reader out of a dated, content-hashed corpus.
          {poolSize !== null && delivered !== null ? (
            <>
              {' '}
              For the fixture below, {poolSize.toLocaleString()} candidates became{' '}
              {delivered.toLocaleString()}
              {discardedShare !== null ? (
                <> — {(discardedShare * 100).toFixed(1)}% discarded</>
              ) : null}
              .
            </>
          ) : null}{' '}
          Every other feed shows you the survivors. This one shows you the whole corpus, the stage
          that removed each candidate, and what it logged on the way out.
        </p>
        <div className="flex flex-wrap gap-2.5 pt-1">
          <Link href="/reader" className="chip chip-on px-4 py-2.5 text-sm">
            Try the reader
          </Link>
          <Link href="/evidence" className="chip px-4 py-2.5 text-sm">
            Inspect the evaluation
          </Link>
          <Link href="/engineering" className="chip px-4 py-2.5 text-sm">
            Read the defect report
          </Link>
        </div>
      </section>

      {fixtures.length > 0 && lead !== undefined ? (
        <section className="frame flex flex-col gap-7 pb-20">
          <Band
            index="01"
            title="The sieve"
            note="One cell per candidate article, at 1:1 with the corpus"
          />
          <Sieve
            fixtures={fixtures}
            initialFixture={lead.key}
            snapshot={artifact?.provenance.snapshot.name ?? 'unknown'}
          />
        </section>
      ) : null}

      <section className="frame flex flex-col gap-7 pb-20">
        <Band index="02" title="The part worth your time" note="Why a ruler exists at all" />
        <div className="grid gap-10 lg:grid-cols-[minmax(0,34rem)_minmax(0,1fr)]">
          <div className="flex flex-col gap-5">
            <p className="prose m-0">
              Deciding which stories a person needs is a claim you can be wrong about, and
              &ldquo;the feed looks better to me&rdquo; is not evidence. So Daily carries an offline
              evaluation harness built to answer one question:{' '}
              <em>did this change make the feed better or worse, and if a story went missing,
              which stage lost it?</em>
            </p>
            <p className="prose m-0">
              It replays frozen corpora against ten adversarial reader fixtures with cached model
              responses and the network off, so the same inputs always produce the same numbers.
              That is what makes a difference between two runs mean something — and what makes it
              possible to say, out loud, when a fix makes the measured numbers worse.
            </p>
          </div>
          <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-7 self-start">
            <Readout term="Stored runs" value={String(runs)} note="imported historical scorecards" />
            <Readout
              term="Frozen corpora"
              value={String(snapshots.length)}
              note={
                corpusTotal > 0
                  ? `${corpusTotal.toLocaleString()} articles, content-hashed`
                  : 'content-hashed'
              }
            />
            <Readout term="Reader fixtures" value="10" note="adversarial, not users" />
            <Readout term="Replay spend" value="$0" note="cached responses, network off" />
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
          <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
            <FixtureStrip
              rows={toFixtureRows(
                artifact.personas,
                (key) => explorerHref({ run: artifact.run_id }, { persona: key }),
                undefined,
              )}
              caption="Each row is one reader fixture's labelled story placements for this run."
            />
            <div className="flex flex-col gap-4 self-start border-t border-rule pt-4 lg:border-0 lg:pt-0">
              <p className="prose m-0 text-base">
                An average is a way of not looking at the worst case. These ten fixtures were
                written to be hard — a New Jersey local-news reader, an Uzbek policy reader, a
                reader whose interests barely intersect the corpus at all — and the run&rsquo;s
                mean hides at least two of them completely.
              </p>
              <Link href="/evidence" className="link label self-start">
                Open the explorer
              </Link>
            </div>
          </div>
        </section>
      ) : null}

      <section className="frame flex flex-col gap-7 pb-20">
        <Band index="04" title="Start with a real failure" note="One defect, traced end to end" />
        <div className="grid gap-10 lg:grid-cols-[minmax(0,34rem)_minmax(0,1fr)]">
          <div className="flex flex-col gap-5">
            <p className="prose m-0">
              The production scorer asked a model to judge forty articles and return forty verdicts
              in order — and sent no article identifiers. When a response came back short, every
              later verdict landed on the wrong article. A New Jersey roster story was rejected for{' '}
              <em>&ldquo;discussing a music EP&rdquo;</em>. An Uzbek policy story was rejected for{' '}
              <em>&ldquo;discussing NFL team rosters&rdquo;</em>.
            </p>
            <p className="prose m-0">
              Fixing it made the measured numbers <em>worse</em>, because refusing to guess costs
              more than guessing right by accident. The regression baseline was not re-recorded.
            </p>
            <Link href="/engineering" className="link label self-start">
              Read the defect report
            </Link>
          </div>
          <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-7 self-start">
            <Readout term="Guard fires" value="63" note="one runner, one corpus, ten fixtures" signal />
            <Readout term="Worst response" value="201" note="verdicts returned for 40 articles" signal />
            <Readout term="Unwanted rate" value="+15.6" note="percentage points, after the fix" signal />
            <Readout term="Re-baselined" value="No" note="the gate still reports red" />
          </dl>
        </div>
      </section>

      <section className="frame pb-8">
        <Band index="05" title="What this site never claims" note="The repository's own truth boundaries" />
        <div className="mt-7 grid gap-x-10 gap-y-7 md:grid-cols-2">
          <Claim term="No readers">
            Daily has never shipped to the App Store. The ten reader profiles are adversarial
            evaluation fixtures, not people. Reading here creates no sessions, no impressions and
            no feedback.
          </Claim>
          <Claim term="Provisional ground truth">
            Labels are model-written with an agent editorial pass. Product-owner human review is
            outstanding, so absolute values are provisional and only run-to-run differences are
            gate-enforced.
          </Claim>
          <Claim term="No significance">
            No confidence intervals and no significance tests, because none were computed. The
            &ldquo;material&rdquo; cutoff is a fixed &plusmn;0.02 chosen by the harness&rsquo;s
            author; ten fixtures with no variance estimate cannot support more than that.
          </Claim>
          <Claim term="Live mode unbuilt">
            Signing in and receiving a feed built for you is not implemented. Live end-to-end
            behaviour is unverified, and nothing here should be read as evidence that it works.
          </Claim>
          <Claim term="Unknown stays unknown">
            Where the stored evidence cannot establish something — the evaluation protocol, the
            execution mode, whether a revision is even reachable — the artifact records the literal
            string <span className="text-unknown">unknown</span>. Never null, never zero, never
            inferred from a neighbouring field.
          </Claim>
          <Claim term="$0 of model spend">
            Every number here comes from offline replay against cached responses. The costs shown
            are reconstructed token-equivalents; actual provider spend for these replays is zero.
          </Claim>
        </div>
      </section>
    </div>
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
    <div className="border-t border-signal pt-3">
      <p className="label m-0 text-ink">{term}</p>
      <p className="m-0 mt-2 max-w-md text-sm text-ink-60">{children}</p>
    </div>
  )
}
