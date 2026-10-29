import Link from 'next/link'

import { SharkBackground } from '@/components/SharkBackground'
import { GuardSummary } from '@/components/GuardSummary'
import { RunStory } from '@/components/RunStory'
import { HOME_RUN_ID, loadHomeEvidence } from '@/lib/home-evidence'
import { explorerHref } from '@/lib/url-state'
import './lab-home.css'
import '@/components/guard-summary.css'

const heroDescription = "Daily builds news editions around a reader's interests. Its parser couldn't reliably match AI scores to articles. Daily Lab tests the fixes."

export default async function HomePage() {
  const evidence = await loadHomeEvidence()

  return (
    <div className="lab-landing">
      <div className="hero-scene">
        <SharkBackground />
        <section className="frame lab-hero" aria-labelledby="daily-introduction">
          <div className="lab-hero-grid">
            <div className="hero-copy">
              <h1 className="lab-headline" id="daily-introduction">Daily makes<br /> news personal.</h1>
              <p className="hero-description" data-hero-overlap>
                {heroDescription}
                <span className="hero-overlap-ink" aria-hidden="true" data-text={heroDescription} />
              </p>
              <div className="hero-actions">
                <Link href="/lab" className="button-primary">Explore the Lab <span aria-hidden="true">↗</span></Link>
                <Link href="/reader?profile=ray" prefetch={false} className="text-link hero-edition-link" data-hero-overlap>
                  Read an edition <span aria-hidden="true">→</span>
                  <span className="hero-overlap-ink" aria-hidden="true" data-text="Read an edition" data-icon="→" />
                </Link>
              </div>
            </div>
          </div>
        </section>
      </div>

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
