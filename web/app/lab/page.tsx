import { AnimatedDetails } from '@/components/AnimatedDetails'
import type { Metadata } from 'next'
import Link from 'next/link'
import { Band } from '@/components/Band'
import { Reveal } from '@/components/Reveal'
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
    <div className="frame lab-page">
      <section className="lab-intro">
        <p className="eyebrow">Daily Lab</p>
        <h1>Test a scoring parser.</h1>
        <div className="lab-intro-copy">
          <p>Test the parsers that interpret Daily's scoring responses. Run the default parser against {catalog.length} cases in Vercel Sandbox, inspect the failure, then edit it.</p>
          <div className="lab-intro-links"><a className="text-link" href="#recorded">Recorded investigations <span aria-hidden="true">↓</span></a><Link className="text-link" href="/engineering">The original defect <span aria-hidden="true">↗</span></Link></div>
        </div>
      </section>
      <section id="run" className="scroll-mt-6" aria-label="Run a parser">
        <LabRunner presets={presets} catalog={catalog} limits={limitsLine} maxBytes={MAX_SOURCE_BYTES} />
      </section>
      <section id="recorded" className="lab-support-section">
        <Band index="01" title="Recorded investigations" note="Published records" />
        {manifest === null ? <p role="status">The published run inventory is unavailable.</p> : (
          <ul className="lab-walkthroughs">{shown.map((w) => {
            const entry = manifest.entries.find((e) => e.file === w.file)
            return <li key={w.slug}><Link href={`/lab/${w.slug}`}>
              {entry && <VerdictBadge verdict={entry.verdict} small />}
              <span className="lab-walkthrough-title">{w.title}</span>
              <span className="lab-walkthrough-copy">{w.blurb}</span>
              <span className="lab-walkthrough-kind">{entry?.kind === 'seeded-control' ? 'Seeded control' : entry?.candidate_id}</span>
            </Link></li>
          })}</ul>
        )}
      </section>
      <section className="lab-support-section">
        <Band index="02" title="Grading criteria" note="Contract correctness, independently graded" />
        <div className="lab-criteria-summary">
          <div>
            <p className="prose m-0 mb-5">{EXPERIMENT.question}</p>
            <Reveal label="What it measures" items={EXPERIMENT.measures} verbatim />
            <Reveal label="What it does not measure" items={EXPERIMENT.does_not_measure} verbatim />
            <Reveal label="Versioned and hashed criteria" items={[
              'Both criteria generations retain their verdicts; the second closes a gap found in earlier runs.',
              'Each verdict carries a criteria hash. New thresholds preserve earlier results.',
              'Acceptance qualifies the parser for human review under those criteria.',
            ]} />
          </div>
          <dl className="lab-readouts">
            <Readout term="Cases" value={catalog.length} note={`${catalog.filter(c => c.origin === 'recorded-replay').length} recorded, ${catalog.filter(c => c.origin === 'fault-injection').length} fault-injected`} />
            <Readout term="Published records" value={manifest?.entries.length ?? 'Unavailable'} note="Including records with no execution" />
            <Readout term="Sandbox executions" value={manifest?.entries.filter(e => e.runner === 'vercel-sandbox').length ?? 'Unavailable'} note="Within the published inventory" />
            <Readout term="Grading" value="Independent" note="Computed from prediction records" />
          </dl>
        </div>
        <AnimatedDetails className="lab-disclosure"><summary>Recorded response</summary>
          {offending ? <OffendingCase data={offending} /> : <p>The recorded batch is unavailable.</p>}
        </AnimatedDetails>
        <AnimatedDetails className="lab-disclosure"><summary>Published runs <span>{manifest?.entries.length ?? 0} records</span></summary>
          <ul className="lab-inventory">{manifest?.entries.map(entry => <li key={entry.file}>
            <Link href={`/lab/${entry.file.replace(/\.json$/, '')}`}>
              <span className="lab-inventory-id">{entry.candidate_id}</span>
              <span className="lab-inventory-note">{entry.runner === 'none' ? 'No candidate execution' : entry.runner}
                {new Set(Object.values(entry.verdict_by_spec)).size > 1 && <span>Verdict moved between criteria generations</span>}
              </span>
              <span className="lab-inventory-verdict"><VerdictBadge verdict={entry.verdict} small /></span>
            </Link>
          </li>)}</ul>
        </AnimatedDetails>
        <AnimatedDetails className="lab-disclosure"><summary>Test scope</summary>
          <div className="grid gap-6 pb-6 text-sm text-ink-60 md:grid-cols-2">
            <p className="m-0">Candidates can target these public cases. Results apply to these fixtures.</p>
            <p className="m-0">Runs execute against recorded or injected responses. Grading makes no model calls; agent-authored runs report candidate-writing calls separately.</p>
            <p className="m-0">The runner enforces admission and execution limits, denies networking and grades independently. Events come from the service; case verdicts arrive when grading finishes.</p>
            <p className="m-0">Evaluating news quality with an ID-based scoring request needs new model recordings.</p>
          </div>
        </AnimatedDetails>
      </section>
    </div>
  )
}
function Readout({ term, value, note }: { term: string; value: string | number; note: string }) {
  return <div><dt className="label text-ink-40">{term}</dt><dd className="m-0 mt-2 text-xl tracking-tight">{value}<span className="mt-1 block text-xs text-ink-60">{note}</span></dd></div>
}
