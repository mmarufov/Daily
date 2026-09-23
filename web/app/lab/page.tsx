import type { Metadata } from 'next'
import Link from 'next/link'

import { Band } from '@/components/Band'
import { OffendingCase } from '@/components/LabOffendingCase'
import { VerdictBadge } from '@/components/LabVerdict'
import { EXPERIMENT } from '@/lib/lab/spec'
import { loadLabIndex, loadOffendingCase, otherRuns, walkthroughs } from '@/lib/lab/data'

export const metadata: Metadata = {
  title: 'Daily Lab',
  description:
    'A controlled experiment on Daily’s batch relevance scorer: does a candidate parser associate every verdict with the article it was actually about, and refuse when it cannot? Verdicts computed by trusted code from prediction records.',
}

/** True when this run is graded differently by different generations. */
function movedGeneration(entry: { verdict_by_spec: Readonly<Record<string, string>> }): boolean {
  return new Set(Object.values(entry.verdict_by_spec)).size > 1
}

export default async function LabPage() {
  const { manifest, issues } = await loadLabIndex()
  const offending = await loadOffendingCase()

  if (manifest === null) {
    return (
      <div className="frame flex max-w-2xl flex-col gap-4 py-16">
        <h1 className="editorial m-0 text-3xl">The Lab export is unavailable</h1>
        <p className="prose m-0">
          Run <span className="text-ink-60">npm run export:lab</span> in{' '}
          <span className="text-ink-60">web/</span> to rebuild it from{' '}
          <span className="text-ink-60">backend/lab/</span>.
        </p>
        <ul className="m-0 flex list-none flex-col gap-1 p-0 text-xs text-signal">
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
  // Derived, never asserted. The claims below used to be prose, which meant
  // they stayed at their most flattering until somebody remembered to weaken
  // them. These move on their own when a run moves.
  const sandboxed = manifest.entries.filter((e) => e.runner === 'vercel-sandbox')
  const investigated = manifest.entries.filter((e) => e.investigated)

  return (
    <div className="flex flex-col">
      <section className="hero frame relative flex flex-col gap-7 py-14 md:py-20">
        <p className="label m-0 text-ink-40">Daily Lab · recorded replay, not a live run</p>
        <h1 className="display m-0 max-w-5xl text-[clamp(2.25rem,6.5vw,4.75rem)]">
          The scorer judged forty articles and never said which verdict belonged to which.
        </h1>
        <p className="lede measure m-0 text-ink-60">
          So when a response came back short, every later verdict landed on the wrong article. This
          is the experiment that measures whether a fix actually fixes it — and the independent
          checks that decide, rather than the candidate&rsquo;s own say-so.
        </p>
        <div className="flex flex-wrap gap-2.5 pt-1">
          {shown[0] !== undefined ? (
            <Link href={`/lab/${shown[0].slug}`} className="chip chip-on px-4 py-2.5 text-sm">
              Replay the investigation
            </Link>
          ) : null}
          <Link href="/engineering" className="chip px-4 py-2.5 text-sm">
            Read the original defect report
          </Link>
        </div>
      </section>

      {offending !== null ? (
        <section className="frame flex flex-col gap-7 pb-20">
          <Band index="01" title="The response that started it" note="One real batch, read from the recordings" />
          <OffendingCase data={offending} />
        </section>
      ) : null}

      <section className="frame flex flex-col gap-7 pb-20">
        <Band index="02" title="The three walkthroughs" note="Every verdict below was computed, not written" />
        <ul className="m-0 grid list-none gap-px border border-rule bg-rule p-0 lg:grid-cols-3">
          {shown.map((w) => {
            const entry = manifest.entries.find((e) => e.file === w.file)
            return (
              <li key={w.slug} className="bg-paper">
                <Link
                  href={`/lab/${w.slug}`}
                  className="flex h-full flex-col gap-3 p-4 no-underline transition-colors duration-150 hover:bg-paper-secondary"
                >
                  {entry !== undefined ? <VerdictBadge verdict={entry.verdict} small /> : null}
                  <span className="headline text-base text-ink">{w.title}</span>
                  <span className="text-xs text-ink-60">{w.blurb}</span>
                  {entry?.kind === 'seeded-control' ? (
                    <span className="label mt-auto pt-1 text-signal">Seeded control</span>
                  ) : (
                    <span className="label mt-auto pt-1 text-ink-40">{entry?.candidate_id}</span>
                  )}
                </Link>
              </li>
            )
          })}
        </ul>
      </section>

      <section className="frame flex flex-col gap-7 pb-20">
        <Band index="03" title="What the experiment asks" note={`spec ${manifest.spec_hash}`} />
        <div className="grid gap-10 lg:grid-cols-[minmax(0,32rem)_minmax(0,1fr)]">
          <div className="flex flex-col gap-5">
            <p className="prose m-0">{EXPERIMENT.question}</p>
            <p className="m-0 border-t border-signal pt-3 text-sm text-ink-60">
              The criteria were written down and hashed before any candidate ran. The hash travels
              with every verdict, so moving a threshold to get a green result changes the hash and
              invalidates the comparison.
            </p>
          </div>
          <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-7 self-start">
            <Readout term="Cases" value="64" note="42 recorded, 22 fault-injected" />
            <Readout term="Runs" value={String(manifest.entries.length)} note="3 versions, 3 seeded controls" />
            <Readout term="Accepted" value={String(accepted)} note="for human review only" />
            <Readout term="Rejected" value={String(rejected)} note="by independent checks" signal />
          </dl>
        </div>
        <div className="grid gap-8 md:grid-cols-2">
          <div>
            <p className="label m-0 text-ink-40">What it measures</p>
            <ul className="m-0 mt-2 flex list-none flex-col gap-1.5 p-0 text-sm text-ink-60">
              {EXPERIMENT.measures.map((m) => (
                <li key={m} className="border-t border-rule pt-1.5">{m}</li>
              ))}
            </ul>
          </div>
          <div>
            <p className="label m-0 text-signal">What it does not measure</p>
            <ul className="m-0 mt-2 flex list-none flex-col gap-1.5 p-0 text-sm text-ink-60">
              {EXPERIMENT.does_not_measure.map((m) => (
                <li key={m} className="claim pt-1.5 text-ink-60">{m}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {rest.length > 0 ? (
        <section className="frame flex flex-col gap-7 pb-20">
          <Band index="04" title="Every run in the set" note="Including the ones that are not walkthroughs" />
          <ul className="m-0 flex list-none flex-col gap-px border-y border-rule p-0">
            {rest.map((entry) => (
              <li key={entry.file}>
                <Link
                  href={`/lab/${entry.file.replace(/\.json$/, '')}`}
                  className="grid grid-cols-[1fr_auto] items-center gap-3 py-2 no-underline transition-colors duration-150 hover:bg-paper-secondary sm:grid-cols-[14rem_1fr_9rem]"
                >
                  <span className="text-xs text-ink">{entry.candidate_id}</span>
                  <span className="hidden text-xs text-ink-40 sm:block">
                    {entry.kind === 'seeded-control' ? 'seeded control' : 'preserved version'}
                    {/* The manifest carries the verdict under every generation
                        so this list can flag a run whose verdict *moved*
                        without loading each run — which is the one thing a
                        reader most wants pointed out and would otherwise have
                        to find by opening eight pages. */}
                    {movedGeneration(entry) ? (
                      <span className="block pt-0.5 text-signal">
                        verdict moved between criteria generations
                      </span>
                    ) : null}
                  </span>
                  <span className="text-right">
                    <VerdictBadge verdict={entry.verdict} small />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="frame flex flex-col gap-7 pb-8">
        <Band index="05" title="What the Lab never claims" note="The boundaries of this result" />
        <div className="grid gap-x-10 gap-y-6 sm:grid-cols-2 lg:grid-cols-3">
          <Claim term="Accepted is not shipped">
            It means eligible for human review under this spec hash. Merging and promotion stay a
            human decision.
          </Claim>
          <Claim term="The cases are public">
            A candidate may have been written against them, so passing does not establish
            generalisation. Fixture performance is reported as fixture performance.
          </Claim>
          <Claim term="Relevance quality is unmeasured">
            Sending article ids changes the request, which invalidates every recorded response.
            New budgeted recordings would be needed and none exist.
          </Claim>
          <Claim term="No live execution here">
            Every run replayed committed recordings offline. No inference call was made; provider
            spend for these runs is <span className="text-ink">$0</span>.
          </Claim>
          {investigated.length === 0 ? (
            <Claim term="No agent has run">
              The investigator&rsquo;s tools, budget and scope gate are implemented and tested, and
              no model has been called — there is no gateway key on this deployment. No agent
              behaviour is depicted anywhere on this site.
            </Claim>
          ) : (
            <Claim term="One agent proposal, graded like any other">
              {investigated.length} candidate{investigated.length === 1 ? ' was' : 's were'} authored by the
              investigator and faced the same scope gate, sandbox and evaluator a human patch
              faces. The model never saw the criteria or its own verdict.
            </Claim>
          )}
          {sandboxed.length === 0 ? (
            <Claim term="Nothing novel has executed">
              Every candidate here is byte-identical to a committed implementation, so all runs
              took the local path. The sandbox boundary is implemented and unexercised.
            </Claim>
          ) : (
            <Claim term="Egress is an upper bound, not a measurement">
              {sandboxed.length} of {manifest.entries.length} runs executed in an isolated microVM.
              The metered egress on those runs includes the bytes spent reading the record bundle
              back, so it is non-zero on a run that reached nothing. The negative controls are the
              direct evidence.
            </Claim>
          )}
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
