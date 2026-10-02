import type { Metadata } from 'next'
import Link from 'next/link'

import { Band } from '@/components/Band'
import { Misalignment } from '@/components/Misalignment'
import { GUARD_EXPERIMENT_HREF, loadGuardExperiment, type GuardExperiment } from '@/lib/guard-experiment'
import { personaName } from '@/lib/personas'
import { explorerHref } from '@/lib/url-state'

export const metadata: Metadata = {
  title: 'Defect report',
  description:
    'One defect in Daily’s batch scorer, followed from a stored scorecard to the lines that caused it, and what refusing to guess cost in the September 21 recorded experiment.',
}

const RUN = 'prod-llm__2026-08-31__47edb50'

/** The rows the cost table shows, in the experiment's own metric keys. */
const ROWS: readonly { key: string; label: string; lowerIsBetter: boolean }[] = [
  { key: 'recall_at_k_mean', label: 'Needed stories delivered (capped recall@12)', lowerIsBetter: false },
  { key: 'raw_recall_at_k_mean', label: 'Raw recall@12', lowerIsBetter: false },
  { key: 'recall_at_retrieval_mean', label: 'Needed stories that reached the scorer', lowerIsBetter: false },
  { key: 'never_rate_mean', label: 'Unwanted stories delivered', lowerIsBetter: true },
  { key: 'need_to_know_recall_mean', label: 'Need-to-know recall', lowerIsBetter: false },
  { key: 'needle_recall_mean', label: 'Planted-needle recall', lowerIsBetter: false },
  { key: 'lookalike_rate_mean', label: 'Lookalike rate', lowerIsBetter: true },
]

export default async function EngineeringPage() {
  const experiment = await loadGuardExperiment()
  return (
    <div className="flex flex-col">
      <section className="frame pt-14 sm:pt-20">
        <h1 className="display m-0 max-w-4xl text-[clamp(2.25rem,5.5vw,4rem)]">
          A story the reader needed, rejected for discussing something else entirely
        </h1>
        <p className="lede measure m-0 mt-6 text-ink-60">
          One defect in the batch scorer, from the symptom in a stored scorecard to the lines that caused it, and what
          refusing to guess cost.
        </p>
      </section>

      <section className="frame mt-24 flex flex-col gap-6" id="symptom">
        <Band index="01" title="A reason about the wrong story" note="Actual traces from the August 31 scorecard" />
        <ul className="m-0 grid list-none gap-px overflow-hidden rounded-lg border border-rule bg-rule p-0 lg:grid-cols-3">
          <Offset
            persona="ray"
            story="a00407"
            title="Giants' 53-man roster to include Odell Beckham"
            reason="The article discusses a music EP, which is irrelevant to the user's interests."
            stage="blended"
          />
          <Offset
            persona="dilshod"
            story="n-dil-02"
            title="Mirziyoyev signs decree abolishing exit visa-style registration"
            reason="The article discusses NFL team rosters, which is not relevant to the user's interests."
            stage="blended"
            needle
          />
          <Offset
            persona="farrukh"
            story="a00037"
            title="World mostly shrugs off Bessent's 'D-Day' Iran sanctions threat"
            reason="The article discusses China's manufacturing activity…"
            stage="rank"
          />
        </ul>
        <p className="measure m-0 text-[0.875rem] text-ink-60">
          The middle one is the sharpest: <span className="data">n-dil-02</span> is a planted needle, injected so its
          right answer is known by construction, and it was rejected on another article&rsquo;s reasoning. These
          examples show shifted associations. They do not establish that every verdict in every batch was wrong.
        </p>
      </section>

      <section className="frame mt-24 flex flex-col gap-6" id="cause">
        <Band index="02" title="The missing identity contract" note="Order was the only link" />
        <div className="grid gap-10 lg:grid-cols-2">
          <div className="flex flex-col gap-5">
            <p className="prose m-0">
              The scorer asks for one verdict per article, in order, without an article identifier. Its positional
              parser logs a count mismatch and then keeps assigning output by position.
            </p>
            <p className="prose m-0">
              One recorded Lab case has 40 inputs and 254 verdicts. Once a response shifts, a plausible reason attaches
              to an unrelated article, and nothing downstream can tell.
            </p>
            <a
              className="go"
              href="https://github.com/mmarufov/Daily/blob/b95a9a63562a6c7b7c36550f1ca7f90ce5e4ceaa/backend/app/services/openai_service.py#L647"
            >
              The audited parser revision
            </a>
          </div>
          <Misalignment />
        </div>
      </section>

      <section className="frame mt-24 flex flex-col gap-6" id="cost">
        <Band index="03" title="Refusing to guess has a cost" note="The September 21 recorded experiment" />
        {experiment === null ? (
          <p role="status" className="m-0 text-[0.875rem] text-unknown">
            The recorded experiment could not be read, so no cost is shown.
          </p>
        ) : (
          <div className="grid items-start gap-10 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
            <CostTable experiment={experiment} />
            <div className="flex flex-col gap-5">
              <p className="prose m-0">
                The count guard discards a mismatched batch and retries. A response with the right count in the wrong
                order still passes, so counting is a partial contract. Discarded batches lose their relevance signal,
                and the delivered feed did not improve.
              </p>
              <p className="m-0 text-[0.875rem] text-ink-60">
                {experiment.historical_test_result.failed} regression checks failed and the baseline was not
                re-recorded. The guard scorecard names the base checkout,{' '}
                <span className="data">{experiment.guard.source.recorded_git_sha}</span>, not a commit containing the
                guard, and the exact guard bytes were not kept. The two scorecards recorded different cache keys. This
                is historical evidence, not a controlled estimate.
              </p>
              <a className="go" href={GUARD_EXPERIMENT_HREF}>
                The experiment, its source hashes and limits
              </a>
            </div>
          </div>
        )}
      </section>

      <section className="frame mt-24 flex flex-col gap-6" id="next">
        <Band index="04" title="Correct association comes first" note="Quality remains a separate question" />
        <div className="grid gap-10 lg:grid-cols-2">
          <p className="prose m-0">
            The Lab makes the identity contract testable. Submit a parser, run it against the public cases in a Sandbox
            microVM, and read failures computed by code it never sees.
          </p>
          <div className="flex flex-col gap-5">
            <p className="prose m-0">
              Passing those checks does not prove better relevance. The quality scorecards use provisional model and
              agent labels, and a changed scoring request needs new recordings.
            </p>
            <Link className="btn btn-primary self-start" href="/lab#run">
              Run a parser
            </Link>
          </div>
        </div>
      </section>
    </div>
  )
}

