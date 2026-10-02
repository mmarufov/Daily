import type { Metadata } from 'next'
import Link from 'next/link'

import { Claim } from '@/components/Claim'
import { Console } from '@/components/Console'
import { OffendingCase } from '@/components/LabOffendingCase'
import { VerdictBadge } from '@/components/LabVerdict'
import { Reveal } from '@/components/Reveal'
import { loadLabIndex, loadOffendingCase, otherRuns, walkthroughs } from '@/lib/lab/data'
import { PUBLIC_RUN_LIMITS } from '@/lib/lab/public-limits'
import { MAX_SOURCE_BYTES } from '@/lib/lab/public-run'
import { loadCaseCatalog, loadRunnerPresets } from '@/lib/lab/runner-presets'
import { ACCEPTANCE, EXPERIMENT, SPECS, specHash } from '@/lib/lab/spec'

export const metadata: Metadata = {
  title: 'The Lab',
  description:
    'Run a parser in a Vercel Sandbox microVM against 64 recorded and fault-injected model responses, graded outside the microVM by criteria hashed before any candidate ran. Every run is published.',
}

/** True when this run is graded differently by different generations. */
function movedGeneration(entry: { verdict_by_spec: Readonly<Record<string, string>> }): boolean {
  return new Set(Object.values(entry.verdict_by_spec)).size > 1
}

const KIND: Record<string, string> = {
  'agent-authored': 'written by an agent',
  'preserved-version': 'preserved version',
  'seeded-control': 'seeded control',
  'human-authored': 'written by a person',
}

