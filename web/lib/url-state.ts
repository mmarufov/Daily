/**
 * URL state for the evidence explorer.
 *
 * Every selection the explorer supports lives in the query string so any view
 * — a persona, a comparison, a single story's trace — is a link someone can
 * send. Updates are merged rather than replaced so moving between the summary,
 * the funnel and a story never drops the rest of the context.
 */

export const VIEWS = ['summary', 'funnel', 'stories'] as const
export type View = (typeof VIEWS)[number]

export const OUTCOME_FILTERS = [
  'all',
  'delivered-wanted',
  'delivered-unwanted',
  'delivered-unlabelled',
  'lost-before-scorer',
  'lost-at-or-after-scorer',
] as const
export type OutcomeFilter = (typeof OUTCOME_FILTERS)[number]

export interface ExplorerState {
  readonly run: string | undefined
  readonly compare: string | undefined
  readonly persona: string | undefined
  readonly view: View
  readonly outcome: OutcomeFilter
  readonly story: string | undefined
}

export type RawSearchParams = Record<string, string | string[] | undefined>

function first(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value[0]
  return value
}

export function readState(params: RawSearchParams): ExplorerState {
  const viewRaw = first(params.view)
  const outcomeRaw = first(params.outcome)
  return {
    run: first(params.run),
    compare: first(params.compare),
    persona: first(params.persona),
    view: (VIEWS as readonly string[]).includes(viewRaw ?? '') ? (viewRaw as View) : 'summary',
    outcome: (OUTCOME_FILTERS as readonly string[]).includes(outcomeRaw ?? '')
      ? (outcomeRaw as OutcomeFilter)
      : 'all',
    story: first(params.story),
  }
}

/** Merge a patch into existing state and render it as query parameters. */
export function buildQuery(
  current: Readonly<Partial<ExplorerState>>,
  patch: Readonly<Partial<ExplorerState>>,
): Record<string, string> {
  const merged: Partial<ExplorerState> = { ...current, ...patch }
  const query: Record<string, string> = {}
  const put = (key: string, value: string | undefined, skipIf?: string) => {
    if (value === undefined || value === '' || value === skipIf) return
    query[key] = value
  }
  put('run', merged.run)
  put('compare', merged.compare)
  put('persona', merged.persona)
  put('view', merged.view, 'summary')
  put('outcome', merged.outcome, 'all')
  put('story', merged.story)
  return query
}

export interface ExplorerUrl {
  readonly pathname: '/evidence'
  readonly query: Record<string, string>
}

/**
 * Href for the explorer, as a UrlObject.
 *
 * A UrlObject rather than a string because Next's typed-routes checking will
 * not accept an arbitrary interpolated string, and disabling that check to get
 * a build through would give up a real guarantee for a cosmetic reason.
 */
export function explorerHref(
  current: Readonly<Partial<ExplorerState>>,
  patch: Readonly<Partial<ExplorerState>>,
): ExplorerUrl {
  return { pathname: '/evidence', query: buildQuery(current, patch) }
}

/** The same target as a plain string, for tests and for router.push. */
export function explorerHrefString(
  current: Readonly<Partial<ExplorerState>>,
  patch: Readonly<Partial<ExplorerState>>,
): string {
  const query = new URLSearchParams(buildQuery(current, patch)).toString()
  return query === '' ? '/evidence' : `/evidence?${query}`
}
