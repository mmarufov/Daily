import type { Metadata } from 'next'
import Link from 'next/link'

import { Band, PageIndex, type Section } from '@/components/Band'
import { Misalignment } from '@/components/Misalignment'
import { Slope, type SlopeRow } from '@/components/Slope'
import { personaName } from '@/lib/personas'
import { explorerHref } from '@/lib/url-state'

export const metadata: Metadata = {
  title: 'Engineering notes',
  description:
    'One verified defect in Daily’s production relevance scorer, followed from the symptom in a stored scorecard to the lines that caused it, the test that now fails without the fix, and the cost of fixing it.',
}

const RUN = 'prod-llm__2026-08-31__47edb50'
const GH = 'https://github.com/mmarufov/Daily/blob/main'

const SECTIONS: readonly Section[] = [
  { index: '01', slug: 'symptom', title: 'Symptom' },
  { index: '02', slug: 'cause', title: 'Cause' },
  { index: '03', slug: 'fix', title: 'The fix' },
  { index: '04', slug: 'cost', title: 'What it cost' },
  { index: '05', slug: 'verification', title: 'Verification' },
  { index: '06', slug: 'remaining', title: 'Still broken' },
]

const band = (slug: string, note?: string) => {
  const s = SECTIONS.find((x) => x.slug === slug)
  return { index: s?.index ?? '', title: s?.title ?? '', slug, note }
}

/**
 * Measured under identical evaluation inputs: same corpus, same k, same ten
 * fixtures, same response cache, zero cache misses on both sides. Only the
 * parse differs, which is what makes this a comparison rather than two
 * unrelated runs.
 */
const COST: readonly SlopeRow[] = [
  { key: 'recall_at_k', label: 'Capped recall@12', a: 0.221, b: 0.187, verdict: 'worse', display: '−3.4 pp', material: true },
  { key: 'recall_at_retrieval', label: 'Reached the scorer', a: 0.321, b: 0.321, verdict: 'unchanged', display: 'unchanged', material: false },
  { key: 'never_rate', label: 'Unwanted rate', a: 0.269, b: 0.425, verdict: 'worse', display: '+15.6 pp', material: true },
  { key: 'needle_recall', label: 'Planted-needle recall', a: 0.6, b: 0.45, verdict: 'worse', display: '−15.0 pp', material: true },
  { key: 'lookalike_rate', label: 'Lookalike rate', a: 0.15, b: 0.25, verdict: 'worse', display: '+10.0 pp', material: true },
  { key: 'event_delivery', label: 'World-critical delivery', a: 0.25, b: 0.1, verdict: 'worse', display: '−15.0 pp', material: true },
]

const TESTS: readonly (readonly [string, string, boolean])[] = [
  ['short response is discarded rather than shifted', 'applied by position', true],
  ['short response is retried before giving up', 'never retried', true],
  ['long response is also discarded', 'extra entry silently dropped', true],
  ['cache miss propagates', 'swallowed, scored everything 0.0', true],
  ['budget exceeded propagates', 'swallowed', true],
  ['aligned response is applied in order', 'unchanged', false],
  ['scores are clamped to the unit interval', 'unchanged', false],
  ['ordinary provider errors still fall back', 'unchanged', false],
  ['request kwargs are the expected shape', 'documents the remaining gap', false],
]