export default async function LabPage() {
  const { manifest, issues } = await loadLabIndex()
  const offending = await loadOffendingCase()
  const [presets, catalog] = await Promise.all([loadRunnerPresets(), loadCaseCatalog()])
  const limits = PUBLIC_RUN_LIMITS
  // Configured limits, stated as limits. Read from the same constant the
  // route enforces, so the page cannot promise a limit the server does not.
  const limitsLine = `Limits: ${limits.per_address.runs} runs an hour from one address, ${limits.concurrent_runs} at once, and ${limits.runs_per_day} runs or ${limits.cpu_ms_per_day / 60_000} minutes of microVM CPU a day across every visitor. A live run is not added to the published runs below.`
  const recorded = catalog.filter((c) => c.origin === 'recorded-replay').length
  const faults = catalog.filter((c) => c.origin === 'fault-injection').length

  if (manifest === null) {
    return (
      <div className="frame flex max-w-2xl flex-col gap-4 py-16">
        <h1 className="editorial m-0 text-3xl">The Lab export is unavailable</h1>
        <p className="prose m-0">
          Run <span className="data">npm run export:lab</span> in <span className="data">web/</span> to rebuild it from{' '}
          <span className="data">backend/lab/</span>.
        </p>
        <ul className="m-0 flex list-none flex-col gap-1 p-0 text-[0.8125rem] text-ink-60">
          {issues.map((i) => (
            <li key={i}>{i}</li>
          ))}
        </ul>
      </div>
    )
  }

  const shown = walkthroughs(manifest)
  const rest = otherRuns(manifest, shown)
  const accepted = manifest.entries.filter((e) => e.verdict === 'accepted-for-review').length
  const rejected = manifest.entries.filter((e) => e.verdict === 'rejected').length
  // Derived, never asserted. These move on their own when a run moves.
  const sandboxed = manifest.entries.filter((e) => e.runner === 'vercel-sandbox')
  const investigated = manifest.entries.filter((e) => e.investigated)
  const proposed = investigated.filter((e) => e.runner !== 'none')

  return (
    <div className="flex flex-col">
      <section className="frame pt-14 sm:pt-20">
        <div className="grid items-end gap-x-16 gap-y-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
          <h1 className="display m-0 max-w-[14ch] text-[clamp(2.5rem,6vw,4.25rem)]">Put a parser through the Lab.</h1>
          <p className="lede m-0 text-ink-60 lg:pb-1.5">
            Your parser runs in a fresh Vercel Sandbox microVM with networking denied, against the same{' '}
            {catalog.length} model responses every published run faced: {recorded} recorded, {faults} injected faults.
            The responses are replayed. The execution and the grading are not.
          </p>
        </div>
      </section>

      <section id="run" className="frame mt-12 scroll-mt-20 sm:mt-14" aria-label="Run a parser">
        <Console
          variant="lab"
          presets={presets}
          catalog={catalog}
          recorded={null}
          limitsLine={limitsLine}
          maxBytes={MAX_SOURCE_BYTES}
        />
      </section>

      <section id="spec" className="frame mt-28 scroll-mt-20" aria-labelledby="spec-title">
        <div className="grid gap-x-16 gap-y-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <div className="flex flex-col gap-6">
            <h2 id="spec-title" className="title m-0">
              What it asks
            </h2>
            {/* The question is the hashed spec's own words. */}
            <p className="m-0 text-[1.25rem] leading-snug font-medium tracking-[-0.015em] text-ink" data-verbatim>
              {EXPERIMENT.question}
            </p>
            <div className="flex flex-col">
              <Reveal label="What it measures" items={EXPERIMENT.measures} verbatim />
              <Reveal label="What it does not measure" items={EXPERIMENT.does_not_measure} verbatim />
              <Reveal
                label="Why the criteria are hashed"
                items={[
                  'The criteria were written down and hashed before any candidate ran.',
                  'The hash travels with every verdict, so moving a threshold to get a green result changes the hash and invalidates the comparison.',
                ]}
              />
            </div>
          </div>
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <p className="m-0 text-[0.875rem] font-medium text-ink">
                {ACCEPTANCE.length} acceptance criteria, generation {EXPERIMENT.spec_version}
              </p>
              <p className="data m-0 text-ink-40">spec {manifest.spec_hash}</p>
            </div>
            <ol className="m-0 flex list-none flex-col overflow-hidden rounded-lg border border-rule p-0">
              {ACCEPTANCE.map((c) => (
                <li key={c.id} className="flex flex-col gap-1 border-b border-rule bg-sheet px-4 py-3 last:border-b-0">
                  <span className="data !text-[0.75rem] text-ink">{c.id}</span>
                  <span className="text-[0.875rem] text-ink-60" data-verbatim>
                    {c.question}
                  </span>
                </li>
              ))}
            </ol>
            <p className="m-0 text-[0.8125rem] text-ink-40">
              Every run is graded under all {SPECS.length} generations:{' '}
              {SPECS.map((s, i) => (
                <span key={s.spec_version}>
                  {i > 0 ? ', ' : ''}generation {s.spec_version} is <span className="data">{specHash(s)}</span>
                </span>
              ))}
              . A verdict that moved between them is flagged in the ledger.
            </p>
          </div>
        </div>
      </section>

      <section id="runs" className="frame mt-28 scroll-mt-20" aria-labelledby="runs-title">
        <div className="flex flex-wrap items-end justify-between gap-6">
          <div className="flex max-w-2xl flex-col gap-4">
            <h2 id="runs-title" className="title m-0">
              Every run, published
            </h2>
            <p className="prose m-0 text-ink-60">
              {manifest.entries.length} runs. {accepted} accepted for review, {rejected} rejected by the checks, and{' '}
              {manifest.entries.length - accepted - rejected} that failed before producing anything to grade. None is
              left out.
            </p>
          </div>
        </div>

        <ul className="m-0 mt-10 grid list-none gap-3 p-0 lg:grid-cols-3">
          {shown.map((w) => {
            const entry = manifest.entries.find((e) => e.file === w.file)
            return (
              <li key={w.slug}>
                <Link
                  href={`/lab/${w.slug}`}
                  className="panel group flex h-full flex-col gap-3 p-5 no-underline transition-[border-color,box-shadow] duration-200 hover:border-rule-strong hover:shadow-[var(--shadow-2)]"
                >
                  <span className="flex items-center justify-between gap-3">
                    {entry !== undefined ? <VerdictBadge verdict={entry.verdict} small /> : <span />}
                    <span className="data !text-[0.75rem] text-ink-40">{entry?.candidate_id}</span>
                  </span>
                  <span className="text-[0.9375rem] font-semibold tracking-[-0.01em] text-ink">{w.title}</span>
                  <span className="text-[0.8125rem] text-ink-60">{w.blurb}</span>
                  {entry?.kind === 'seeded-control' ? (
                    <span className="mt-auto pt-1 text-[0.8125rem] text-ink-40">Seeded control</span>
                  ) : (
                    <span className="go mt-auto pt-1 !text-[0.8125rem]">
                      {w.slug === 'accepted' ? 'Replay the investigation' : 'Open the run'}
                    </span>
                  )}
                </Link>
              </li>
            )
          })}
        </ul>

        {rest.length > 0 ? (
          <div className="mt-8 overflow-hidden rounded-lg border border-rule">
            <ul className="m-0 flex list-none flex-col p-0">
              {rest.map((entry) => (
                <li key={entry.file} className="border-b border-rule last:border-b-0">
                  <Link
                    href={`/lab/${entry.file.replace(/\.json$/, '')}`}
                    className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-0.5 bg-sheet px-4 py-2.5 no-underline transition-colors duration-150 hover:bg-paper-secondary sm:grid-cols-[16rem_minmax(0,1fr)_10rem]"
                  >
                    <span className="data truncate !text-[0.8125rem] text-ink">{entry.candidate_id}</span>
                    <span className="hidden text-[0.8125rem] text-ink-40 sm:block">
                      {KIND[entry.kind] ?? entry.kind}
                      {entry.runner === 'vercel-sandbox' ? ', ran in a microVM' : null}
                      {movedGeneration(entry) ? (
                        <span className="ml-2 text-signal">verdict moved between criteria generations</span>
                      ) : null}
                    </span>
                    <span className="text-right">
                      <VerdictBadge verdict={entry.verdict} small />
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </section>

      {offending !== null ? (
        <section className="frame mt-28" aria-labelledby="origin-title">
          <div className="flex max-w-2xl flex-col gap-4">
            <h2 id="origin-title" className="title m-0">
              The response that started it
            </h2>
            <p className="prose m-0 text-ink-60">
              The scorer judged forty articles and never said which verdict belonged to which. One real batch, read from
              the recordings.
            </p>
          </div>
          <div className="mt-10">
            <OffendingCase data={offending} />
          </div>
        </section>
      ) : null}

      <section className="frame mt-28" aria-labelledby="claims-title">
        <h2 id="claims-title" className="title m-0">
          What the Lab never claims
        </h2>
        <div className="mt-8 grid gap-x-10 gap-y-6 sm:grid-cols-2 lg:grid-cols-3">
          <Claim term="Accepted is not shipped">
            It means eligible for human review under this spec hash. Merging and promotion stay a human decision.
          </Claim>
          <Claim term="The cases are public">
            A candidate may have been written against them, so passing does not establish generalisation. Fixture
            performance is reported as fixture performance.
          </Claim>
          <Claim term="Relevance quality is unmeasured">
            Sending article ids changes the request, which invalidates every recorded response. New budgeted recordings
            would be needed and none exist.
          </Claim>
          <Claim term="Live execution, recorded responses">
            A parser run from this page executes for real, in a microVM. The model responses it parses do not: they are
            the committed recordings and fault injections, replayed, and grading calls no model. The same is true of
            every published run here. The agent-authored ones called a model to write their candidate, and each
            run&rsquo;s page states what that call cost.
          </Claim>
          {investigated.length === 0 ? (
            <Claim term="No agent has run">
              The investigator&rsquo;s tools, budget and scope gate are implemented and tested, and no model has been
              called. There is no gateway key on this deployment. No agent behaviour is depicted anywhere on this site.
            </Claim>
          ) : (
            <Claim term="Agent proposals, graded like any other">
              {investigated.length} investigator runs are published. {proposed.length} of them proposed a candidate, and
              each faced the same scope gate, sandbox and evaluator a human patch faces. The other{' '}
              {investigated.length - proposed.length} ended without a proposal and are published anyway. The model never
              saw the criteria or its own verdict.
            </Claim>
          )}
          {sandboxed.length === 0 ? (
            <Claim term="Nothing novel has executed">
              Every candidate here is byte-identical to a committed implementation, so all runs took the local path. The
              sandbox boundary is implemented and unexercised.
            </Claim>
          ) : (
            <Claim term="Egress is an upper bound, not a measurement">
              {sandboxed.length} of {manifest.entries.length} runs executed in an isolated microVM. The metered egress on
              those runs includes the bytes spent reading the record bundle back, so it is non-zero on a run that reached
              nothing. The negative controls are the direct evidence.
            </Claim>
          )}
        </div>
      </section>
    </div>
  )
}
