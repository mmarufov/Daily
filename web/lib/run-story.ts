export type RunStoryCaseStatus = 'correct' | 'failed' | 'not-applicable'
export type IsolationProbeName = 'egress-dns' | 'egress-https' | 'no-evaluator-present' | 'no-secrets-in-env'

export interface RunStoryData {
  readonly runId: string
  readonly preset: string
  readonly date: string
  readonly sourceHref: string
  readonly specVersion: number
  readonly specHash: string
  readonly events: readonly { readonly stage: string; readonly elapsed: string }[]
  readonly probes: readonly { readonly name: IsolationProbeName; readonly label: string; readonly held: boolean }[]
  readonly cases: readonly { readonly id: string; readonly status: RunStoryCaseStatus }[]
  readonly counts: {
    readonly total: number
    readonly correct: number
    readonly failed: number
    readonly notApplicable: number
    readonly faultInjected: number
  }
  readonly failure: { readonly id: string; readonly summary: string }
}
