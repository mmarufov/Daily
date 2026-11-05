import { AnimatedDetails } from '@/components/AnimatedDetails'
import type { Metadata } from 'next'
import Link from 'next/link'
import { OffendingCase } from '@/components/LabOffendingCase'
import { LabRunner } from '@/components/LabRunner'
import { VerdictBadge } from '@/components/LabVerdict'
import { EXPERIMENT } from '@/lib/lab/spec'
import { loadLabIndex, loadOffendingCase, walkthroughs } from '@/lib/lab/data'
import { PUBLIC_RUN_LIMITS } from '@/lib/lab/public-limits'
import { MAX_SOURCE_BYTES } from '@/lib/lab/public-run'
import { loadCaseCatalog, loadRunnerPresets } from '@/lib/lab/runner-presets'
import '../lab-workspace.css'

export const metadata: Metadata = {
  title: 'Run a parser · Daily Lab',
  description: 'Run a Python parser in Vercel Sandbox. Inspect recorded and injected cases with independent grading.',
}

export default async function LabPage() {
  const [{ manifest }, offending, presets, catalog] = await Promise.all([
    loadLabIndex(), loadOffendingCase(), loadRunnerPresets(), loadCaseCatalog(),
  ])
  const limits = PUBLIC_RUN_LIMITS
  const limitsLine = `Limits: ${limits.per_address.runs} runs/hour per address, ${limits.concurrent_runs} at once, and ${limits.runs_per_day} runs or ${limits.cpu_ms_per_day / 60_000} minutes of microVM CPU/day across all visitors. Live runs have a separate inventory.`
  const shown = manifest === null ? [] : walkthroughs(manifest)
  return (
    <div className="frame lab-page support-page support-lab">
      <section className="lab-intro support-intro">
        <p className="eyebrow">Daily Lab</p>
        <h1>Test a scoring parser.</h1>
        <div className="lab-intro-copy">
          <p>Run a parser for Daily's scoring responses against {catalog.length} cases in Vercel Sandbox. Inspect the failure, then edit it.</p>
          <Link className="text-link" href="/engineering">Case study <span aria-hidden="true">↗</span></Link>
        </div>
      </section>
      <section id="run" className="scroll-mt-6" aria-label="Run a parser">
        <LabRunner presets={presets} catalog={catalog} limits={limitsLine} maxBytes={MAX_SOURCE_BYTES} />
      </section>
      <section className="support-disclosures" aria-label="Supporting records">
        {manifest === null ? <p role="status">The published run inventory is unavailable.</p> : null}
        {offending === null ? <p role="status">The recorded response is unavailable.</p> : null}
        <AnimatedDetails className="lab-disclosure">
          <summary id="recorded" className="scroll-mt-6">Recorded examples</summary>
          <div className="support-disclosure-body">
            <ul className="lab-walkthroughs">{shown.map((w) => {
              const entry = manifest?.entries.find((e) => e.file === w.file)
              return <li key={w.slug}><Link href={`/lab/${w.slug}`}>
                {entry && <VerdictBadge verdict={entry.verdict} small />}
                <span className="lab-walkthrough-title">{w.title}</span>
                <span className="lab-walkthrough-copy">{w.blurb}</span>
                <span className="lab-walkthrough-kind">{entry?.kind === 'seeded-control' ? 'Seeded control' : entry?.candidate_id}</span>
              </Link></li>
            })}</ul>
            {offending ? <AnimatedDetails className="lab-disclosure">
              <summary>Recorded response</summary>
              <OffendingCase data={offending} />
            </AnimatedDetails> : null}
          </div>
        </AnimatedDetails>
        <AnimatedDetails className="lab-disclosure">
          <summary>Grading criteria</summary>
          <div className="support-disclosure-body lab-criteria-content">
            <p className="m-0" data-verbatim>{EXPERIMENT.question}</p>
            <div className="grid gap-6 md:grid-cols-2">
              <div><h3 className="label text-ink-60">What it measures</h3>
                <ul className="m-0 space-y-2 pl-5" data-verbatim>{EXPERIMENT.measures.map(item => <li key={item}>{item}</li>)}</ul>
              </div>
              <div><h3 className="label text-ink-60">What it does not measure</h3>
                <ul className="m-0 space-y-2 pl-5" data-verbatim>{EXPERIMENT.does_not_measure.map(item => <li key={item}>{item}</li>)}</ul>
              </div>
            </div>
            <p className="m-0">Criteria are versioned and hashed. Both generations retain their verdicts; the second closes a gap found in earlier runs. Acceptance qualifies the parser for human review under those criteria.</p>
            <p className="m-0 text-ink-60">Results apply to these public fixtures. Candidates can target the cases. Grading uses recorded or injected responses and makes no model calls; agent-authored runs report candidate-writing calls separately.</p>
            <p className="m-0 text-ink-60">Evaluating news quality with an ID-based scoring request needs new model recordings.</p>
          </div>
        </AnimatedDetails>
        <AnimatedDetails className="lab-disclosure">
          <summary>Published runs <span>{manifest === null ? 'Unavailable' : `${manifest.entries.length} records`}</span></summary>
          <div className="support-disclosure-body">
            <dl className="lab-readouts">
              <Readout term="Published records" value={manifest?.entries.length ?? 'Unavailable'} note="Including records with no execution" />
              <Readout term="Sandbox executions" value={manifest?.entries.filter(e => e.runner === 'vercel-sandbox').length ?? 'Unavailable'} note="Within the published inventory" />
            </dl>
            <ul className="lab-inventory">{manifest?.entries.map(entry => <li key={entry.file}>
              <Link href={`/lab/${entry.file.replace(/\.json$/, '')}`}>
                <span className="lab-inventory-id">{entry.candidate_id}</span>
                <span className="lab-inventory-note">{entry.runner === 'none' ? 'No candidate execution' : entry.runner}
                  {new Set(Object.values(entry.verdict_by_spec)).size > 1 && <span>Verdict moved between criteria generations</span>}
                </span>
                <span className="lab-inventory-verdict"><VerdictBadge verdict={entry.verdict} small /></span>
              </Link>
            </li>)}</ul>
          </div>
        </AnimatedDetails>
      </section>
    </div>
  )
}
function Readout({ term, value, note }: { term: string; value: string | number; note: string }) {
  return <div><dt className="label text-ink-40">{term}</dt><dd className="m-0 mt-2 text-xl tracking-tight">{value}<span className="mt-1 block text-xs text-ink-60">{note}</span></dd></div>
}
