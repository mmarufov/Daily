import type { Metadata } from 'next'
import Link from 'next/link'

import { Band } from '@/components/Band'
import { Misalignment } from '@/components/Misalignment'
import { Slope, type SlopeRow } from '@/components/Slope'
import { explorerHref } from '@/lib/url-state'

export const metadata: Metadata = {
  title: 'Engineering notes',
  description:
    'One verified defect in Daily’s production relevance scorer, followed from the symptom in a stored scorecard to the lines that caused it, the test that now fails without the fix, and the cost of fixing it.',
}

const RUN = 'prod-llm__2026-08-31__47edb50'
const GH = 'https://github.com/mmarufov/Daily/blob/main'

/**
 * Measured under identical evaluation inputs: same corpus, same k, same ten
 * fixtures, same response cache, zero cache misses on both sides. Only the
 * parse differs, which is what makes this a comparison rather than two
 * unrelated runs.
 */
const COST: readonly SlopeRow[] = [
  {
    key: 'recall_at_k',
    label: 'Capped recall@12',
    a: 0.221,
    b: 0.187,
    verdict: 'worse',
    display: '−3.4 pp',
    material: true,
  },
  {
    key: 'recall_at_retrieval',
    label: 'Reached the scorer',
    a: 0.321,
    b: 0.321,
    verdict: 'unchanged',
    display: 'unchanged',
    material: false,
  },
  {
    key: 'never_rate',
    label: 'Unwanted rate',
    a: 0.269,
    b: 0.425,
    verdict: 'worse',
    display: '+15.6 pp',
    material: true,
  },
  {
    key: 'needle_recall',
    label: 'Planted-needle recall',
    a: 0.6,
    b: 0.45,
    verdict: 'worse',
    display: '−15.0 pp',
    material: true,
  },
  {
    key: 'lookalike_rate',
    label: 'Lookalike rate',
    a: 0.15,
    b: 0.25,
    verdict: 'worse',
    display: '+10.0 pp',
    material: true,
  },
  {
    key: 'event_delivery',
    label: 'World-critical delivery',
    a: 0.25,
    b: 0.1,
    verdict: 'worse',
    display: '−15.0 pp',
    material: true,
  },
]

const TESTS: readonly (readonly [string, string, boolean])[] = [
  ['short response is discarded rather than shifted', 'applied by position', true],
  ['short response is retried before giving up', 'never retried', true],
  ['long response is also discarded', 'extra entry silently dropped', true],
  ['cache miss propagates', 'swallowed, returned all-zero scores', true],
  ['budget exceeded propagates', 'swallowed', true],
  ['aligned response is applied in order', 'unchanged behaviour', false],
  ['scores are clamped to the unit interval', 'unchanged behaviour', false],
  ['ordinary provider errors still fall back', 'unchanged behaviour', false],
  ['request kwargs are the expected shape', 'documents the remaining gap', false],
]