export default function EngineeringPage() {
  return (
    <div className="flex flex-col">
      <section className="frame flex flex-col gap-6 py-12 md:py-16">
        <p className="label m-0 text-ink-40">Defect report</p>
        <h1 className="display m-0 max-w-4xl text-[clamp(2rem,5.5vw,4rem)]">
          A story the reader needed, rejected for discussing something else entirely
        </h1>
        <p className="lede measure m-0 text-ink-60">
          One bug, from the symptom in a stored scorecard to the lines that caused it — and what
          fixing it cost.
        </p>
        <PageIndex sections={SECTIONS} />
      </section>

      <section className="frame flex flex-col gap-6 pb-20">
        <Band {...band('symptom', 'Reasons attached to the wrong articles')} />
        <ul className="m-0 grid list-none gap-px border border-rule bg-rule p-0 lg:grid-cols-3">
          <Offset
            persona="ray"
            story="a00407"
            title="Giants’ 53-man roster to include Odell Beckham"
            reason="The article discusses a music EP, which is irrelevant to the user’s interests."
            stage="blended"
          />
          <Offset
            persona="dilshod"
            story="n-dil-02"
            title="Mirziyoyev signs decree abolishing exit visa-style registration"
            reason="The article discusses NFL team rosters, which is not relevant to the user’s interests."
            stage="blended"
            needle
          />
          <Offset
            persona="farrukh"
            story="a00037"
            title="World mostly shrugs off Bessent’s ‘D-Day’ Iran sanctions threat"
            reason="The article discusses China’s manufacturing activity…"
            stage="rank"
          />
        </ul>
        <p className="m-0 measure text-sm text-ink-60">
          A clean offset, not a model reasoning badly. The middle one is sharpest:{' '}
          <span className="text-ink">n-dil-02</span> is a <em>planted needle</em>, injected so its
          right answer is known by construction — and it was rejected on another
          article&rsquo;s reasoning.
        </p>
      </section>

      <section className="frame flex flex-col gap-6 pb-20">
        <Band {...band('cause', 'Positional output misalignment')} />
        <div className="grid gap-10 lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)]">
          <div className="flex flex-col gap-5">
            <p className="prose m-0">
              The feed scores candidates in batches of forty through{' '}
              <Code href={`${GH}/backend/app/services/openai_service.py`}>score_articles_batch</Code>
              , which asks for one verdict per article in the same order and{' '}
              <strong>sends no article identifier</strong>. The parse is positional. A count
              mismatch was logged and then ignored.
            </p>
            <p className="m-0 border-t border-signal pt-3 text-sm text-ink-60">
              Misattributed relevance is worse than absent relevance. A missing score is visible
              downstream and can be retried; a shifted one silently drops a story and files a
              plausible rationale about a different one.
            </p>
            <details className="text-sm text-ink-60">
              <summary className="disclosure label text-ink-40">
                How the repository itself confirms this
              </summary>
              <p className="m-0 mt-2">
                The prototype pipeline requires every verdict to echo its{' '}
                <span className="text-ink">id</span> and drops unmatched ones — and every rejection
                reason in its scorecards matches its own headline. A correct implementation exists
                on the product side too, in{' '}
                <Code href={`${GH}/backend/app/services/ranking_provider.py`}>ranking_provider.py</Code>
                , which keys by article id, caps output and treats truncation as failure. It is
                gated behind <span className="text-ink">S7_PROVIDER_ENABLED</span> and is not what
                the live feed calls.
              </p>
            </details>
          </div>
          <Misalignment />
        </div>
      </section>

      <section className="frame flex flex-col gap-6 pb-20">
        <Band {...band('fix', 'And one deliberate non-fix')} />
        <div className="grid gap-10 lg:grid-cols-2">
          <div className="flex flex-col gap-4">
            <p className="label m-0 text-ink-40">What landed</p>
            <ul className="m-0 flex list-none flex-col gap-4 p-0">
              <Item term="A length mismatch discards the batch">
                The retry loop gets another attempt instead of verdicts assigned by position. If
                every attempt mismatches, the batch reports itself unscored.
              </Item>
              <Item term="CacheMiss and BudgetExceeded propagate">
                Both were swallowed by a blanket handler, so an offline replay that should have
                failed closed instead scored every article 0.0 — while reporting zero cache misses.
              </Item>
            </ul>
          </div>
          <div className="flex flex-col gap-4">
            <p className="label m-0 text-signal">What was deliberately left broken</p>
            <p className="prose m-0 text-base">
              The complete fix is id-keyed output, which changes the scoring prompt — and the
              regression gate replays responses keyed by a hash of the request. Changing the prompt
              invalidates the entire evidence base the gate runs against.
            </p>
            <p className="prose m-0 text-base">
              Bundling a correctness fix with the destruction of the baseline that proves it leaves
              no way to show the fix helped. So the guard lands first, and the prompt change is
              staged behind a cache rebuild.
            </p>
          </div>
        </div>
      </section>

      <section className="frame flex flex-col gap-6 pb-20">
        <Band {...band('cost', 'Identical inputs, only the parse differs')} />
        <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-7 sm:grid-cols-4">
          <Figure term="Guard fires" value="63" note="one run, ten fixtures" signal />
          <Figure term="Worst response" value="201" note="verdicts for 40 articles" signal />
          <Figure term="Cache misses" value="0" note="replayed entirely offline" />
          <Figure term="Model calls" value="44 → 84" note="retries are not free" />
        </dl>
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
          <Slope rows={COST} aLabel="Committed scorecard" bLabel="With the guard" />
          <div className="flex flex-col gap-4 self-start">
            <p className="prose m-0 text-base">
              Not &ldquo;the fix made it worse&rdquo; — two facts at once. The committed 22.1% was
              never a measurement of the pipeline judging correctly, because it counted verdicts
              that landed on the right article by accident.
            </p>
            <p className="prose m-0 text-base">
              And refusing to guess is expensive: on a mismatch the guard discards all forty
              verdicts, so those candidates carry no relevance signal at all. That is why the
              unwanted rate climbs. Neither number describes a healthy pipeline — the first is
              meaningless, the second is the price of having no way to salvage a partial response.
            </p>
          </div>
        </div>
      </section>

      <section className="frame flex flex-col gap-6 pb-20">
        <Band {...band('verification', 'Nine tests, five of them new failures')} />
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
          <ul className="m-0 flex list-none flex-col gap-px border-y border-rule p-0">
            {TESTS.map(([name, before, fails]) => (
              <li
                key={name}
                className="grid grid-cols-[1fr_auto] items-baseline gap-4 py-2 sm:grid-cols-[1fr_14rem]"
              >
                <span className="text-xs text-ink">{name}</span>
                <span className={`text-xs ${fails ? 'text-signal' : 'text-ink-40'}`}>
                  {fails ? 'failed' : 'passed'} before — {before}
                </span>
              </li>
            ))}
          </ul>
          <div className="flex flex-col gap-4 self-start">
            <p className="prose m-0 text-base">
              Nine tests in{' '}
              <Code href={`${GH}/backend/tests/test_batch_scoring_alignment.py`}>
                test_batch_scoring_alignment.py
              </Code>
              . Five fail against the unfixed code; four are non-regression guards.
            </p>
            <p className="m-0 border-t border-signal pt-3 text-sm text-ink-60">
              The gate goes from <span className="text-ink">42 passed</span> to{' '}
              <span className="text-ink">6 failed</span>, and{' '}
              <strong className="text-ink">the baseline was not re-recorded</strong>. It is
              correctly reporting that behaviour changed; re-recording it for a green badge would
              destroy the only evidence the change had a cost.
            </p>
          </div>
        </div>
      </section>

      <section className="frame flex flex-col gap-6 pb-8">
        <Band {...band('remaining', 'Stated rather than buried')} />
        <div className="grid gap-x-10 gap-y-6 sm:grid-cols-2 lg:grid-cols-4">
          <Item term="Reordering still slips through" signal>
            No article ids are sent, so a response of the right length but internally reordered is
            still misapplied.
          </Item>
          <Item term="No output cap or finish_reason check" signal>
            Both still missing on this path. Both belong with the prompt change.
          </Item>
          <Item term="The evidence predates main" signal>
            Every scorecard here ran at a revision not reachable from the default branch, and none
            records an evaluation protocol.
          </Item>
          <Item term="The corrected prototype is untested" signal>
            CI&rsquo;s prototype tier runs a historical legacy adapter, so the corrected pipeline
            is not exercised at all.
          </Item>
        </div>
        <details className="mt-2 text-sm text-ink-60">
          <summary className="disclosure label text-ink-40">
            Where this site stops and the backend begins
          </summary>
          <div className="mt-3 grid gap-x-10 gap-y-5 sm:grid-cols-2">
            <p className="m-0">
              Daily is an iPhone app against a FastAPI backend and Postgres. The backend is a
              stateful daemon — seven background loops, schema application, a Postgres advisory
              lock for leader election — and it stays where it runs today.
            </p>
            <p className="m-0">
              This site is a separate read tier: the reader replays a frozen corpus, the explorer
              renders immutable artifacts exported from the harness&rsquo;s own scorecards, and
              nothing here scores an article. Labels are model-written with an agent pass, so
              absolute values are provisional.
            </p>
          </div>
        </details>
      </section>
    </div>
  )
}

