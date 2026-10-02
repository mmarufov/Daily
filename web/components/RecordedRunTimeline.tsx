import { CaseStatusMark } from './CaseStatusMark'
import {
  executionElapsed,
  ISOLATION_LABELS,
  loadRecordedExecution,
  RECORDED_EXECUTION_HREF,
  RECORDED_EXECUTION_ID,
  type RecordedExecution,
} from '@/lib/recorded-execution'

/** Recorded-only extraction of Console's Timeline/Probes from 07caa9cc. */
export async function RecordedRunTimeline() {
  return <RecordedRunTimelineView execution={await loadRecordedExecution()} />
}

export function RecordedRunTimelineView({ execution }: { execution: RecordedExecution | null }) {
  if (execution === null) {
    return (
      <div className="recorded-execution" data-testid="recorded-run-timeline">
        <h3>Recorded production execution</h3>
        <p>The recorded execution is unavailable. Open the Lab to inspect or run a parser.</p>
        <a className="text-link" href="/lab#run">Open the Lab <span aria-hidden="true">↗</span></a>
      </div>
    )
  }

  const { progress, outcome } = execution.response
  const origin = progress[0]!.at
  const date = new Intl.DateTimeFormat('en-US', {
    month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC',
  }).format(new Date(origin))

  return (
    <div className="recorded-execution" data-testid="recorded-run-timeline" data-run-id={RECORDED_EXECUTION_ID}>
      <div className="recorded-execution-heading">
        <h3>Recorded production execution <span>· {execution.preset}</span></h3>
        <p><time dateTime={origin}>{date}</time> · UTC · elapsed seconds</p>
      </div>
      <ol className="recorded-timeline" aria-label="Recorded production execution timeline">
        {progress.map((event) => (
          <li key={event.at} className="recorded-timeline-row">
            <span className="recorded-timeline-time" aria-label={`${executionElapsed(event.at, origin)} seconds`}>
              {executionElapsed(event.at, origin)}
            </span>
            <span className="recorded-timeline-dot" aria-hidden="true" />
            <div className="recorded-timeline-step">
              {event.stage}
              {event.stage === 'probing isolation' ? (
                <ul className="recorded-timeline-probes" aria-label="Recorded isolation checks">
                  {outcome.sandbox.isolation.map((probe) => (
                    <li key={probe.name} data-held={probe.held} title={probe.expectation}>
                      <CaseStatusMark tone={probe.held ? 'correct' : 'wrong'} />
                      <span>{ISOLATION_LABELS[probe.name]}<span className="sr-only">: {probe.held ? 'passed' : 'failed'}</span></span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </li>
        ))}
        <li className="recorded-timeline-row">
          <span className="recorded-timeline-time" />
          <span className="recorded-timeline-dot" aria-hidden="true" />
          <div className="recorded-timeline-step">graded outside the microVM</div>
        </li>
      </ol>
      <p className="recorded-execution-provenance">
        Spec {outcome.grading.spec_version} · <code>{outcome.grading.spec_hash}</code> · {outcome.grading.verdict}.
      </p>
      <a className="text-link recorded-execution-source" href={RECORDED_EXECUTION_HREF}>
        Inspect the recorded run <span aria-hidden="true">↗</span>
      </a>
    </div>
  )
}
