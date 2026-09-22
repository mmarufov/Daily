import { UNKNOWN, type Artifact, type ProvenanceNote } from '@/lib/artifact'
import type { Compatibility } from '@/lib/compare'

const SEVERITY_TONE: Record<ProvenanceNote['severity'], string> = {
  info: 'border-rule text-ink-60',
  caution: 'border-unknown text-ink-60',
  warning: 'border-signal text-ink',
}

const SEVERITY_WORD: Record<ProvenanceNote['severity'], string> = {
  info: 'Note',
  caution: 'Caution',
  warning: 'Warning',
}

export function ProvenancePanel({ artifact }: { artifact: Artifact }) {
  const p = artifact.provenance
  const warnings = p.notes.filter((n) => n.severity !== 'info')

  return (
    <details className="border border-rule bg-paper-secondary">
      <summary className="disclosure label px-4 py-3 text-ink">
        Provenance · {p.runner} · {p.snapshot.name}
        {warnings.length > 0 ? (
          <span className="ml-2 text-signal">
            — {warnings.length} caveat{warnings.length === 1 ? '' : 's'} on this run
          </span>
        ) : null}
      </summary>

      <div className="flex flex-col gap-6 border-t border-rule bg-paper p-4">
        <section>
          <p className="label m-0 text-ink-40">Three revisions, kept apart</p>
          <dl className="m-0 mt-2 grid gap-x-6 gap-y-3 text-xs sm:grid-cols-3">
            <Row
              term="Executed the evaluation"
              value={p.eval_revision}
              note={
                p.eval_revision_reachable === false
                  ? 'not reachable from the default branch'
                  : p.eval_revision_reachable === UNKNOWN
                    ? 'reachability unknown'
                    : 'reachable from the default branch'
              }
              mono
            />
            <Row term="Stores the scorecard" value={p.storage_revision} mono />
            <Row term="Built this artifact" value={p.artifact_revision} mono />
          </dl>
          <p className="m-0 mt-2 text-xs text-ink-60">
            {artifact.origin === 'imported-historical'
              ? 'This artifact imports a stored scorecard. It is not a run this pipeline executed, and no current revision is stamped onto its numbers.'
              : 'This artifact was produced by a run this pipeline executed.'}
          </p>
        </section>

        <section>
          <p className="label m-0 text-ink-40">Run identity</p>
          <dl className="m-0 mt-2 grid gap-x-6 gap-y-3 text-xs sm:grid-cols-3">
            <Row term="Runner" value={p.runner} mono />
            <Row term="CLI argument" value={p.runner_cli_arg} mono />
            <Row
              term="Protocol"
              value={p.protocol}
              note={p.protocol_source === 'absent-in-source' ? 'absent in the source scorecard' : 'recorded'}
              mono
            />
            <Row term="k" value={String(p.k)} />
            <Row term="Execution mode" value={p.execution_mode} note={p.execution_mode_basis} />
            <Row
              term="Recorded at"
              value={p.run_created_at}
              note={p.timestamps_trustworthy ? undefined : 'embedded timestamps contradict the content'}
            />
            <Row term="Needles planted" value={String(p.needles)} />
            <Row term="Quiet corpus" value={String(p.quiet)} />
            <Row term="Cache keys touched" value={p.cache_keys === null ? UNKNOWN : String(p.cache_keys)} />
          </dl>
          {p.models.length > 0 ? (
            <p className="m-0 mt-2 text-xs text-ink-60">
              Models observed: <span className="text-ink">{p.models.join(', ')}</span>
            </p>
          ) : null}
        </section>

        <section>
          <p className="label m-0 text-ink-40">Corpus</p>
          <dl className="m-0 mt-2 grid gap-x-6 gap-y-3 text-xs sm:grid-cols-3">
            <Row term="Snapshot" value={p.snapshot.name} />
            <Row
              term="Articles"
              value={p.snapshot.n_articles === null ? UNKNOWN : p.snapshot.n_articles.toLocaleString()}
            />
            <Row term="Frozen at" value={p.snapshot.frozen_now} />
            <Row term="Content hash" value={shorten(p.snapshot.sha256)} mono />
            <Row term="Derived from" value={p.snapshot.derived_from ?? 'original capture'} />
            <Row
              term="Clusters removed"
              value={p.snapshot.removed_clusters.length === 0 ? 'none' : p.snapshot.removed_clusters.join(', ')}
            />
          </dl>
          {p.snapshot.note !== null ? (
            <p className="m-0 mt-2 text-xs text-ink-60">{p.snapshot.note}</p>
          ) : null}
        </section>

        <section>
          <p className="label m-0 text-ink-40">Ground truth</p>
          {p.labels === null ? (
            <p className="m-0 mt-2 text-xs">No label set was found for this snapshot.</p>
          ) : (
            <>
              <dl className="m-0 mt-2 grid gap-x-6 gap-y-3 text-xs sm:grid-cols-3">
                <Row term="Label rows" value={p.labels.rows.toLocaleString()} note="persona/article pairs" />
                <Row
                  term="Distinct articles"
                  value={p.labels.unique_articles.toLocaleString()}
                  note="labelled at least once"
                />
                <Row term="Fixtures" value={String(p.labels.personas)} />
                <Row term="Contested" value={p.labels.contested.toLocaleString()} />
                <Row term="Status" value={p.labels.status.replace(/-/g, ' ')} />
                <Row term="Label models" value={p.labels.models.join(', ') || UNKNOWN} mono />
              </dl>
              <p className="m-0 mt-2 text-xs text-ink-60">
                By source:{' '}
                {Object.entries(p.labels.by_source)
                  .map(([source, count]) => `${source} ${count.toLocaleString()}`)
                  .join(' · ')}
                . Labels are model-written with an agent editorial pass; product-owner human review
                is outstanding, so absolute values are provisional and only run-to-run differences
                are gate-enforced.
              </p>
            </>
          )}
        </section>

        {p.notes.length > 0 ? (
          <section>
            <p className="label m-0 text-ink-40">Caveats</p>
            <ul className="m-0 mt-2 flex list-none flex-col gap-2 p-0">
              {p.notes.map((note, index) => (
                <li
                  key={`${note.severity}-${index}`}
                  className={`border-l-2 pl-3 text-xs ${SEVERITY_TONE[note.severity]}`}
                >
                  <strong>{SEVERITY_WORD[note.severity]}.</strong> {note.message}
                  <span className="block pt-1 text-[11px] text-ink-40">
                    {note.source}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {artifact.baseline.is_baseline ? (
          <section>
            <p className="label m-0 text-ink-40">Baseline file</p>
            <p className="m-0 mt-2 text-xs">
              This file carries regression-gate thresholds for{' '}
              {artifact.baseline.snapshot_baseline_keys.join(', ')}.
              {artifact.baseline.disagrees_with_run.length > 0 ? (
                <>
                  {' '}
                  Its thresholds for{' '}
                  <strong>{artifact.baseline.disagrees_with_run.join(', ')}</strong> disagree with
                  the committed run scorecard for the same runner and snapshot, which means the
                  file was re-recorded after the timestamps inside it.
                </>
              ) : (
                ' Its thresholds agree with the committed run scorecards.'
              )}
            </p>
          </section>
        ) : null}
      </div>
    </details>
  )
}

export function CompatibilityNotice({ compatibility }: { compatibility: Compatibility }) {
  const blocking = compatibility.kind === 'incompatible'
  return (
    <div
      role={blocking ? 'alert' : undefined}
      className={`border-l-2 pl-3 ${blocking ? 'border-signal' : 'border-unknown'}`}
    >
      <p className="m-0 text-sm text-ink">{compatibility.headline}</p>
      {compatibility.issues.length > 0 ? (
        <ul className="m-0 mt-1.5 flex list-none flex-col gap-1 p-0">
          {compatibility.issues.map((issue, index) => (
            <li key={`${issue.field}-${index}`} className="max-w-3xl text-xs text-ink-60">
              <span className="text-ink">{issue.field}</span> — {issue.message}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

function Row({
  term,
  value,
  note,
  mono,
}: {
  term: string
  value: string
  note?: string | undefined
  mono?: boolean
}) {
  return (
    <div>
      <dt className="label m-0 text-ink-40">{term}</dt>
      <dd className={`m-0 mt-0.5 text-xs ${mono === true ? 'break-all text-ink' : ''}`}>
        {value}
        {/* See the note in app/page.tsx: only <dt>/<dd> may sit inside a
            <div> within a <dl>. */}
        {note !== undefined ? (
          <span className="mt-0.5 block text-[11px] text-ink-60">{note}</span>
        ) : null}
      </dd>
    </div>
  )
}

function shorten(hash: string): string {
  return hash === UNKNOWN || hash.length <= 16 ? hash : `${hash.slice(0, 16)}…`
}
