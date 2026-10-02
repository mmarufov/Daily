import type { Metadata } from 'next'
import Link from 'next/link'
import { Band } from '@/components/Band'
import { Misalignment } from '@/components/Misalignment'
import { GuardExperiment } from '@/components/GuardExperiment'
import { loadGuardExperiment } from '@/lib/guard-experiment'
import { personaName } from '@/lib/personas'
import { explorerHref } from '@/lib/url-state'
import '../findings.css'
import '../supporting-pages.css'

export const metadata: Metadata = {
  title: 'Findings · Daily Lab',
  description: 'The September 21 recorded experiment: refusing ambiguous scorer output lowered recall and raised unwanted results. Inspect the defect, evidence and limitations.',
}
const RUN = 'prod-llm__2026-08-31__47edb50'

export default async function EngineeringPage() {
  const experiment = await loadGuardExperiment()
  return <div className="findings-page frame flex flex-col">
    <section className="support-intro flex flex-col gap-5">
      <p className="eyebrow">Finding / September 21, 2026</p>
      <h1 className="display m-0 max-w-4xl text-[clamp(2.75rem,6vw,5rem)]">A safer guard.<br />A worse score.</h1>
      <p className="lede measure m-0 text-ink-60">A count guard refused ambiguous model output. In the recorded experiment, recall fell and unwanted results rose.</p>
      <p className="m-0 max-w-2xl text-sm text-ink-60">This is a historical working-tree experiment, not a shipped guard or current CI status. The original baseline was retained.</p>
    </section>
    <section className="support-section flex flex-col gap-6" id="symptom">
      <Band index="01" title="A reason about the wrong story" note="Actual traces from the August 31 scorecard" />
      <ul className="m-0 grid list-none gap-px border border-rule bg-rule p-0 lg:grid-cols-3">
        <Offset persona="ray" story="a00407" title="Giants' 53-man roster to include Odell Beckham" reason="The article discusses a music EP, which is irrelevant to the user's interests." stage="blended" />
        <Offset persona="dilshod" story="n-dil-02" title="Mirziyoyev signs decree abolishing exit visa-style registration" reason="The article discusses NFL team rosters, which is not relevant to the user's interests." stage="blended" needle />
        <Offset persona="farrukh" story="a00037" title="World mostly shrugs off Bessent's 'D-Day' Iran sanctions threat" reason="The article discusses China's manufacturing activity…" stage="rank" />
      </ul>
      <p className="m-0 measure text-sm text-ink-60">These examples show shifted associations. They do not establish that every verdict in every batch was wrong.</p>
    </section>
    <section className="support-section flex flex-col gap-6" id="cause">
      <Band index="02" title="The missing identity contract" note="Order was the only link" />
      <div className="grid gap-10 lg:grid-cols-2">
        <div className="flex flex-col gap-5">
          <p className="prose m-0">The scorer asks for one verdict per article in order, without an article identifier. Its positional parser logs a count mismatch and then continues assigning output.</p>
          <p className="prose m-0">One recorded Lab case has 40 inputs and 254 verdicts. Once a response shifts, an apparently plausible reason can attach to an unrelated article.</p>
          <a className="text-link text-sm" href="https://github.com/mmarufov/Daily/blob/b95a9a63562a6c7b7c36550f1ca7f90ce5e4ceaa/backend/app/services/openai_service.py#L647">Inspect the audited parser revision ↗</a>
        </div><Misalignment />
      </div>
    </section>
    <section className="support-section flex flex-col gap-6" id="cost">
      <Band index="03" title="Refusing ambiguity has a cost" note="September 21 recorded experiment" />
      {experiment ? <GuardExperiment experiment={experiment} /> : <p role="status">The historical experiment is unavailable.</p>}
      <div className="findings-interpretation grid gap-8 lg:grid-cols-2">
        <div className="flex flex-col gap-5">
          <p className="prose m-0">The experimental guard discards a mismatched batch and retries. A response with the right count but the wrong order can still pass. Counting is a partial contract.</p>
          <p className="prose m-0">Discarded batches lose their relevance signal. The recorded metrics show that refusing ambiguous output did not, on its own, improve the delivered feed.</p>
        </div>
        <div className="flex flex-col gap-5">
          <p className="m-0 text-sm text-ink-60">The historical note reports the same snapshot, ten fixtures and k=12. Both scorecards report zero cache misses, but their recorded cache-key sets differ. The comparison is historical evidence, not a controlled causal estimate with fully preserved execution inputs.</p>
          <p className="m-0 text-sm text-ink-60">Six regression failures were recorded and the baseline was not re-recorded. The guard scorecard identifies the base checkout, not a commit containing the experimental implementation. Exact guard bytes were not preserved with the record.</p>
          <a className="text-link text-sm" href="/experiments/batch-alignment.json">Versioned experiment, source hashes and limitations ↗</a>
        </div>
      </div>
    </section>
    <section className="support-section flex flex-col gap-6" id="next">
      <Band index="04" title="Correct association comes first" note="Quality remains a separate question" />
      <div className="grid gap-10 lg:grid-cols-2">
        <p className="prose m-0">Daily Lab makes the identity contract inspectable. Submit a parser, run the public cases in Sandbox, and examine independently computed failures. Both generations of the criteria and their verdicts remain available.</p>
        <div className="flex flex-col gap-5"><p className="prose m-0">Passing those checks does not prove better news relevance. The quality scorecards use provisional model and agent labels; a changed scoring request also needs new recordings.</p><Link className="button-primary self-start" href="/lab#run">Run a parser <span aria-hidden="true">↗</span></Link></div>
      </div>
    </section>
  </div>
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
    <li className="finding-trace flex flex-col gap-3 bg-paper p-5">
      <p className="headline m-0 text-base">{title}</p>
      <blockquote className="m-0 border-l-2 border-signal pl-3 text-sm text-signal" data-verbatim>&ldquo;{reason}&rdquo;</blockquote>
      <p className="m-0 mt-auto text-xs text-ink-40">
        fixture {personaName(persona)} · dropped at {stage}
        {needle === true ? ' · planted needle' : ''}
      </p>
      <Link
        href={explorerHref({ run: RUN }, { persona, view: 'stories', story, outcome: 'all' })}
        className="link label self-start"
      >
        open this story&rsquo;s recorded trace
      </Link>
    </li>
  )
}