function Offset({
  persona,
  story,
  title,
  reason,
  stage,
  needle,
}: {
  persona: string
  story: string
  title: string
  reason: string
  stage: string
  needle?: boolean
}) {
  return (
    <li className="flex flex-col gap-3 bg-paper p-4">
      <p className="headline m-0 text-base">{title}</p>
      <p className="m-0 border-l border-signal pl-3 text-sm text-signal">&ldquo;{reason}&rdquo;</p>
      <p className="m-0 mt-auto text-xs text-ink-40">
        fixture {personaName(persona)} · dropped at {stage}
        {needle === true ? ' · planted needle' : ''}
      </p>
      <Link
        href={explorerHref({ run: RUN }, { persona, view: 'stories', story, outcome: 'all' })}
        className="link label self-start"
      >
        open this story&rsquo;s recorded trace
      </Link>
    </li>
  )
}

function Code({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} className="link text-xs" rel="noreferrer">
      {children}
    </a>
  )
}

function Item({
  term,
  children,
  signal,
}: {
  term: string
  children: React.ReactNode
  signal?: boolean
}) {
  return (
    <li className={`list-none border-t pt-3 ${signal === true ? 'border-signal' : 'border-rule'}`}>
      <p className="label m-0 text-ink">{term}</p>
      <p className="m-0 mt-2 max-w-md text-sm text-ink-60">{children}</p>
    </li>
  )
}

function Figure({
  term,
  value,
  note,
  signal,
}: {
  term: string
  value: string
  note: string
  signal?: boolean
}) {
  return (
    <div>
      <dt className="label m-0 text-ink-40">{term}</dt>
      <dd className={`readout-sm m-0 mt-1.5 text-2xl ${signal === true ? 'text-signal' : ''}`}>
        {value}
        {/* See the note in app/page.tsx: only <dt>/<dd> may sit inside a
            <div> within a <dl>. */}
        <span className="block font-sans text-xs font-normal tracking-normal text-ink-40">
          {note}
        </span>
      </dd>
    </div>
  )
}
