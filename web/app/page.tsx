import Link from 'next/link'

import { Console } from '@/components/Console'
import { DefectFigure } from '@/components/DefectFigure'
import { MissFigure } from '@/components/MissFigure'
import { SieveFigure } from '@/components/SieveFigure'
import { loadHomeEvidence, type FixtureRecall } from '@/lib/home'
import { PUBLIC_RUN_LIMITS } from '@/lib/lab/public-limits'
import { MAX_SOURCE_BYTES } from '@/lib/lab/public-run'
import { loadCaseCatalog, loadRunnerPresets } from '@/lib/lab/runner-presets'
import { ACCEPTANCE } from '@/lib/lab/spec'

const WORDS = ['Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve']

/** A count that opens a sentence reads as a word. */
function spell(n: number): string {
  return WORDS[n] ?? String(n)
}

function pct(x: number): string {
  return `${(x * 100).toFixed(1)}%`
}

export default async function HomePage() {
  const [evidence, presets, catalog] = await Promise.all([loadHomeEvidence(), loadRunnerPresets(), loadCaseCatalog()])
  const { sieve, ladder, misses, defect, guard, recorded, lab, corpus, run } = evidence
  const limits = PUBLIC_RUN_LIMITS
  const limitsLine = `Runs are real and metered: ${limits.per_address.runs} an hour from one address, ${limits.concurrent_runs} at once, and ${limits.runs_per_day} a day across every visitor.`
  const recordedCount = catalog.filter((c) => c.origin === 'recorded-replay').length
  const faultCount = catalog.filter((c) => c.origin === 'fault-injection').length

  const pool = sieve?.steps[0]?.survivors ?? null
  const delivered = sieve?.steps[sieve.steps.length - 1]?.survivors ?? null
  const lookback = misses?.stages[0]

  return (
    <div className="flex flex-col">
      {/* ------------------------------------------------------- hero --- */}
      <section className="frame pt-14 sm:pt-20 lg:pt-24">
        <div className="grid items-end gap-x-16 gap-y-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
          <h1 className="display m-0 max-w-[13ch] text-[clamp(2.75rem,7vw,5rem)]">Find out if the fix fixes anything.</h1>
          <div className="flex flex-col gap-5 lg:pb-2">
            <p className="lede m-0 text-ink-60">
              Daily Lab runs a proposed fix in a Vercel Sandbox microVM against {catalog.length} cases built to break
              it, grades it by criteria fixed in advance, and publishes where it fails.
            </p>
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
              <a href="#method" className="go">
                How it decides
              </a>
              <Link href="/lab" className="go">
                Every published run
              </Link>
            </div>
          </div>
        </div>

        <div className="mt-12 sm:mt-16">
          <Console
            variant="hero"
            presets={presets}
            catalog={catalog}
            recorded={recorded}
            limitsLine={limitsLine}
            maxBytes={MAX_SOURCE_BYTES}
          />
        </div>
      </section>

      {/* ------------------------------------------------ the subject --- */}
      {sieve !== null && pool !== null && delivered !== null ? (
        <section className="frame mt-32 sm:mt-40" aria-labelledby="subject">
          <div className="grid gap-x-16 gap-y-10 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
            <div className="flex flex-col gap-5">
              <h2 id="subject" className="title m-0">
                {spell(sieve.steps.length)} stages between {pool.toLocaleString('en-US')} articles and one edition.
              </h2>
              <p className="prose m-0 text-ink-60">
                The Lab measures Daily, a personalised news pipeline that has never had a reader. Each square is a
                candidate article for one reader on one frozen day. {delivered} make the edition.
              </p>
              <Link href={`/evidence?persona=${sieve.fixture}&view=funnel`} className="go">
                Every reader, every stage
              </Link>
            </div>
            <SieveFigure steps={sieve.steps} name={sieve.name} snapshot={run?.snapshot ?? ''} />
          </div>
        </section>
      ) : null}

      {/* ------------------------------------- retrieval had already lost --- */}
      {misses !== null && lookback !== undefined ? (
        <section className="frame mt-32 sm:mt-40" aria-labelledby="ranking">
          <div className="grid gap-x-16 gap-y-10 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
            <div className="flex flex-col gap-5">
              <h2 id="ranking" className="title m-0">
                Better ranking cannot save it.
              </h2>
              <p className="prose m-0 text-ink-60">
                Across ten test readers, {misses.total} stories they needed never arrived. {lookback.count} were gone
                before anything had judged them: they were older than the newest 300 rows the pipeline loads.
              </p>
              <p className="prose m-0 text-ink-60">Make everything after that perfect, and see what comes back.</p>
            </div>
            <div className="flex min-w-0 flex-col gap-14">
              <MissFigure stages={misses.stages} total={misses.total} />
              {ladder !== null && run !== null ? (
                <Ladder reached={ladder.reached} delivered={ladder.delivered} fixtures={ladder.fixtures} k={run.k} />
              ) : null}
            </div>
          </div>
        </section>
      ) : null}

      {/* ---------------------------------------- the fix made it worse --- */}
      {defect !== null ? (
        <section className="frame mt-32 sm:mt-40" aria-labelledby="defect">
          <div className="flex max-w-3xl flex-col gap-5">
            <h2 id="defect" className="title m-0">
              The fix made the numbers worse.
            </h2>
            <p className="prose m-0 text-ink-60">
              The scorer sends {defect.articles.length} articles and asks for a verdict on each, in order. No id travels
              either way, so position is the only link. This response came back with {defect.returned}. The fix refuses
              to guess. Turn it on.
            </p>
          </div>
          <div className="mt-12">
            <DefectFigure batch={defect} experiment={guard} />
          </div>
        </section>
      ) : null}

      {/* ------------------------------------------------- the method --- */}
      <section id="method" className="frame mt-32 scroll-mt-20 sm:mt-40" aria-labelledby="method-title">
        <div className="flex max-w-3xl flex-col gap-5">
          <h2 id="method-title" className="title m-0">
            Built so a fix cannot grade itself.
          </h2>
          <p className="prose m-0 text-ink-60">
            The candidate writes one file. Everything that decides whether it passed lives somewhere the candidate
            cannot reach, and was written down before it existed.
          </p>
        </div>

        <div className="mt-12 grid gap-px overflow-hidden rounded-xl border border-rule bg-rule md:grid-cols-2">
          <Method title="Criteria first">
            <p className="data m-0 text-[clamp(1.25rem,2.4vw,1.75rem)] tracking-[-0.02em] text-ink">
              {lab?.specHash ?? 'unavailable'}
            </p>
            <p className="m-0 text-[0.875rem] text-ink-60">
              {ACCEPTANCE.length} criteria, hashed before any candidate ran. The hash travels with every verdict, so
              a threshold moved afterwards breaks the comparison in public.
            </p>
            <ul className="m-0 mt-1 flex list-none flex-wrap gap-1.5 p-0" aria-label="The criteria">
              {ACCEPTANCE.map((c) => (
                <li key={c.id} title={c.question} className="data rounded-md bg-paper-secondary px-2 py-1 !text-[0.75rem] text-ink-60">
                  {c.id}
                </li>
              ))}
            </ul>
          </Method>

          <div className="flex flex-col gap-px bg-rule [&>*:last-child]:flex-1">
            <Method title={`${catalog.length} cases built to break it`}>
              <p className="m-0 text-[0.875rem] text-ink-60">
                {recordedCount} are real model responses from the pipeline, replayed. {faultCount} are injected
                faults, each made to catch one specific mistake, such as a response the right length in the wrong
                order.
              </p>
              <CaseStrip recorded={recordedCount} faults={faultCount} />
            </Method>
            <Method title="Isolation that is checked, not assumed">
              <p className="m-0 text-[0.875rem] text-ink-60">
                Each run gets a fresh microVM with networking denied. The grader never enters it. Afterwards four
                probes run inside the same microVM, and the run counts only if all four fail to reach anything.
              </p>
            </Method>
          </div>

          {lab !== null ? (
            <Method title="Every run is published, including the failures">
              <RunLedger accepted={lab.accepted} rejected={lab.rejected} total={lab.runs} />
              <Link href="/lab" className="go">
                Open the ledger
              </Link>
            </Method>
          ) : null}

          {corpus !== null ? (
            <Method title="Ground truth, with its limits stated">
              <p className="readout-sm m-0">{corpus.labels.toLocaleString('en-US')}</p>
              <p className="m-0 text-[0.875rem] text-ink-60">
                relevance labels across {corpus.snapshots} content-hashed corpus snapshots. All were written by a
                model. None has been reviewed by a person, so absolute numbers are provisional and comparisons are
                the point.
              </p>
            </Method>
          ) : null}
        </div>
      </section>

      {/* ------------------------------------------------------ close --- */}
      <section className="frame mt-32 sm:mt-40">
        <div className="flex flex-col items-start gap-6 border-t border-rule pt-12 sm:flex-row sm:items-end sm:justify-between">
          <h2 className="title m-0 max-w-[18ch]">The cases are public. The criteria are fixed. Bring a parser.</h2>
          <Link href="/lab#run" className="btn btn-primary">
            Open the Lab
          </Link>
        </div>
      </section>
    </div>
  )
}

