import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'

import { Band, PageIndex, type Section } from '@/components/Band'
import { Counterexample, CriteriaTable, Timeline, VerdictBadge } from '@/components/LabVerdict'
import { UNKNOWN } from '@/lib/lab/artifact'
import { loadLabIndex, loadLabRun, walkthroughs } from '@/lib/lab/data'
import { SANDBOX_LIMITS } from '@/lib/lab/runner'

const SECTIONS: readonly Section[] = [
  { index: '01', slug: 'verdict', title: 'Verdict' },
  { index: '02', slug: 'counterexample', title: 'Counterexample' },
  { index: '03', slug: 'patch', title: 'The patch' },
  { index: '04', slug: 'timeline', title: 'Timeline' },
  { index: '05', slug: 'cases', title: 'Cases' },
  { index: '06', slug: 'provenance', title: 'Provenance' },
]

const band = (slug: string, note?: string) => {
  const s = SECTIONS.find((x) => x.slug === slug)
  return { index: s?.index ?? '', title: s?.title ?? '', slug, note }
}

/** Resolve a URL segment: either a walkthrough slug or a run file stem. */
async function resolve(segment: string) {
  const { manifest } = await loadLabIndex()
  if (manifest === null) return null
  const bySlug = walkthroughs(manifest).find((w) => w.slug === segment)
  const file = bySlug?.file ?? `${segment}.json`
  const entry = manifest.entries.find((e) => e.file === file)
  if (entry === undefined) return null
  const run = await loadLabRun(file)
  return run === null ? null : { run, entry, manifest }
}

export async function generateStaticParams() {
  const { manifest } = await loadLabIndex()
  if (manifest === null) return []
  const slugs = walkthroughs(manifest).map((w) => ({ run: w.slug }))
  const files = manifest.entries.map((e) => ({ run: e.file.replace(/\.json$/, '') }))
  return [...slugs, ...files]
}

export async function generateMetadata({
  params,
}: {
  params: Promise<{ run: string }>
}): Promise<Metadata> {
  const { run } = await params
  const resolved = await resolve(run)
  if (resolved === null) return { title: 'Run not found' }
  return {
    title: `${resolved.run.candidate.candidate_id} — ${resolved.run.verdict}`,
    description: resolved.run.verdict_reason,
  }
}

