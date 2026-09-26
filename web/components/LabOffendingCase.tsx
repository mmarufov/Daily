import { z } from 'zod'

/**
 * The failure, shown rather than described.
 *
 * Two columns, with nothing joining them but their index — which is precisely
 * the defect. The counts are read from the recorded response, so the absurd
 * pair (forty articles, two hundred and fifty-four verdicts) is not an
 * illustration of a possible failure but the one that happened.
 */

export const OffendingCaseSchema = z.object({
  case_id: z.string(),
  snapshot: z.string(),
  articles_sent: z.number().int(),
  verdicts_returned: z.number().int(),
  articles: z.array(z.object({ position: z.number().int(), id: z.string(), title: z.string(), source: z.string() })),
  verdicts: z.array(z.object({ position: z.number().int(), reason: z.string() })),
  response_bytes: z.number().int(),
  response_head: z.string(),
  finish_reason: z.string(),
  note: z.string(),
  source: z.string(),
})
export type OffendingCase = z.infer<typeof OffendingCaseSchema>

export function OffendingCase({ data }: { data: OffendingCase }) {
  const looped = data.verdicts_returned > data.articles_sent
  return (
    <div className="flex flex-col gap-5">
      <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-6 sm:grid-cols-4">
        <Stat term="Articles sent" value={String(data.articles_sent)} note="one batch" />
        <Stat
          term="Verdicts returned"
          value={String(data.verdicts_returned)}
          note={looped ? 'the model kept going' : 'short of the batch'}
          signal
        />
        <Stat term="finish_reason" value={data.finish_reason} note={data.finish_reason === 'stop' ? 'not even truncated' : 'stopped early'} />
        <Stat term="Article ids sent" value="0" note="position is the only link" signal />
      </dl>

      <div className="grid gap-px border border-rule bg-rule md:grid-cols-2">
        <div className="min-w-0 bg-paper p-4">
          <p className="label m-0 text-ink-40">What was sent · first 6 of {data.articles_sent}</p>
          <ol className="m-0 mt-3 flex list-none flex-col gap-2 p-0">
            {data.articles.map((a) => (
              <li key={a.id} className="grid grid-cols-[2rem_1fr] gap-2 border-t border-rule pt-2">
                <span className="band-index">{String(a.position).padStart(2, '0')}</span>
                <span className="text-xs text-ink">
                  <span data-verbatim>{a.title}</span>
                  <span className="block pt-0.5 text-ink-40">{a.source}</span>
                </span>
              </li>
            ))}
          </ol>
        </div>
        <div className="min-w-0 bg-paper p-4">
          <p className="label m-0 text-signal">
            What came back · first 6 of {data.verdicts_returned}
          </p>
          <ol className="m-0 mt-3 flex list-none flex-col gap-2 p-0">
            {data.verdicts.map((v) => (
              <li key={v.position} className="grid grid-cols-[2rem_1fr] gap-2 border-t border-rule pt-2">
                <span className="band-index">{String(v.position).padStart(2, '0')}</span>
                <span className="text-xs text-ink-60">&ldquo;{v.reason}&rdquo;</span>
              </li>
            ))}
          </ol>
        </div>
      </div>

      <p className="m-0 max-w-3xl text-xs text-ink-60">{data.note}</p>

      <details className="border border-rule bg-paper-secondary">
        <summary className="disclosure label px-4 py-3 text-ink">
          The recorded response · {data.response_bytes.toLocaleString()} bytes, first 600 shown
        </summary>
        <pre className="m-0 max-w-full overflow-x-auto border-t border-rule bg-paper p-4 text-[11px] leading-relaxed whitespace-pre-wrap break-all text-ink-60">
          {data.response_head}
        </pre>
        <p className="m-0 border-t border-rule px-4 py-3 text-xs text-ink-40">
          Case <span className="text-ink-60">{data.case_id}</span>, corpus{' '}
          <span className="text-ink-60">{data.snapshot}</span>, read from{' '}
          <span className="text-ink-60">{data.source}</span>.
        </p>
      </details>
    </div>
  )
}

function Stat({ term, value, note, signal }: { term: string; value: string; note: string; signal?: boolean }) {
  return (
    <div>
      <dt className="label m-0 text-ink-40">{term}</dt>
      <dd className={`readout-sm m-0 mt-1.5 text-3xl ${signal === true ? 'text-signal' : ''}`}>
        {value}
        <span className="block font-sans text-xs font-normal tracking-normal text-ink-40">{note}</span>
      </dd>
    </div>
  )
}
