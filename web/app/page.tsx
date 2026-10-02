import Link from 'next/link'

import { EditionPreview } from '@/components/EditionPreview'
import { GuardSummary } from '@/components/GuardSummary'
import { RunStory } from '@/components/RunStory'
import { HOME_RUN_ID, loadHomeEvidence } from '@/lib/home-evidence'
import { explorerHref } from '@/lib/url-state'
import './lab-home.css'
import '@/components/guard-summary.css'

export default async function HomePage() {
  const evidence = await loadHomeEvidence()

  return (
    <div className="lab-landing">
      <section className="frame lab-hero" aria-labelledby="daily-introduction">
        <div className="lab-hero-grid">
          <div className="hero-copy">
            <h1 className="lab-headline" id="daily-introduction">Daily makes<br /> news personal.</h1>
            <p className="hero-description">Daily builds news editions around a reader&apos;s interests. Its parser couldn&apos;t reliably match AI scores to articles. Daily Lab tests the fixes.</p>
            <div className="hero-actions">
              <Link href="/lab" className="button-primary">Explore the Lab <span aria-hidden="true">↗</span></Link>
              <Link href="/reader?profile=ray" prefetch={false} className="text-link">Read an edition <span aria-hidden="true">→</span></Link>
            </div>
          </div>
          <EditionPreview edition={evidence.editionPreview} />
        </div>
      </section>

      <RunStory data={evidence.runStory} />
      <GuardSummary experiment={evidence.guardExperiment} />

      <div className="frame home-story-footer">
        <nav className="home-evidence-links" aria-label="More recorded evidence">
          <Link id="pipeline" href={explorerHref({ run: HOME_RUN_ID, view: 'funnel' }, { persona: 'ray' })} className="text-link">Inside Daily's pipeline <span aria-hidden="true">↗</span></Link>
          <Link id="retrieval" href={explorerHref({ run: HOME_RUN_ID, view: 'stories' }, { outcome: 'lost-before-scorer' })} className="text-link">Inspect retrieval losses <span aria-hidden="true">↗</span></Link>
        </nav>
        <div className="home-story-closing">
          <p>Test your parser in the Lab.</p>
          <Link href="/lab#run" className="button-primary">Run a parser <span aria-hidden="true">↗</span></Link>
        </div>
      </div>
    </div>
  )
}