export default async function LabRunPage({ params }: { params: Promise<{ run: string }> }) {
  const { run: segment } = await params
  const resolved = await resolve(segment)
  if (resolved === null) notFound()
  const { run } = resolved

  const scored = run.outcomes.filter((o) => o.applicability === 'scored')
  const wrong = scored.filter((o) => o.status !== 'correct')
  const observed = scored.filter((o) => o.group === 'observed')
  const control = run.candidate.kind === 'seeded-control'

  return (
    <div className="flex flex-col">
      <section className="frame flex flex-col gap-6 py-12 md:py-14">
        <p className="label m-0 text-ink-40">
          <Link href="/lab" className="link">Daily Lab</Link> · recorded replay · run{' '}
          {run.run_id.split('__').slice(-2).join(' · ')}
        </p>
        <h1 className="display m-0 max-w-4xl text-[clamp(2rem,5.5vw,4rem)]">
          {run.candidate.candidate_id}
        </h1>
        <div className="flex flex-wrap items-center gap-3">
          <VerdictBadge verdict={run.verdict} />
          <p className="m-0 max-w-2xl text-sm text-ink-60">{run.verdict_reason}</p>
        </div>
        {control ? (
          <p className="m-0 max-w-3xl border-l-2 border-signal pl-3 text-sm text-ink-60">
            <strong className="text-ink">This is a seeded control.</strong> It carries a deliberate
            defect and exists so the checks can be shown to catch something. {run.candidate.description}
          </p>
        ) : (
          <p className="lede measure m-0 text-ink-60">{run.candidate.description}</p>
        )}
        {/* Only index sections this run actually renders: a counterexample
            exists only where a candidate mis-associated rather than refused,
            and an index entry that jumps nowhere is worse than no entry. */}
        <PageIndex
          sections={SECTIONS.filter(
            (s) => s.slug !== 'counterexample' || run.smallest_counterexample !== null,
          )}
        />
      </section>

      <section className="frame flex flex-col gap-6 pb-16">
        <Band {...band('verdict', `spec ${run.provenance.spec_hash}`)} />
        <CriteriaTable run={run} />
        <p className="m-0 max-w-3xl border-t border-signal pt-3 text-sm text-ink-60">
          {run.verdict_scope}
        </p>
      </section>

      {run.smallest_counterexample !== null ? (
        <section className="frame flex flex-col gap-6 pb-16">
          <Band {...band('counterexample', 'The smallest thing that is wrong')} />
          <Counterexample run={run} />
        </section>
      ) : null}

      <section className="frame flex flex-col gap-6 pb-16">
        <Band {...band('patch', `against ${run.candidate.patch_base.split('/').pop()}`)} />
        {run.candidate.patch === '' ? (
          <p className="m-0 max-w-2xl text-sm text-ink-60">
            This run is the baseline itself, so there is nothing to diff against.
          </p>
        ) : (
          <details className="border border-rule bg-paper-secondary">
            <summary className="disclosure label px-4 py-3 text-ink">
              Unified diff · {run.candidate.patch.split('\n').length} lines · applies with git apply
            </summary>
            <pre className="m-0 max-w-full overflow-x-auto border-t border-rule bg-paper p-4 text-[11px] leading-relaxed">
              {run.candidate.patch.split('\n').map((line, i) => (
                <span
                  key={i}
                  className={
                    line.startsWith('+') && !line.startsWith('+++')
                      ? 'block text-ink'
                      : line.startsWith('-') && !line.startsWith('---')
                        ? 'block text-signal'
                        : 'block text-ink-40'
                  }
                >
                  {line === '' ? ' ' : line}
                </span>
              ))}
            </pre>
          </details>
        )}
        <div className="grid gap-6 md:grid-cols-2">
          <div className="min-w-0">
            <p className="label m-0 text-ink-40">Reproduce this run</p>
            <pre className="m-0 mt-2 max-w-full overflow-x-auto border border-rule bg-paper-secondary p-3 text-[11px] text-ink-60">
{`cd backend
EVAL_OFFLINE=1 venv/bin/python -m lab.orchestrate \\
  --candidate ${run.candidate.candidate_id} --tag clean
cd ../web && npm run export:lab -- --check`}
            </pre>
          </div>
          <div className="min-w-0">
            <p className="label m-0 text-ink-40">Source under test</p>
            <p className="m-0 mt-2 break-all text-xs text-ink-60">
              <span className="text-ink">{run.candidate.source_path}</span>
              <span className="block pt-1">
                sha256 {run.candidate.source_sha256.slice(0, 16)}… · {run.candidate.source_bytes} bytes
              </span>
              <span className="block pt-1">
                transcribed from {run.candidate.transcribed_from}
              </span>
            </p>
          </div>
        </div>
      </section>

      <section className="frame flex flex-col gap-6 pb-16">
        <Band {...band('timeline', `${run.attempts.length} attempt${run.attempts.length === 1 ? '' : 's'}`)} />
        <Timeline run={run} />
        <p className="m-0 max-w-3xl text-xs text-ink-40">
          Durability makes orchestration recoverable; it does not make a sandbox creation or a
          publish happen exactly once. An attempt the orchestrator never saw finish is recorded as{' '}
          <span className="text-unknown">unknown-outcome</span> rather than assumed to have failed.
        </p>
      </section>

      <section className="frame flex flex-col gap-6 pb-16">
        <Band {...band('cases', `${scored.length} scored, ${run.outcomes.length - scored.length} not applicable`)} />
        <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-4">
          <Figure term="Recorded cases" value={String(observed.length)} note="real batches, replayed" />
          <Figure term="Fault-injected" value={String(scored.length - observed.length)} note="labelled synthetic" />
          <Figure term="Correct" value={String(scored.length - wrong.length)} note="of the scored cases" />
          <Figure term="Wrong" value={String(wrong.length)} note="see the table" signal={wrong.length > 0} />
        </dl>
        {wrong.length > 0 ? (
          <div className="relative -mx-5 overflow-x-auto px-5 md:mx-0 md:px-0">
            <table className="w-full min-w-md border-collapse text-xs">
              <caption className="sr-only">Every case this candidate got wrong</caption>
              <thead>
                <tr className="border-b border-ink-40 text-left">
                  <th scope="col" className="label py-2 pr-3 text-ink-40">Case</th>
                  <th scope="col" className="label py-2 pr-3 text-ink-40">Group</th>
                  <th scope="col" className="label py-2 pr-3 text-ink-40">What happened</th>
                  <th scope="col" className="label py-2 text-ink-40">Why it is wrong</th>
                </tr>
              </thead>
              <tbody>
                {wrong.slice(0, 40).map((o) => (
                  <tr key={o.case_id} className="border-b border-rule align-top">
                    <th scope="row" className="py-2 pr-3 text-left font-normal text-ink">{o.case_id}</th>
                    <td className="py-2 pr-3 text-ink-40">{o.group}</td>
                    <td className="py-2 pr-3 text-signal">{o.status}</td>
                    <td className="py-2 text-ink-60">{o.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {wrong.length > 40 ? (
              <p className="m-0 pt-2 text-xs text-ink-40">
                Showing the first 40 of {wrong.length}. The full set is in the artifact below.
              </p>
            ) : null}
          </div>
        ) : (
          <p className="m-0 max-w-2xl text-sm text-ink-60">
            Every scored case was correct. That is what the verdict above is asserting, and nothing
            more.
          </p>
        )}
      </section>

      <section className="frame flex flex-col gap-6 pb-8">
        <Band {...band('provenance', 'What can and cannot be established')} />
        <div className="grid gap-8 lg:grid-cols-2">
          <dl className="m-0 grid gap-x-8 gap-y-4 text-xs sm:grid-cols-2">
            <Row term="Executed at revision" value={run.provenance.executed_at_revision} />
            <Row term="Built this artifact" value={run.provenance.artifact_revision} />
            <Row term="Evaluator revision" value={run.provenance.evaluator_revision} />
            <Row term="Spec hash" value={run.provenance.spec_hash} />
            <Row term="Execution mode" value={run.provenance.execution_mode} note={run.provenance.execution_mode_basis} />
            <Row term="Python" value={run.provenance.python} />
            <Row term="Model calls" value={String(run.usage.model_calls)} />
            <Row term="Spend for this run" value={`$${run.usage.replay_spend_usd}`} note={run.usage.basis} />
            <Row
              term="Recording cost"
              value={run.usage.recording_cost_usd === UNKNOWN ? UNKNOWN : `$${String(run.usage.recording_cost_usd)}`}
            />
            <Row
              term="Sandbox limits"
              value={`${SANDBOX_LIMITS.image}, network ${SANDBOX_LIMITS.network}`}
              note={`${SANDBOX_LIMITS.wall_clock_seconds}s wall clock, ${SANDBOX_LIMITS.secrets} secrets. Not exercised by this run.`}
            />
          </dl>
          <div className="flex flex-col gap-3">
            <p className="label m-0 text-ink-40">Case suites</p>
            {run.provenance.case_suites.map((s) => (
              <p key={s.group} className="m-0 text-xs text-ink-60">
                <span className="text-ink">{s.path}</span>
                <span className="block pt-0.5">
                  {s.n_cases} cases · sha256 {s.sha256.slice(0, 16)}…
                </span>
                <span className="block pt-0.5 text-ink-40">{s.generated_from}</span>
              </p>
            ))}
          </div>
        </div>

        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {run.provenance.notes.map((n, i) => (
            <li
              key={i}
              className={`border-l-2 pl-3 text-xs ${n.severity === 'warning' ? 'border-signal text-ink' : n.severity === 'caution' ? 'border-unknown text-ink-60' : 'border-rule text-ink-60'}`}
            >
              <strong className="text-ink">
                {n.severity === 'warning' ? 'Warning.' : n.severity === 'caution' ? 'Caution.' : 'Note.'}
              </strong>{' '}
              {n.message}
              <span className="block pt-1 text-[11px] text-ink-40">{n.source}</span>
            </li>
          ))}
        </ul>

        <details className="border border-rule bg-paper-secondary">
          <summary className="disclosure label px-4 py-3 text-ink">
            The full artifact, as published
          </summary>
          <p className="m-0 border-t border-rule bg-paper p-4 text-xs text-ink-60">
            Validated against the schema in{' '}
            <span className="text-ink">web/lib/lab/artifact.ts</span> before it was written.{' '}
            <a
              href={`/lab-artifacts/${run.candidate.candidate_id}-${run.run_id.split('__').pop() ?? 'clean'}.json`}
              className="link"
            >
              Download the JSON
            </a>
            .
          </p>
        </details>
      </section>
    </div>
  )
}

function Row({ term, value, note }: { term: string; value: string; note?: string }) {
  return (
    <div>
      <dt className="label m-0 text-ink-40">{term}</dt>
      <dd className={`m-0 mt-0.5 text-xs ${value === UNKNOWN ? 'text-unknown' : 'text-ink'}`}>
        {value}
        {note !== undefined ? (
          <span className="block pt-1 font-sans text-[11px] font-normal tracking-normal text-ink-40">
            {note}
          </span>
        ) : null}
      </dd>
    </div>
  )
}

function Figure({ term, value, note, signal }: { term: string; value: string; note: string; signal?: boolean }) {
  return (
    <div>
      <dt className="label m-0 text-ink-40">{term}</dt>
      <dd className={`readout-sm m-0 mt-1.5 text-2xl ${signal === true ? 'text-signal' : ''}`}>
        {value}
        <span className="block font-sans text-xs font-normal tracking-normal text-ink-40">{note}</span>
      </dd>
    </div>
  )
}