export default function EngineeringPage() {
  return (
    <div className="flex flex-col">
      <section className="frame flex flex-col gap-6 py-12 md:py-16">
        <p className="label m-0 text-ink-40">Defect report · one bug, traced end to end</p>
        <h1 className="display m-0 max-w-4xl text-[clamp(2rem,5.5vw,4rem)]">
          A story the reader needed, rejected for discussing something else entirely
        </h1>
        <p className="lede measure m-0 text-ink-60">
          What the stored evidence showed, which lines caused it, what was fixed, what was
          deliberately <em>not</em> fixed, and what remains wrong afterwards.
        </p>
      </section>

      <section className="frame flex flex-col gap-6 pb-20">
        <Band index="01" title="Symptom" note="Three rejection reasons that describe other articles" />
        <p className="prose measure m-0">
          The harness records, for every article, the stage at which it left the pipeline and any
          reason logged beside it. Reading those traces, three rejections described articles that
          were not the articles they were attached to.
        </p>
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
          These are not vague mismatches. A music rationale landed on a sports story and a sports
          rationale landed on an Uzbek policy story: a clean offset, which is the signature of a
          list applied at the wrong index rather than a model reasoning badly. The middle case is
          sharpest — <span className="text-ink">n-dil-02</span> is a <em>planted needle</em>, an
          article injected at run time precisely so its correct answer is known by construction. It
          was rejected using another article&rsquo;s reasoning.
        </p>
      </section>

      <section className="frame flex flex-col gap-6 pb-20">
        <Band index="02" title="Cause" note="Positional output misalignment" />
        <div className="grid gap-10 lg:grid-cols-[minmax(0,28rem)_minmax(0,1fr)]">
          <div className="flex flex-col gap-5">
            <p className="prose m-0">
              The production feed scores candidates in batches of forty through{' '}
              <Code href={`${GH}/backend/app/services/openai_service.py`}>
                openai_service.score_articles_batch
              </Code>
              . The prompt numbers the articles and asks for one entry per article, same order.{' '}
              <strong>
                No article identifier is sent, and the model is never asked to echo an index back.
              </strong>{' '}
              Nothing in the response says which article a verdict belongs to.
            </p>
            <p className="prose m-0">
              A count mismatch was logged and then ignored. The parse assigned{' '}
              <span className="text-ink">results[i]</span> to{' '}
              <span className="text-ink">articles[i]</span> regardless of length, no output cap was
              set, and <span className="text-ink">finish_reason</span> was never checked — so a
              truncated response looked exactly like a complete one.
            </p>
            <p className="m-0 border-t border-signal pt-3 text-sm text-ink-60">
              Misattributed relevance is worse than absent relevance. Absent scoring is visible
              downstream as a fallback and can be retried. A shifted verdict silently drops a story
              and files a plausible rationale about a different one, which is indistinguishable
              from the model simply disagreeing with you.
            </p>
          </div>
          <Misalignment />
        </div>
        <p className="m-0 max-w-3xl text-sm text-ink-60">
          The contrast inside the same repository confirms the diagnosis. The prototype pipeline
          requires every verdict to echo its <span className="text-ink">id</span> and drops
          unmatched verdicts rather than trusting position — and every rejection reason in the
          prototype scorecards matches its own headline. A correct implementation already exists on
          the product side too, in{' '}
          <Code href={`${GH}/backend/app/services/ranking_provider.py`}>ranking_provider.py</Code>,
          which keys judgments by article id, sets an explicit output cap, uses a strict JSON
          schema and treats truncation as failure instead of salvage. It is gated behind{' '}
          <span className="text-ink">S7_PROVIDER_ENABLED</span> and is not what the live feed
          calls.
        </p>
      </section>

      <section className="frame flex flex-col gap-6 pb-20">
        <Band index="03" title="Fix, and one deliberate non-fix" note="The request bytes are untouched" />
        <div className="grid gap-10 lg:grid-cols-2">
          <div className="flex flex-col gap-4">
            <p className="label m-0 text-ink-40">What landed</p>
            <ul className="m-0 flex list-none flex-col gap-4 p-0">
              <Item term="A length mismatch discards the batch">
                The retry loop gets another attempt instead of verdicts assigned by position. If
                every attempt mismatches, the batch reports itself unscored rather than partly
                guessed.
              </Item>
              <Item term="CacheMiss and BudgetExceeded propagate">
                Both subclass <span className="text-ink">RuntimeError</span> and were being
                swallowed by a blanket handler, so an offline replay that should have failed closed
                instead produced a fully degraded run where every article scored 0.0 — while still
                reporting zero cache misses, because the harness only counts a miss on the live
                network path.
              </Item>
            </ul>
          </div>
          <div className="flex flex-col gap-4">
            <p className="label m-0 text-signal">What was deliberately left broken</p>
            <p className="prose m-0 text-base">
              The complete fix is id-keyed output, exactly as{' '}
              <span className="text-ink">ranking_provider.py</span> already does it. That
              necessarily changes the scoring prompt — and the regression gate replays model
              responses keyed by a content hash of the request. Changing the prompt invalidates
              every committed response for this runner, which is the evidence base the gate runs
              against.
            </p>
            <p className="prose m-0 text-base">
              Bundling a correctness fix with the destruction of the baseline that proves it would
              leave no way to show the fix helped. So the alignment guard lands first, and the
              prompt change is staged behind a cache rebuild.
            </p>
          </div>
        </div>
      </section>

      <section className="frame flex flex-col gap-6 pb-20">
        <Band index="04" title="How often it fires" note="One runner, one corpus, ten fixtures" />
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,30rem)]">
          <dl className="m-0 grid grid-cols-2 gap-x-6 gap-y-8 self-start sm:grid-cols-4 lg:grid-cols-2">
            <Figure term="Guard fires" value="63" note="across the ten fixtures" signal />
            <Figure term="Cache misses" value="0" note="replayed entirely offline" />
            <Figure term="Worst response" value="201" note="verdicts for 40 articles" signal />
            <Figure term="Model calls" value="44 → 84" note="retries are not free" />
          </dl>
          <div className="flex flex-col gap-4">
            <p className="prose m-0">
              Not rarely. The observed mismatches are not off-by-one either: 27 verdicts returned
              for 40 articles, 33 for 40, 18 for 20, and in one case <strong>201 for 40</strong> —
              the documented looping failure, five times over. Every one of those was previously
              applied by position.
            </p>
            <p className="prose m-0">
              Which means the uncomfortable part:{' '}
              <strong>
                every production-pipeline number in the committed scorecards was computed with
                verdict lists shifted against their articles.
              </strong>
            </p>
          </div>
        </div>
      </section>

      <section className="frame flex flex-col gap-6 pb-20">
        <Band index="05" title="What the fix cost" note="Identical inputs, only the parse differs" />
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
          <Slope
            rows={COST}
            aLabel="Committed scorecard"
            bLabel="With the alignment guard"
            note="Reached the scorer is the control: the fix touches scoring, not retrieval, and retrieval is unchanged exactly as it should be."
          />
          <div className="flex flex-col gap-4 self-start">
            <p className="prose m-0 text-base">
              That is not &ldquo;the fix made the product worse&rdquo;. It is two facts at once.
              The committed numbers were inflated by misattribution — 22.1% was never a measurement
              of the pipeline judging correctly, because it counted verdicts that landed on the
              right article by accident.
            </p>
            <p className="prose m-0 text-base">
              And refusing to guess is currently expensive: on a mismatch the guard discards all
              forty verdicts, so those candidates carry no relevance signal at all. That is why the
              unwanted rate climbs — with no signal, nothing is filtering unwanted stories out.
              Neither number describes a healthy pipeline. The first is meaningless; the second is
              the honest price of having no way to salvage a partial response, which is precisely
              what article ids would buy.
            </p>
          </div>
        </div>
      </section>

      <section className="frame flex flex-col gap-6 pb-20">
        <Band index="06" title="Verification" note="Nine tests, five of them new failures" />
        <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
          <ul className="m-0 flex list-none flex-col gap-px border-y border-rule p-0">
            {TESTS.map(([name, before, fails]) => (
              <li
                key={name}
                className="grid grid-cols-[1fr_auto] items-baseline gap-4 py-2 sm:grid-cols-[1fr_15rem]"
              >
                <span className="text-xs text-ink">{name}</span>
                <span className={`text-xs ${fails ? 'text-signal' : 'text-ink-40'}`}>
                  {fails ? 'fails' : 'passes'} before — {before}
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
              . Five fail against the unfixed code and pass with the fix; the other four are
              non-regression guards that correctly pass either way.
            </p>
            <p className="m-0 border-t border-signal pt-3 text-sm text-ink-60">
              The regression gate goes from{' '}
              <span className="text-ink">42 passed, 59 subtests passed</span> to{' '}
              <span className="text-ink">6 failed, 53 subtests passed</span>.{' '}
              <strong className="text-ink">The baseline was deliberately not re-recorded.</strong>{' '}
              The gate is correctly reporting that behaviour changed materially; re-recording it to
              get a green badge would destroy the only evidence that the change had a cost.
              Re-baselining here requires reviewed promotion evidence, and &ldquo;the badge is
              green&rdquo; is not that evidence.
            </p>
          </div>
        </div>
      </section>

      <section className="frame flex flex-col gap-6 pb-20">
        <Band index="07" title="What remains true" note="Still broken, stated rather than buried" />
        <div className="grid gap-x-10 gap-y-7 md:grid-cols-2">
          <Item term="A reordered response still slips through" signal>
            The scorer still sends no article ids, so a response of the <em>right length</em> but
            internally reordered would still be misapplied. The guard catches count mismatches,
            which is what the evidence showed — not every possible misalignment.
          </Item>
          <Item term="No output cap, no finish_reason check" signal>
            Both still missing on this path. Both belong with the prompt change.
          </Item>
          <Item term="The evidence predates the default branch" signal>
            Every scorecard on this site was executed at a revision that is not reachable from the
            default branch, and none of them records an evaluation protocol. They are evidence
            about that historical run, not about the code shipping today. Every run in the explorer
            carries the caveat.
          </Item>
          <Item term="The corrected prototype is untested by CI" signal>
            The regression gate&rsquo;s prototype tier runs a historical legacy adapter, so the
            corrected default prototype pipeline is not exercised by the committed suite at all.
          </Item>
        </div>
      </section>

      <section className="frame flex flex-col gap-6 pb-8">
        <Band index="08" title="How the pieces fit" note="Where this site stops" />
        <div className="grid gap-10 lg:grid-cols-[minmax(0,32rem)_minmax(0,1fr)]">
          <div className="flex flex-col gap-5">
            <p className="prose m-0">
              Daily is an iPhone app against a FastAPI backend and Postgres. The backend is a
              stateful process: its startup path launches seven background loops — ingestion,
              prewarm, source quality, interest evolution, per-user refresh, account maintenance,
              ranking refresh — applies schema, and elects a leader with a Postgres advisory lock.
              That is a daemon, and it stays where it runs today.
            </p>
            <p className="prose m-0">
              This site is a separate read tier. It does not reimplement ranking: the reader
              replays a dated frozen corpus, and the explorer renders immutable artifacts exported
              from the harness&rsquo;s own scorecards. Nothing here scores an article.
            </p>
          </div>
          <dl className="m-0 grid gap-x-8 gap-y-6 self-start sm:grid-cols-2">
            <Boundary term="Web tier">
              Next.js on Vercel. Server components read validated artifacts; public results are
              immutable and cached; no personalised response is ever shared.
            </Boundary>
            <Boundary term="Artifacts">
              A versioned, validated export with explicit provenance. Three revisions kept apart:
              the one that executed an evaluation, the one that stores the scorecard, and the one
              that built the artifact.
            </Boundary>
            <Boundary term="Backend">
              Unchanged except for the scoped fix above. Ingestion, the background workers, the
              database and every feature gate stay exactly where they were.
            </Boundary>
            <Boundary term="Ground truth">
              Model-written labels with an agent editorial pass. Product-owner human review is
              outstanding, so absolute values are provisional and only run-to-run differences are
              gate-enforced.
            </Boundary>
          </dl>
        </div>
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
        fixture {persona} · dropped at {stage}
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
      </dd>
      <p className="m-0 mt-1 text-xs text-ink-40">{note}</p>
    </div>
  )
}

function Boundary({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-rule pt-3">
      <dt className="label m-0 text-ink-40">{term}</dt>
      <dd className="m-0 mt-2 text-sm text-ink-60">{children}</dd>
    </div>
  )
}
