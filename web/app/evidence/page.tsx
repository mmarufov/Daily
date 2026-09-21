import type { Metadata } from 'next'
import Link from 'next/link'

import { Controls, describeEntry } from '@/components/Controls'
import { FunnelView } from '@/components/FunnelView'
import { MetricTable } from '@/components/MetricTable'
import { CompatibilityNotice, ProvenancePanel } from '@/components/Provenance'
import { StoryDetail, StoryTable } from '@/components/StoryTable'
import { countStories, findPersona, outcomeBreakdown, RUN_LEVEL_METRICS, summaryValue } from '@/lib/aggregate'
import type { Artifact } from '@/lib/artifact'
import { assessCompatibility } from '@/lib/compare'
import { defaultComparison, defaultEntry, findEntry, loadArtifact, loadIndex } from '@/lib/data'
import { formatValue } from '@/lib/format'
import { resolveMetric } from '@/lib/metrics'
import { explorerHref, readState, type RawSearchParams } from '@/lib/url-state'

export const metadata: Metadata = {
  title: 'Evaluation evidence',
  description:
    'Interactive results from Daily’s offline evaluation harness: per-fixture metrics, the candidate funnel, and the recorded trace for individual stories.',
}

export default async function EvidencePage({
  searchParams,
}: {
  searchParams: Promise<RawSearchParams>
}) {
  const raw = await searchParams
  const requested = readState(raw)
  const index = await loadIndex()

  if (index.entries.length === 0) {
    return <NoArtifacts errors={index.errors} incomplete={index.incomplete} />
  }

  const primaryEntry = findEntry(index.entries, requested.run) ?? defaultEntry(index.entries)
  if (primaryEntry === undefined) {
    return <NoArtifacts errors={index.errors} incomplete={index.incomplete} />
  }

  const requestedButMissing =
    requested.run !== undefined && findEntry(index.entries, requested.run) === undefined

  const comparisonEntry =
    requested.compare !== undefined
      ? findEntry(index.entries, requested.compare)
      : defaultComparison(index.entries, primaryEntry)

  const primaryLoad = await loadArtifact(primaryEntry)
  if (!primaryLoad.ok) {
    return (
      <LoadFailure
        title="That run could not be loaded"
        where={primaryLoad.error.where}
        issues={primaryLoad.error.issues}
      />
    )
  }
  const primary = primaryLoad.artifact

  let comparison: Artifact | null = null
  let comparisonFailed: string | null = null
  if (comparisonEntry !== undefined) {
    const load = await loadArtifact(comparisonEntry)
    if (load.ok) comparison = load.artifact
    else comparisonFailed = load.error.issues.join('; ')
  }

  const state = {
    ...requested,
    run: primaryEntry.run_id,
    compare: comparisonEntry?.run_id,
  }

  const compatibility = comparison === null ? null : assessCompatibility(primary, comparison)
  const showDeltas = compatibility?.showDirectionalDeltas ?? false
  const persona = findPersona(primary, state.persona)
  const personaKeys = primary.personas.map((p) => p.key)

  const selectedStory =
    persona !== undefined && state.story !== undefined
      ? persona.stories.find((s) => s.id === state.story)
      : undefined

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-3">
        <p className="signature-caps m-0 text-ochre">the ruler</p>
        <h1 className="hero-headline m-0 text-3xl sm:text-4xl">Evaluation evidence</h1>
        <p className="dek m-0 max-w-2xl text-ink-60">
          Ten adversarial reader fixtures, three content-hashed corpora, and a recorded trace for
          every article. Pick a run to see what a reader would have received, then follow a story
          that should have reached them and did not.
        </p>
        <p className="m-0 max-w-2xl text-xs text-ink-60">
          Artifacts loaded from {index.source === 'blob' ? 'the published Blob store' : 'the export committed in this repository'}.
          {index.errors.length > 0
            ? ' The published set was unreachable, so the committed export is being shown instead.'
            : ''}
        </p>
      </header>

      {requestedButMissing ? (
        <p role="alert" className="m-0 border-l-2 border-danger pl-3 text-sm">
          The run <span className="font-mono">{requested.run}</span> is not in the current manifest,
          so the default run is shown instead. A link to a run that has since been republished will
          land here rather than silently showing different numbers.
        </p>
      ) : null}

      <Controls state={state} entries={index.entries} personas={personaKeys} />

      {compatibility !== null ? <CompatibilityNotice compatibility={compatibility} /> : null}
      {comparisonFailed !== null ? (
        <p role="alert" className="m-0 border-l-2 border-danger pl-3 text-xs text-ink-60">
          The comparison run failed to load: {comparisonFailed}
        </p>
      ) : null}

      <RunHeadline
        primary={primary}
        comparison={comparison}
        personaKey={state.persona}
      />

      {state.view === 'summary' ? (
        <section className="flex flex-col gap-5">
          <h2 className="meta-caps m-0 text-ink-60">
            {state.persona === undefined
              ? `Averages across ${primary.personas.length} reader fixtures`
              : `Reader fixture ${state.persona}`}
          </h2>
          <MetricTable
            primary={primary}
            comparison={comparison}
            showDeltas={showDeltas}
            personaKey={state.persona}
          />
          {state.persona === undefined ? (
            <p className="m-0 max-w-2xl text-xs text-ink-60">
              The weakest-fixture column exists so an average cannot hide a reader the pipeline
              fails. A filled dot beside a difference means it clears the harness&rsquo;s fixed
              &plusmn;0.02 materiality cutoff — a threshold chosen by the author, not a
              significance test. Ten fixtures with no variance estimate cannot support one.
            </p>
          ) : null}
          <PersonaGrid primary={primary} state={state} />
        </section>
      ) : null}

      {state.view === 'funnel' ? (
        <section className="flex flex-col gap-5">
          <h2 className="meta-caps m-0 text-ink-60">
            {state.persona === undefined ? 'Funnel, all fixtures summed' : `Funnel for ${state.persona}`}
          </h2>
          <FunnelView artifact={primary} persona={persona} />
        </section>
      ) : null}

      {state.view === 'stories' ? (
        <section className="flex flex-col gap-5">
          <h2 className="meta-caps m-0 text-ink-60">
            {persona === undefined ? 'Stories' : `Stories for ${persona.key}`}
          </h2>
          {persona === undefined ? (
            <div className="flex flex-col gap-3">
              <p className="m-0 max-w-2xl text-sm">
                Per-story traces are recorded per reader fixture. Choose one to follow its stories.
              </p>
              <ul className="m-0 flex list-none flex-wrap gap-2 p-0">
                {personaKeys.map((key) => (
                  <li key={key}>
                    <Link
                      href={explorerHref(state, { persona: key, view: 'stories' })}
                      className="rounded-button border border-sepia px-3 py-1.5 text-sm no-underline hover:border-ink"
                    >
                      {key}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="flex flex-col gap-5">
              {selectedStory !== undefined ? <StoryDetail story={selectedStory} /> : null}
              <StoryTable persona={persona} state={state} />
            </div>
          )}
        </section>
      ) : null}

      <ProvenancePanel artifact={primary} />
      {comparison !== null ? <ProvenancePanel artifact={comparison} /> : null}
    </div>
  )
}

function RunHeadline({
  primary,
  comparison,
  personaKey,
}: {
  primary: Artifact
  comparison: Artifact | null
  personaKey: string | undefined
}) {
  const personas = personaKey === undefined
    ? primary.personas
    : primary.personas.filter((p) => p.key === personaKey)

  const unwanted = countStories(personas, (s) => s.outcome === 'delivered-unwanted')
  const lostEarly = countStories(personas, (s) => s.outcome === 'lost-before-scorer')
  const breakdown = outcomeBreakdown(personas)

  return (
    <section className="flex flex-col gap-4 border-y border-sepia py-5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 className="row-headline m-0">{describeEntryTitle(primary)}</h2>
        {comparison !== null ? (
          <p className="m-0 text-sm text-ink-60">compared with {describeEntryTitle(comparison)}</p>
        ) : null}
      </div>

      <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
        {RUN_LEVEL_METRICS.map((metric) => {
          const def = resolveMetric(metric)
          const value = summaryValue(primary, metric, 'mean')
          return (
            <div key={metric}>
              <dt className="meta-caps m-0 text-ink-60">{def.label}</dt>
              <dd className="m-0 mt-0.5 font-serif text-xl font-bold tabular-nums">
                {formatValue(value, def.kind)}
              </dd>
            </div>
          )
        })}
      </dl>

      <p className="m-0 max-w-3xl text-sm text-ink-60">
        Across {personas.length} fixture{personas.length === 1 ? '' : 's'}, this run delivered{' '}
        <strong className="text-danger">{unwanted.pairs}</strong> explicitly unwanted
        story-placements ({unwanted.uniqueArticles} distinct articles), and{' '}
        <strong className="text-danger">{lostEarly.pairs}</strong> wanted story-placements were
        lost before the scorer ever saw them ({lostEarly.uniqueArticles} distinct articles). A
        story lost before scoring cannot be rescued by better ranking.
      </p>

      <ul className="m-0 flex list-none flex-wrap gap-x-5 gap-y-1 p-0 text-xs text-ink-60">
        {[...breakdown].map(([outcome, counts]) => (
          <li key={outcome}>
            <span className="font-mono">{outcome}</span> — {counts.pairs} pairs /{' '}
            {counts.uniqueArticles} articles
          </li>
        ))}
      </ul>
    </section>
  )
}

function describeEntryTitle(artifact: Artifact): string {
  const p = artifact.provenance
  return `${p.runner} · ${p.snapshot.name} · k=${p.k}${artifact.baseline.is_baseline ? ' · baseline' : ''}`
}

function PersonaGrid({
  primary,
  state,
}: {
  primary: Artifact
  state: ReturnType<typeof readState>
}) {
  return (
    <div className="flex flex-col gap-2">
      <h3 className="meta-caps m-0 text-ink-60">Every fixture, no averaging</h3>
      <div className="overflow-x-auto">
        <table className="w-full min-w-lg border-collapse text-sm">
          <caption className="sr-only">
            Capped recall, unwanted rate and reached-the-scorer for each reader fixture
          </caption>
          <thead>
            <tr className="border-b border-ink text-left">
              <th scope="col" className="py-2 pr-3 font-semibold">
                Fixture
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-semibold">
                Capped recall
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-semibold">
                Unwanted rate
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-semibold">
                Reached scorer
              </th>
              <th scope="col" className="py-2 text-right font-semibold">
                Must-see
              </th>
            </tr>
          </thead>
          <tbody>
            {primary.personas.map((persona) => (
              <tr key={persona.key} className="border-b border-sepia">
                <th scope="row" className="py-2 pr-3 text-left font-normal">
                  <Link
                    href={explorerHref(state, { persona: persona.key, story: undefined })}
                    className="text-ink-blue no-underline hover:underline"
                  >
                    {persona.key}
                  </Link>
                </th>
                <td className="py-2 pr-3 text-right tabular-nums">
                  {formatValue(persona.metrics.recall_at_k ?? null, 'fraction')}
                </td>
                <td className="py-2 pr-3 text-right tabular-nums">
                  {formatValue(persona.metrics.never_rate ?? null, 'fraction')}
                </td>
                <td className="py-2 pr-3 text-right tabular-nums">
                  {formatValue(persona.metrics.recall_at_retrieval ?? null, 'fraction')}
                </td>
                <td className="py-2 text-right tabular-nums text-ink-60">
                  {persona.counts.must_see ?? '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function NoArtifacts({
  errors,
  incomplete,
}: {
  errors: readonly { where: string; issues: readonly string[] }[]
  incomplete: boolean
}) {
  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <h1 className="hero-headline m-0 text-3xl">No evaluation artifacts are available</h1>
      <p className="body-reading m-0">
        {incomplete
          ? 'Artifact files were found but no validated manifest was, so nothing is shown rather than presenting an unverified partial set.'
          : 'Nothing has been exported yet.'}{' '}
        Run <code className="font-mono text-sm">npm run export:artifacts</code> in{' '}
        <code className="font-mono text-sm">web/</code> to build the committed export from{' '}
        <code className="font-mono text-sm">backend/evals/results/</code>.
      </p>
      {errors.length > 0 ? (
        <div>
          <h2 className="meta-caps m-0 text-ink-60">Load errors</h2>
          <ul className="m-0 mt-2 flex list-none flex-col gap-2 p-0 text-xs">
            {errors.map((error) => (
              <li key={error.where} className="border-l-2 border-danger pl-3">
                <span className="font-mono">{error.where}</span>
                <span className="block text-ink-60">{error.issues.join('; ')}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

function LoadFailure({
  title,
  where,
  issues,
}: {
  title: string
  where: string
  issues: readonly string[]
}) {
  return (
    <div className="flex max-w-2xl flex-col gap-3">
      <h1 className="hero-headline m-0 text-3xl">{title}</h1>
      <p className="m-0 font-mono text-sm">{where}</p>
      <ul className="m-0 flex list-none flex-col gap-1 p-0 text-sm text-ink-60">
        {issues.map((issue, index) => (
          <li key={index}>{issue}</li>
        ))}
      </ul>
      <Link href="/evidence" className="text-ink-blue underline">
        Back to the default run
      </Link>
    </div>
  )
}