function Method({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-4 bg-sheet p-6 sm:p-8">
      <h3 className="m-0 text-[0.9375rem] font-semibold tracking-[-0.01em] text-ink">{title}</h3>
      {children}
    </div>
  )
}

function CaseStrip({ recorded, faults }: { recorded: number; faults: number }) {
  return (
    <div className="flex flex-col gap-2" role="img" aria-label={`${recorded} recorded cases and ${faults} fault-injected cases`}>
      <div className="flex flex-wrap gap-[3px]">
        {Array.from({ length: recorded }, (_, i) => (
          <span key={i} className="cell" data-tone="mid" style={{ ['--c' as string]: '9px' }} />
        ))}
      </div>
      <div className="flex flex-wrap gap-[3px]">
        {Array.from({ length: faults }, (_, i) => (
          <span key={i} className="cell" data-tone="open" style={{ ['--c' as string]: '9px' }} />
        ))}
      </div>
    </div>
  )
}

function RunLedger({ accepted, rejected, total }: { accepted: number; rejected: number; total: number }) {
  const failed = total - accepted - rejected
  const rows: { label: string; n: number; tone: string }[] = [
    { label: 'accepted for review', n: accepted, tone: 'ink' },
    { label: 'rejected by the checks', n: rejected, tone: 'loss' },
    { label: 'failed before producing anything to grade', n: failed, tone: 'ghost' },
  ]
  return (
    <div className="flex flex-col gap-3">
      <p className="m-0 flex items-baseline gap-2">
        <span className="readout-sm">{total}</span>
        <span className="text-[0.875rem] text-ink-60">runs, all of them on the site</span>
      </p>
      <div className="flex flex-wrap gap-[3px]" role="img" aria-label={rows.map((r) => `${r.n} ${r.label}`).join(', ')}>
        {rows.flatMap((r) =>
          Array.from({ length: r.n }, (_, i) => (
            <span key={`${r.label}-${i}`} className="cell" data-tone={r.tone} style={{ ['--c' as string]: '12px' }} />
          )),
        )}
      </div>
      <ul className="m-0 flex list-none flex-col gap-1 p-0 text-[0.8125rem] text-ink-60">
        {rows.map((r) => (
          <li key={r.label} className="flex items-center gap-2">
            <span className="cell" data-tone={r.tone} style={{ ['--c' as string]: '9px' }} />
            <span className="data w-6 text-ink">{r.n}</span>
            {r.label}
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * The ladder: needed stories that reached the scorer, and that were
 * delivered, for the run and for each reader. A reader at zero is labelled,
 * in the loss colour, at full size.
 */
function Ladder({
  reached,
  delivered,
  fixtures,
  k,
}: {
  reached: number
  delivered: number
  fixtures: readonly FixtureRecall[]
  k: number
}) {
  const zeros = fixtures.filter((f) => f.delivered === 0)
  const max = Math.max(...fixtures.map((f) => f.delivered))
  const scale = Math.max(0.5, Math.ceil(max * 10) / 10)
  return (
    <div className="flex flex-col gap-5">
      <div className="grid grid-cols-2 gap-6 border-t border-rule pt-6 sm:grid-cols-3">
        <div>
          <p className="readout-sm m-0">{pct(reached)}</p>
          <p className="m-0 mt-1 text-[0.8125rem] text-ink-60">of needed stories even reached the scorer</p>
        </div>
        <div>
          <p className="readout-sm m-0">{pct(delivered)}</p>
          <p className="m-0 mt-1 text-[0.8125rem] text-ink-60">were delivered, the mean over ten readers</p>
        </div>
        <div>
          <p className={`readout-sm m-0 ${zeros.length > 0 ? 'text-signal' : ''}`}>{zeros.length > 0 ? '0%' : pct(Math.min(...fixtures.map((f) => f.delivered)))}</p>
          <p className="m-0 mt-1 text-[0.8125rem] text-ink-60">
            {zeros.length === 0
              ? 'for the worst-served reader'
              : `for ${zeros.map((z) => z.name).join(' and ')}, who received none of ${zeros.length === 1 ? 'the stories they needed' : 'theirs'}`}
          </p>
        </div>
      </div>

      <figure className="m-0 flex flex-col gap-2">
        <ol className="m-0 flex list-none flex-col gap-1.5 p-0" aria-label="Needed stories delivered, per reader">
          {fixtures.map((f) => (
            <li key={f.key} className="grid grid-cols-[5.5rem_minmax(0,1fr)_3.5rem] items-center gap-3 text-[0.8125rem]">
              <span className="truncate text-ink-60">{f.name}</span>
              <span className="relative h-2.5 overflow-hidden rounded-[3px] bg-paper-secondary">
                <span
                  className="absolute inset-y-0 left-0 rounded-[3px] bg-ink"
                  style={{ width: `${(f.delivered / scale) * 100}%` }}
                />
              </span>
              <span className={`data text-right !text-[0.75rem] ${f.delivered === 0 ? 'text-signal' : 'text-ink'}`}>
                {pct(f.delivered)}
              </span>
            </li>
          ))}
        </ol>
        <figcaption className="pl-[6.25rem] text-[0.75rem] text-ink-40">
          Needed stories delivered, per reader, capped at the {k} slots of an edition. Scale 0 to {Math.round(scale * 100)}%.
        </figcaption>
      </figure>
    </div>
  )
}
