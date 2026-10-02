import Link from 'next/link'

import { CaseStatusMark } from '@/components/CaseStatusMark'
import { EditionPreview } from '@/components/EditionPreview'
import { HeroSieve } from '@/components/HeroSieve'
import { RetrievalLoss } from '@/components/RetrievalLoss'
import { RecordedRunTimeline } from '@/components/RecordedRunTimeline'
import { GuardExperiment } from '@/components/GuardExperiment'
import { HOME_RUN_ID, loadHomeEvidence } from '@/lib/home-evidence'
import './lab-home.css'
import './findings.css'
import '@/components/recorded-run-timeline.css'

export default async function HomePage() {
  const evidence = await loadHomeEvidence()
  const run = evidence.recordedRun
  const correct = run?.counts.correct ?? 0
  const excluded = run?.counts['not-applicable'] ?? 0
  const applicable = (run?.outcomes.length ?? 0) - excluded
  const lookback = evidence.losses?.segments.find((s) => s.key === 'lookback')

  return (
    <div className="lab-landing">
      <section className="frame lab-hero" aria-labelledby="daily-introduction">
        <div className="lab-hero-grid">
          <div className="hero-copy">
            <h1 className="lab-headline" id="daily-introduction">Daily makes<br /> news personal.</h1>
            <p className="hero-description">Daily builds a news edition around a reader&apos;s interests. When its parser couldn&apos;t reliably match AI scores to articles, Daily Lab became the place to test proposed fixes.</p>
            <div className="hero-actions">
              <Link href="/lab" className="button-primary">Explore the Lab <span aria-hidden="true">↗</span></Link>
              <Link href="/reader?profile=ray" prefetch={false} className="text-link">Read an edition <span aria-hidden="true">→</span></Link>
            </div>
          </div>
          <EditionPreview edition={evidence.editionPreview} />
        </div>
      </section>

      <section className="frame lab-invitation" id="daily-lab" aria-labelledby="lab-question">
        <div className="invitation-inner">
          <div className="invitation-copy">
            <p className="eyebrow">01 / Daily Lab</p>
            <h2 id="lab-question">Does the fix<br /> actually work?</h2>
            <p>{evidence.offendingCase ? <>Daily sent {evidence.offendingCase.articles_sent} articles for scoring and received {evidence.offendingCase.verdicts_returned} verdicts without article IDs, leaving the matches unverifiable. </> : <>Daily&apos;s parser must connect each model score to the right article. </>}The Lab runs proposed parsers in Vercel Sandbox and grades their results independently.</p>
            <Link href="/lab#run" className="button-primary">Run the default parser <span aria-hidden="true">↗</span></Link>
            <div className="invitation-facts">
              <span><b>{evidence.lab.caseCount ?? 'Unavailable'}</b>cases</span>
              <span><b>{evidence.lab.faultCount ?? 'Unavailable'}</b>fault-injected</span>
              <span><b>Independent</b>grading</span>
            </div>
          </div>
          {run ? (
            <div className="recorded-result">
              <div className="recorded-result-top"><span>{run.candidate.candidate_id}</span><span className="recorded-status">{run.verdict === 'rejected' ? 'Rejected' : run.verdict}</span></div>
              <p className="recorded-result-note">Published Lab result · criteria generation 1</p>
              <div className="recorded-case-field" data-testid="recorded-case-field" role="img" aria-label={`${correct} correct, ${applicable - correct} failed, ${excluded} not applicable, out of ${run.outcomes.length} cases`}>
                {run.outcomes.map((outcome) => {
                  const tone = outcome.status === 'correct' ? 'correct' : outcome.status === 'not-applicable' ? 'unscored' : 'wrong'
                  return <span key={outcome.case_id} className="case-status-cell" data-tone={tone} data-status={outcome.status} aria-hidden="true"><CaseStatusMark tone={tone} /></span>
                })}
              </div>
              <ul className="case-status-legend recorded-case-legend">
                {([['correct', correct, 'correct'], ['wrong', applicable - correct, 'failed'], ['unscored', excluded, 'not applicable']] as const).map(([tone, count, label]) => (
                  <li key={tone}><span className="case-status-cell" data-tone={tone}><CaseStatusMark tone={tone} /></span><span>{count} {label}</span></li>
                ))}
              </ul>
              <p className="recorded-result-summary">The count guard looks like a fix. {applicable - correct} applicable cases still catch it.</p>
              <Link href={evidence.recordedRunHref} className="text-link">Inspect this verdict <span aria-hidden="true">→</span></Link>
              <RecordedRunTimeline />
            </div>
          ) : <div className="recorded-result"><p>The published result is unavailable.</p><Link href="/lab" className="text-link">Open the Lab</Link><RecordedRunTimeline /></div>}
        </div>
      </section>

      <section className="finding-section" id="experiment">
        <div className="frame finding-layout">
          <div className="finding-copy">
            <p className="eyebrow">02 / The cost of correctness</p>
            <h2>A safer guard.<br />A worse score.</h2>
            <p>An experimental guard refused batches with the wrong number of verdicts, and measured feed quality got worse. The Lab checks parser correctness; this historical experiment measures the effect on news relevance.</p>
          </div>
          <GuardExperiment experiment={evidence.guardExperiment} />
        </div>
      </section>

      <section className="finding-section" id="pipeline">
        <div className="frame finding-layout pipeline-layout">
          <div className="finding-copy">
            <p className="eyebrow">03 / Inside Daily</p>
            <h2>From candidates<br />to an edition.</h2>
            <p>Daily retrieves articles, scores their relevance, and assembles a personalized feed. Follow one recorded pipeline, including its injected test stories, from the candidate pool to delivery.</p>
            <Link href="/evidence" className="text-link">Explore the evidence <span aria-hidden="true">→</span></Link>
          </div>
          <HeroSieve fixtures={evidence.fixtures} runId={HOME_RUN_ID} snapshot={evidence.artifact?.provenance.snapshot.name ?? 'unavailable'} />
        </div>
      </section>

      <section className="finding-section" id="retrieval">
        <div className="frame finding-layout">
          <div className="finding-copy">
            <p className="eyebrow">04 / Before the model</p>
            <h2>Ranking never got a chance.</h2>
            <p>{lookback && evidence.losses ? <>{lookback.count} of {evidence.losses.total} missed must-see pairs were lost at the lookback window. Better ranking cannot recover a story retrieval never supplied.</> : 'Trace where the recorded pipeline lost stories before the scorer could see them.'}</p>
            <Link href="/evidence?run=prod-llm__2026-09-02__47edb50&view=stories&outcome=lost-before-scorer" className="text-link">Inspect the losses <span aria-hidden="true">→</span></Link>
          </div>
          <RetrievalLoss data={evidence.losses} />
        </div>
        <div className="frame home-closing"><p>Have a fix in mind? Put it through the Lab.</p><Link href="/lab#run" className="button-primary">Run a parser <span aria-hidden="true">↗</span></Link></div>
      </section>
    </div>
  )
}
