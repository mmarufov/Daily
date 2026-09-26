import type { Metadata } from 'next'
import Link from 'next/link'

import { Band } from '@/components/Band'
import { Controls } from '@/components/Controls'
import { FixtureStrip, toFixtureRows } from '@/components/FixtureStrip'
import { FunnelView } from '@/components/FunnelView'
import { Glossary } from '@/components/Glossary'
import { MetricTable } from '@/components/MetricTable'
import { CompatibilityNotice, ProvenancePanel } from '@/components/Provenance'
import { Sieve } from '@/components/Sieve'
import { Slope, type SlopeRow } from '@/components/Slope'
import { StoryDetail, StoryTable } from '@/components/StoryTable'
import {
  countStories,
  findPersona,
  HEADLINE_METRICS,
  outcomeBreakdown,
  RUN_LEVEL_METRICS,
  summaryValue,
} from '@/lib/aggregate'
import type { Artifact } from '@/lib/artifact'
import { assessCompatibility } from '@/lib/compare'
import { defaultComparison, defaultEntry, findEntry, loadArtifact, loadIndex } from '@/lib/data'
import { computeDelta, formatValue } from '@/lib/format'
import { resolveMetric } from '@/lib/metrics'
import { personaLabel, personaName } from '@/lib/personas'
import { explorerHref, readState, type RawSearchParams } from '@/lib/url-state'

