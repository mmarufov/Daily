import Link from 'next/link'

import { loadIndex } from '@/lib/data'

export default async function HomePage() {
  const index = await loadIndex()
  const runs = index.entries.filter((e) => !e.is_baseline).length
  const snapshots = index.manifest?.snapshots ?? []
  const corpusTotal = snapshots.reduce((sum, s) => sum + (s.n_articles ?? 0), 0)

  return (
    <div className="flex flex-col gap-14">
      <section className="flex flex-col gap-5">
        <p className="signature-caps m-0 text-ochre">news that knows you</p>
        <h1 className="hero-headline m-0 max-w-2xl text-4xl sm:text-5xl">
          A daily edition built from your own words — and a ruler that says whether it worked.
        </h1>
        <p className="dek m-0 max-w-2xl text-ink-60">
          You describe yourself in a short conversation. Daily finds credible publications for
          those interests, works out what each story is actually about, and sets a feed that reads
          like a hand-set magazine with your name on the masthead. No match scores, no
          &ldquo;because you read X&rdquo; receipts.
        </p>
        <div className="flex flex-wrap gap-3 pt-1">
          <Link
            href="/reader"
            className="rounded-button border border-ink bg-ink px-4 py-2 text-sm font-semibold text-paper no-underline"
          >
            Try the reader
          </Link>
          <Link
            href="/evidence"
            className="rounded-button border border-sepia px-4 py-2 text-sm font-semibold text-ink no-underline hover:border-ink"
          >
            Inspect the evaluation
          </Link>
        </div>
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="meta-caps m-0 text-ink-60">The part worth your time</h2>
        <p className="body-reading m-0 max-w-2xl">
          Deciding which stories a person needs is a claim you can be wrong about, and &ldquo;the
          feed looks better to me&rdquo; is not evidence. So Daily carries an evaluation harness
          built to answer one question: <em>did this change make the feed better or worse, and if a
          story went missing, which stage lost it?</em>
        </p>
        <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
          <Stat term="Stored runs" value={String(runs)} note="imported historical scorecards" />
          <Stat
            term="Frozen corpora"
            value={String(snapshots.length)}
            note={corpusTotal > 0 ? `${corpusTotal.toLocaleString()} articles total` : 'content-hashed'}
          />
          <Stat term="Reader fixtures" value="10" note="adversarial, not users" />
          <Stat term="Replay cost" value="$0" note="cached responses, network off" />
        </dl>
      </section>

      <section className="flex flex-col gap-4 border-t border-sepia pt-8">
        <h2 className="meta-caps m-0 text-ink-60">Start with a real failure</h2>
        <p className="body-reading m-0 max-w-2xl">
          The clearest way in is one story that should have reached a reader and did not. The
          engineering notes follow a single defect from the symptom in a stored scorecard to the
          exact lines that caused it, and to the test that now fails without the fix.
        </p>
        <Link href="/engineering" className="text-ink-blue underline">
          Read the debugging case study
        </Link>
      </section>
    </div>
  )
}

function Stat({ term, value, note }: { term: string; value: string; note: string }) {
  return (
    <div>
      <dt className="meta-caps m-0 text-ink-60">{term}</dt>
      <dd className="m-0 mt-1 font-serif text-3xl font-bold tabular-nums">{value}</dd>
      <p className="m-0 text-xs text-ink-60">{note}</p>
    </div>
  )
}
