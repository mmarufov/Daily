import Link from 'next/link'

import { HeroSieve } from '@/components/HeroSieve'
import { RetrievalLoss } from '@/components/RetrievalLoss'
import { GuardExperiment } from '@/components/GuardExperiment'
import { HOME_RUN_ID, loadHomeEvidence } from '@/lib/home-evidence'
import './lab-home.css'
import './findings.css'

export default async function HomePage() {
  const evidence = await loadHomeEvidence()
  const run = evidence.recordedRun
  const correct = run?.counts.correct ?? 0
  const excluded = run?.counts['not-applicable'] ?? 0
  const applicable = (run?.outcomes.length ?? 0) - excluded
  const lookback = evidence.losses?.segments.find((s) => s.key === 'lookback')

  return (
    <div className="lab-landing">
      <section className="frame lab-hero">
        <div className="lab-hero-grid">
          <div className="hero-copy">
            <p className="eyebrow">An evaluation instrument</p>
            <h1 className="lab-headline">Does the fix<br /> actually work?</h1>
            <p className="hero-description">Run untrusted Python parsers in Vercel Sandbox against recorded and injected failures. Inspect the verdict.</p>
            <div className="hero-actions">
              <Link href="/lab#run" className="button-primary">Run a parser <span aria-hidden="true">↗</span></Link>
              <Link href="/evidence" className="text-link">Explore the evidence <span aria-hidden="true">→</span></Link>
            </div>
            <p className="hero-footnote">Independent grading. Versioned, hashed criteria.</p>
          </div>
          <HeroSieve fixtures={evidence.fixtures} runId={HOME_RUN_ID} snapshot={evidence.artifact?.provenance.snapshot.name ?? 'unavailable'} />
        </div>
        <div className="hero-context">
          <p>The subject: a personalized news pipeline.<br />The instrument: everything it failed to catch.</p>
          <a href="#retrieval" className="text-link">Follow the evidence <span aria-hidden="true">↓</span></a>
        </div>
      </section>

      <section className="finding-section" id="retrieval">
        <div className="frame finding-layout">
          <div className="finding-copy">
            <p className="eyebrow">01 / Before the model</p>
            <h2>Ranking never got a chance.</h2>
            <p>{lookback && evidence.losses ? <>{lookback.count} of {evidence.losses.total} missed must-see pairs were lost at the lookback window. Better ranking cannot recover a story retrieval never supplied.</> : 'Trace where the recorded pipeline lost stories before the scorer could see them.'}</p>
            <Link href="/evidence?run=prod-llm__2026-09-02__47edb50&view=stories&outcome=lost-before-scorer" className="text-link">Inspect the losses <span aria-hidden="true">→</span></Link>
          </div>
          <RetrievalLoss data={evidence.losses} />
        </div>
      </section>

      <section className="finding-section" id="experiment">
        <div className="frame finding-layout">
          <div className="finding-copy">
            <p className="eyebrow">02 / The cost of correctness</p>
            <h2>A safer guard.<br />A worse score.</h2>
            <p>A recorded response returned more verdicts than articles, without IDs to join them. An experimental guard refused to guess.</p>
            {evidence.offendingCase ? <>
              <div className="defect-strip" aria-label={`${evidence.offendingCase.articles_sent} articles sent, ${evidence.offendingCase.verdicts_returned} verdicts returned`}>
                <div className="defect-quantity"><strong>{evidence.offendingCase.articles_sent}</strong><span>articles sent</span></div>
                <span aria-hidden="true">→</span>
                <div className="defect-quantity"><strong>{evidence.offendingCase.verdicts_returned}</strong><span>verdicts returned</span></div>
              </div>
              <p className="defect-caption">One recorded batch. No article IDs in either direction.</p>
            </> : null}
          </div>
          <GuardExperiment experiment={evidence.guardExperiment} />
        </div>
      </section>

      <section className="frame lab-invitation">
        <div className="invitation-inner">
          <div className="invitation-copy">
            <p className="eyebrow">03 / Your turn</p>
            <h2>Put your parser through it.</h2>
            <p>The count guard looks like a fix. Four applicable cases still catch it. Start there, or submit your own.</p>
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
              <p className="recorded-result-note">Recorded Lab result · not a live execution</p>
              <div className="recorded-case-field" role="img" aria-label={`${correct} correct, ${applicable - correct} failed, ${excluded} not applicable, out of ${run.outcomes.length} cases`}>
                {run.outcomes.map((outcome) => <span key={outcome.case_id} data-status={outcome.status} aria-hidden="true" />)}
              </div>
              <p className="recorded-result-summary">{correct}/{applicable} applicable cases correct. {excluded} not applicable.</p>
              <Link href="/lab/count-guard-v1-clean" className="text-link">Inspect this verdict <span aria-hidden="true">→</span></Link>
            </div>
          ) : <div className="recorded-result"><p>The recorded result is unavailable.</p><Link href="/lab" className="text-link">Open the Lab</Link></div>}
        </div>
      </section>
    </div>
  )
}
