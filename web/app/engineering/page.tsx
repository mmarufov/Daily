import type { Metadata } from 'next'
import Link from 'next/link'
import { AnimatedDetails } from '@/components/AnimatedDetails'
import { Band } from '@/components/Band'
import { Misalignment } from '@/components/Misalignment'
import { GuardExperiment } from '@/components/GuardExperiment'
import { loadGuardExperiment } from '@/lib/guard-experiment'
import { personaName } from '@/lib/personas'
import { explorerHref } from '@/lib/url-state'
import '../findings.css'

export const metadata: Metadata = {
  title: 'Case study · Daily Lab',
  description: 'The September 21 count-guard experiment: recorded recall fell and unwanted results rose.',
}
const RUN = 'prod-llm__2026-08-31__47edb50'

export default async function EngineeringPage() {
  const experiment = await loadGuardExperiment()
  return <div className="frame support-page support-case-study">
    <header className="support-intro">
      <p className="eyebrow">Case study</p>
      <h1>A safer guard. A worse score.</h1>
      <p className="lede measure m-0 text-ink-60">A count guard refused mismatched output. Recorded recall fell and unwanted results rose.</p>
    </header>
    <section className="support-section" id="symptom">
      <Band index="01" title="Shifted verdicts" note="August 31 scorecard traces" />
      <ul className="case-primary-example m-0 list-none border border-rule p-0">
        <Offset persona="ray" story="a00407" title="Giants' 53-man roster to include Odell Beckham" reason="The article discusses a music EP, which is irrelevant to the user's interests." stage="blended" />
      </ul>
      <AnimatedDetails className="support-disclosure">
        <summary>More recorded examples</summary>
        <ul className="case-more-examples m-0 grid list-none gap-px border border-rule bg-rule p-0 md:grid-cols-2">
          <Offset persona="dilshod" story="n-dil-02" title="Mirziyoyev signs decree abolishing exit visa-style registration" reason="The article discusses NFL team rosters, which is not relevant to the user's interests." stage="blended" needle />
          <Offset persona="farrukh" story="a00037" title="World mostly shrugs off Bessent's 'D-Day' Iran sanctions threat" reason="The article discusses China's manufacturing activity…" stage="rank" />
        </ul>
      </AnimatedDetails>
    </section>
    <section className="support-section" id="cause">
      <Band index="02" title="Article IDs missing" note="Order was the only link" />
      <div className="support-evidence-layout">
        <div className="flex flex-col gap-5">
          <p className="prose m-0">The scorer requests ordered verdicts without article IDs. The parser continues assigning them after a count mismatch.</p>
          <p className="prose m-0">One recorded Lab case has 40 inputs and 254 verdicts.</p>
          <a className="text-link text-sm" href="https://github.com/mmarufov/Daily/blob/b95a9a63562a6c7b7c36550f1ca7f90ce5e4ceaa/backend/app/services/openai_service.py#L647">Inspect the audited parser revision ↗</a>
        </div><Misalignment />
      </div>
    </section>
    <section className="support-section" id="cost">
      <Band index="03" title="Count-guard results" note="September 21 recorded experiment" />
      <p className="prose measure m-0">The guard discards mismatched batches and retries. Reordered verdicts can still pass when the count matches.</p>
      {experiment ? <GuardExperiment experiment={experiment} showInvestigationLink={false} showHistoryNote /> : <p role="status">The historical experiment is unavailable.</p>}
    </section>
    <section className="support-section" id="next">
      <Band index="04" title="Parser tests" note="Independent grading" />
      <p className="prose measure m-0">Run a parser in Sandbox and inspect each failed case. Both criteria generations and their verdicts remain available. A changed scoring request needs new model recordings.</p>
      <Link className="button-primary self-start" href="/lab#run">Run a parser <span aria-hidden="true">↗</span></Link>
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
    <li className="flex flex-col gap-3 bg-paper p-4">
      <p className="headline m-0 text-base" data-verbatim>{title}</p>
      <p className="m-0 border-l border-signal pl-3 text-sm text-signal" data-verbatim>&ldquo;{reason}&rdquo;</p>
      <p className="m-0 mt-auto text-xs text-ink-40">
        fixture {personaName(persona)} · dropped at {stage}
        {needle === true ? ' · planted needle' : ''}
      </p>
      <Link
        href={explorerHref({ run: RUN }, { persona, view: 'stories', story, outcome: 'all' })}
        className="text-link self-start"
      >
        Inspect story trace
      </Link>
    </li>
  )
}