function CostTable({ experiment }: { experiment: GuardExperiment }) {
  const rows = ROWS.flatMap((r) => {
    const before = experiment.original.summary[r.key]
    const after = experiment.guard.summary[r.key]
    return typeof before === 'number' && typeof after === 'number' ? [{ ...r, before, after }] : []
  })
  return (
    <div className="overflow-x-auto rounded-lg border border-rule bg-sheet">
      <table className="w-full min-w-md border-collapse text-[0.8125rem]">
        <caption className="sr-only">
          Quality metrics for the same snapshot and readers, without and with the count guard
        </caption>
        <thead>
          <tr className="border-b border-rule bg-paper-secondary text-left text-[0.75rem] text-ink-40">
            <th scope="col" className="px-4 py-2 font-medium">Metric</th>
            <th scope="col" className="px-4 py-2 text-right font-medium">Without</th>
            <th scope="col" className="px-4 py-2 text-right font-medium">With the guard</th>
            <th scope="col" className="px-4 py-2 text-right font-medium">Change</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const delta = (r.after - r.before) * 100
            const same = Math.abs(delta) <= 0.05
            const worse = r.lowerIsBetter ? delta > 0.05 : delta < -0.05
            return (
              <tr key={r.key} className="border-b border-rule last:border-b-0">
                <th scope="row" className="px-4 py-2.5 text-left font-normal text-ink-60">
                  {r.label}
                </th>
                <td className="data px-4 py-2.5 text-right text-ink">{(r.before * 100).toFixed(1)}%</td>
                <td className="data px-4 py-2.5 text-right text-ink">{(r.after * 100).toFixed(1)}%</td>
                <td className={`data px-4 py-2.5 text-right ${same ? 'text-ink-40' : worse ? 'text-signal' : 'text-ink-60'}`}>
                  {same ? 'unchanged' : `${delta > 0 ? '+' : '−'}${Math.abs(delta).toFixed(1)} pts`}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Offset({
  persona,
  story,
  title,
  reason,
  stage,
  needle,
}: {
  persona: string
  story: string
  title: string
  reason: string
  stage: string
  needle?: boolean
}) {
  return (
    <li className="flex flex-col gap-3 bg-sheet p-5">
      <p className="headline m-0 text-base" data-verbatim>
        {title}
      </p>
      <p className="m-0 rounded-md bg-signal-wash px-3 py-2 text-[0.8125rem] text-signal" data-verbatim>
        &ldquo;{reason}&rdquo;
      </p>
      <p className="m-0 mt-auto text-[0.75rem] text-ink-40">
        Fixture {personaName(persona)}, dropped at <span className="data">{stage}</span>
        {needle === true ? ', a planted needle' : ''}
      </p>
      <Link
        href={explorerHref({ run: RUN }, { persona, view: 'stories', story, outcome: 'all' })}
        className="go self-start !text-[0.8125rem]"
      >
        Open this story&rsquo;s recorded trace
      </Link>
    </li>
  )
}
