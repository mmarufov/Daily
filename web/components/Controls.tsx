'use client'

import Link from 'next/link'
import { useRef } from 'react'

import type { ManifestEntry } from '@/lib/artifact'
import { explorerHref, VIEWS, type ExplorerState, type OutcomeFilter, type View } from '@/lib/url-state'

interface ControlsProps {
  readonly state: ExplorerState
  readonly entries: readonly ManifestEntry[]
  readonly personas: readonly string[]
}

const OUTCOME_LABELS: Record<OutcomeFilter, string> = {
  all: 'Every story',
  'delivered-wanted': 'Delivered — wanted',
  'delivered-unwanted': 'Delivered — unwanted',
  'delivered-unlabelled': 'Delivered — unlabelled',
  'lost-before-scorer': 'Lost before the scorer',
  'lost-at-or-after-scorer': 'Lost at or after the scorer',
}

const VIEW_LABELS: Record<View, string> = {
  summary: 'Summary',
  funnel: 'Funnel',
  stories: 'Stories',
}

/**
 * Explorer controls as a plain GET form.
 *
 * Submitting a GET form to /evidence produces exactly the shareable URL the
 * explorer reads, which means every control works with JavaScript disabled and
 * the browser's own history handles back and forward. The client component adds
 * only one thing: submitting on change so a selection does not need a second
 * click. The visible Apply button is kept for keyboard and no-JS use rather
 * than hidden behind a noscript tag.
 */
export function Controls({ state, entries, personas }: ControlsProps) {
  const formRef = useRef<HTMLFormElement>(null)

  const submitNow = () => {
    formRef.current?.requestSubmit()
  }

  const runs = entries.filter((e) => !e.is_baseline)
  const comparable = runs.filter((e) => e.run_id !== state.run)

  return (
    <div className="flex flex-col gap-4 border border-sepia bg-paper-secondary p-4">
      <form ref={formRef} method="get" action="/evidence" className="flex flex-col gap-4">
        {/* The story selection is context, not a control; preserve it across
            filter changes so moving between views does not lose the trace. */}
        {state.story !== undefined ? (
          <input type="hidden" name="story" value={state.story} />
        ) : null}
        <input type="hidden" name="view" value={state.view} />

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Run" htmlFor="run-select">
            <Select id="run-select" name="run" value={state.run ?? ''} onChange={submitNow}>
              {runs.map((entry) => (
                <option key={entry.run_id} value={entry.run_id}>
                  {describeEntry(entry)}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Compare against" htmlFor="compare-select">
            <Select
              id="compare-select"
              name="compare"
              value={state.compare ?? ''}
              onChange={submitNow}
            >
              <option value="">No comparison</option>
              {comparable.map((entry) => (
                <option key={entry.run_id} value={entry.run_id}>
                  {describeEntry(entry)}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Reader fixture" htmlFor="persona-select">
            <Select
              id="persona-select"
              name="persona"
              value={state.persona ?? ''}
              onChange={submitNow}
            >
              <option value="">All ten, aggregated</option>
              {personas.map((key) => (
                <option key={key} value={key}>
                  {key}
                </option>
              ))}
            </Select>
          </Field>

          {state.view === 'stories' ? (
            <Field label="Outcome" htmlFor="outcome-select">
              <Select
                id="outcome-select"
                name="outcome"
                value={state.outcome}
                onChange={submitNow}
              >
                {Object.entries(OUTCOME_LABELS).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </Field>
          ) : null}
        </div>

        <div>
          <button
            type="submit"
            className="rounded-button border border-ink px-3 py-1.5 text-sm font-semibold"
          >
            Apply
          </button>
        </div>
      </form>

      <div role="tablist" aria-label="Explorer view" className="flex flex-wrap gap-2 border-t border-sepia pt-4">
        {VIEWS.map((view) => {
          const selected = state.view === view
          return (
            <Link
              key={view}
              role="tab"
              aria-selected={selected}
              href={explorerHref(state, { view })}
              className={[
                'rounded-button border px-3 py-1.5 text-sm font-semibold no-underline',
                selected
                  ? 'border-ink bg-ink text-paper'
                  : 'border-sepia bg-paper text-ink hover:border-ink',
              ].join(' ')}
            >
              {VIEW_LABELS[view]}
            </Link>
          )
        })}
      </div>
    </div>
  )
}

function Select({
  id,
  name,
  value,
  onChange,
  children,
}: {
  id: string
  name: string
  value: string
  onChange: () => void
  children: React.ReactNode
}) {
  return (
    <select
      id={id}
      name={name}
      defaultValue={value}
      onChange={onChange}
      className="w-full rounded-thumb border border-sepia bg-paper px-2 py-1.5 text-sm"
    >
      {children}
    </select>
  )
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string
  htmlFor: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={htmlFor} className="meta-caps text-ink-60">
        {label}
      </label>
      {children}
    </div>
  )
}

export function describeEntry(entry: ManifestEntry): string {
  return `${entry.runner} · ${entry.snapshot} · k=${entry.k}`
}