export const metadata: Metadata = {
  title: 'Evaluation evidence',
  description:
    'Interactive results from Daily’s offline evaluation harness: per-fixture metrics, the candidate funnel drawn at 1:1 with the corpus, and the recorded trace for individual stories.',
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

  const state = { ...requested, run: primaryEntry.run_id, compare: comparisonEntry?.run_id }

  const compatibility = comparison === null ? null : assessCompatibility(primary, comparison)
  const showDeltas = compatibility?.showDirectionalDeltas ?? false
  const persona = findPersona(primary, state.persona)
  const personaKeys = primary.personas.map((p) => p.key)

  const selectedStory =
    persona !== undefined && state.story !== undefined
      ? persona.stories.find((s) => s.id === state.story)
      : undefined

  return (
    <div className="flex flex-col">
      <section className="hero frame relative flex flex-col gap-6 py-12 md:py-14">
        <p className="label m-0 text-ink-40">
          The ruler · artifacts {index.source === 'blob' ? 'from the published store' : 'committed in this repository'}
        </p>
        <h1 className="display m-0 text-[clamp(2.25rem,6vw,4.5rem)]">Evaluation evidence</h1>
        <p className="lede measure m-0 text-ink-60">
          Ten adversarial fixtures, three frozen corpora, and a recorded trace for every article.
          Pick a run, then follow a story that should have reached a reader and did not.
        </p>
        {index.errors.length > 0 ? (
          <p className="m-0 max-w-2xl border-l-2 border-signal pl-3 text-xs text-ink-60">
            The published artifact set was unreachable, so the committed export is shown instead.
            Nothing is hidden, but the run ids may lag the latest publication.
          </p>
        ) : null}
      </section>

      <section className="frame flex flex-col gap-5 pb-10">
        {requestedButMissing ? (
          <p role="alert" className="m-0 border-l-2 border-signal pl-3 text-xs">
            The run <span className="text-ink">{requested.run}</span> is not in the current
            manifest, so the default is shown instead, rather than silently showing different
            numbers.
          </p>
        ) : null}

        <Controls state={state} entries={index.entries} personas={personaKeys} />

        {compatibility !== null ? <CompatibilityNotice compatibility={compatibility} /> : null}
        {comparisonFailed !== null ? (
          <p role="alert" className="m-0 border-l-2 border-signal pl-3 text-xs text-ink-60">
            The comparison run failed to load: {comparisonFailed}
          </p>
        ) : null}
      </section>

      <RunHeadline primary={primary} comparison={comparison} personaKey={state.persona} />

      {state.view === 'summary' ? (
        <>
          <section className="frame flex flex-col gap-6 pb-16">
            <Band
              index="01"
              title={comparison === null ? 'Metrics' : 'Two runs, one scale'}
              note={
                state.persona === undefined
                  ? `Averaged over ${primary.personas.length} fixtures`
                  : `Fixture ${personaName(state.persona)}`
              }
              as="h2"
            />
            {comparison !== null && showDeltas ? (
              <Slope
                rows={slopeRows(primary, comparison, state.persona)}
                aLabel={primary.provenance.runner}
                bLabel={comparison.provenance.runner}
              />
            ) : null}
            {/* The metric table's intrinsic width exceeds a 375px viewport,
                so it gets its own scroll port rather than pushing the page
                sideways. */}
            <div className="relative -mx-5 overflow-x-auto px-5 md:mx-0 md:px-0">
              <MetricTable
                primary={primary}
                comparison={comparison}
                showDeltas={showDeltas}
                personaKey={state.persona}
              />
            </div>
            {state.persona === undefined ? (
              <p className="m-0 max-w-3xl text-xs text-ink-40">
                The weakest-fixture column exists so an average cannot hide a reader the pipeline
                fails. A filled dot marks a difference past the fixed &plusmn;0.02 cutoff, which is the
                harness author&rsquo;s threshold and not a significance test.
              </p>
            ) : null}
            <Glossary />
          </section>

          <section className="frame flex flex-col gap-6 pb-16">
            <Band index="02" title="Every fixture, no averaging" as="h2" />
            <FixtureStrip
              rows={toFixtureRows(
                primary.personas,
                (key) => explorerHref(state, { persona: key, story: undefined }),
                state.persona,
              )}
              caption="Select one to filter everything above."
            />
          </section>
        </>
      ) : null}

      {state.view === 'funnel' ? (
        <>
          <section className="frame flex flex-col gap-6 pb-16">
            <Band
              index="01"
              title="The sieve"
              note={
                persona === undefined
                  ? 'Pick a fixture to draw it'
                  : `Fixture ${personaName(persona.key)}, 1:1 with the corpus`
              }
              as="h2"
            />
            {persona === undefined ? (
              <div className="flex flex-col gap-3">
                <p className="m-0 max-w-2xl text-xs text-ink-60">
                  One cell per candidate article, so it only means anything for a single fixture. Summing
                  ten would draw the same article ten times and call it a corpus.
                </p>
                <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
                  {personaKeys.map((key) => (
                    <li key={key}>
                      <Link
                        href={explorerHref(state, { persona: key, view: 'funnel' })}
                        className="chip"
                      >
                        {personaName(key)}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <Sieve
                fixtures={[{ key: persona.key, steps: persona.funnel }]}
                initialFixture={persona.key}
                snapshot={primary.provenance.snapshot.name}
                showFixturePicker={false}
              />
            )}
          </section>

          <section className="frame flex flex-col gap-6 pb-16">
            <Band
              index="02"
              title={persona === undefined ? 'Funnel, all fixtures summed' : `Funnel for ${personaName(persona.key)}`}
              as="h2"
            />
            <FunnelView artifact={primary} persona={persona} />
          </section>
        </>
      ) : null}

      {state.view === 'stories' ? (
        <section className="frame flex flex-col gap-6 pb-16">
          <Band
            index="01"
            title={persona === undefined ? 'Stories' : `Stories for ${personaName(persona.key)}`}
            note={persona === undefined ? undefined : `Outcome filter: ${state.outcome}`}
            as="h2"
          />
          {persona === undefined ? (
            <div className="flex flex-col gap-3">
              <p className="m-0 max-w-2xl text-xs text-ink-60">
                Traces are recorded per fixture. Choose one.
              </p>
              <ul className="m-0 flex list-none flex-wrap gap-1.5 p-0">
                {personaKeys.map((key) => (
                  <li key={key}>
                    <Link
                      href={explorerHref(state, { persona: key, view: 'stories' })}
                      className="chip"
                    >
                      {personaName(key)}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <div className="flex flex-col gap-6">
              {selectedStory !== undefined ? (
                <StoryDetail story={selectedStory} persona={persona} />
              ) : null}
              <StoryTable persona={persona} state={state} />
            </div>
          )}
        </section>
      ) : null}

      <section className="frame flex flex-col gap-4 pb-8">
        <Band index="" title="Provenance" note="What can and cannot be established" as="h2" />
        <ProvenancePanel artifact={primary} />
        {comparison !== null ? <ProvenancePanel artifact={comparison} /> : null}
      </section>
    </div>
  )
}

/** Fraction metrics only; the Slope component explains why. */
function slopeRows(
  primary: Artifact,
  comparison: Artifact,
  personaKey: string | undefined,
): readonly SlopeRow[] {
  const read = (artifact: Artifact, metric: string): number | null => {
    if (personaKey !== undefined) {
      const persona = artifact.personas.find((p) => p.key === personaKey)
      return persona?.metrics[metric] ?? null
    }
    return summaryValue(artifact, metric, 'mean')
  }

  // Headline metrics only. The chart answers "what moved, and which way"; the
  // table below it answers "by exactly how much", for every metric. Drawing all
  // fourteen in both places was the same information twice.
  return HEADLINE_METRICS.flatMap((metric) => {
    const def = resolveMetric(metric)
    if (def.kind !== 'fraction') return []
    const a = read(primary, metric)
    const b = read(comparison, metric)
    if (a === null || b === null) return []
    const delta = computeDelta(a, b, metric)
    return [
      {
        key: metric,
        label: def.label,
        a,
        b,
        verdict: delta.verdict,
        display: delta.verdict === 'unchanged' ? 'unchanged' : delta.display,
        material: delta.material,
      } satisfies SlopeRow,
    ]
  })
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
  const personas =
    personaKey === undefined ? primary.personas : primary.personas.filter((p) => p.key === personaKey)

  const unwanted = countStories(personas, (s) => s.outcome === 'delivered-unwanted')
  const lostEarly = countStories(personas, (s) => s.outcome === 'lost-before-scorer')
  const breakdown = outcomeBreakdown(personas)

  return (
    <section className="frame flex flex-col gap-6 border-y border-rule py-7">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <h2 className="headline m-0 text-lg">{describeEntryTitle(primary)}</h2>
        {comparison !== null ? (
          <p className="m-0 text-xs text-ink-40">
            compared with {describeEntryTitle(comparison)}
          </p>
        ) : null}
      </div>

      <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-4">
        {RUN_LEVEL_METRICS.map((metric) => {
          const def = resolveMetric(metric)
          const value = summaryValue(primary, metric, 'mean')
          return (
            <div key={metric}>
              <dt className="label m-0 text-ink-40">{def.label}</dt>
              <dd className="readout-sm m-0 mt-1.5 text-2xl">{formatValue(value, def.kind)}</dd>
            </div>
          )
        })}
      </dl>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,34rem)_minmax(0,1fr)]">
        <p className="m-0 text-sm text-ink-60">
          Across {personas.length} fixture{personas.length === 1 ? '' : 's'}:{' '}
          <span className="text-signal">{unwanted.pairs}</span> unwanted placements delivered (
          {unwanted.uniqueArticles} distinct articles), and{' '}
          <span className="text-signal">{lostEarly.pairs}</span> wanted ones lost before the scorer
          saw them ({lostEarly.uniqueArticles} distinct). A story lost before scoring cannot be
          rescued by better ranking.
        </p>
        <ul className="m-0 flex list-none flex-col gap-1 self-start p-0 text-xs text-ink-40">
          {[...breakdown].map(([outcome, counts]) => (
            <li key={outcome} className="flex justify-between gap-4 border-b border-rule pb-1">
              <span>{outcome}</span>
              <span>
                {counts.pairs} pairs / {counts.uniqueArticles} articles
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

function describeEntryTitle(artifact: Artifact): string {
  const p = artifact.provenance
  return `${p.runner} · ${p.snapshot.name} · k=${p.k}${artifact.baseline.is_baseline ? ' · baseline' : ''}`
}

function NoArtifacts({
  errors,
  incomplete,
}: {
  errors: readonly { where: string; issues: readonly string[] }[]
  incomplete: boolean
}) {
  return (
    <div className="frame flex max-w-2xl flex-col gap-4 py-16">
      <h1 className="editorial m-0 text-3xl">No evaluation artifacts are available</h1>
      <p className="prose m-0">
        {incomplete
          ? 'Artifact files were found but no validated manifest was, so nothing is shown rather than presenting an unverified partial set.'
          : 'Nothing has been exported yet.'}{' '}
        Run <span className="text-ink-60">npm run export:artifacts</span> in{' '}
        <span className="text-ink-60">web/</span> to build the committed export from{' '}
        <span className="text-ink-60">backend/evals/results/</span>.
      </p>
      {errors.length > 0 ? (
        <div>
          <h2 className="label m-0 text-ink-40">Load errors</h2>
          <ul className="m-0 mt-2 flex list-none flex-col gap-2 p-0 text-xs">
            {errors.map((error) => (
              <li key={error.where} className="border-l-2 border-signal pl-3">
                <span className="text-ink">{error.where}</span>
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
    <div className="frame flex max-w-2xl flex-col gap-3 py-16">
      <h1 className="editorial m-0 text-3xl">{title}</h1>
      <p className="m-0 text-xs text-ink-60">{where}</p>
      <ul className="m-0 flex list-none flex-col gap-1 p-0 text-xs text-signal">
        {issues.map((issue, i) => (
          <li key={i}>{issue}</li>
        ))}
      </ul>
      <Link href="/evidence" className="link label self-start">
        Back to the default run
      </Link>
    </div>
  )
}
