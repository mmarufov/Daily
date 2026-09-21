import type { Metadata } from 'next'
import Link from 'next/link'

import { explorerHref } from '@/lib/url-state'

export const metadata: Metadata = {
  title: 'Engineering notes',
  description:
    'One verified defect in Daily’s production relevance scorer, followed from the symptom in a stored scorecard to the lines that caused it and the test that now fails without the fix.',
}

const RUN = 'prod-llm__2026-08-31__47edb50'
const GH = 'https://github.com/mmarufov/Daily/blob/main'

export default function EngineeringPage() {
  return (
    <div className="flex flex-col gap-14">
      <header className="flex flex-col gap-3">
        <p className="signature-caps m-0 text-ochre">engineering notes</p>
        <h1 className="hero-headline m-0 max-w-3xl text-3xl sm:text-4xl">
          A story the reader needed, rejected for discussing something else entirely
        </h1>
        <p className="dek m-0 max-w-2xl text-ink-60">
          One defect, traced end to end: what the stored evidence showed, which lines caused it,
          what was fixed, what was deliberately not fixed, and what remains true afterwards.
        </p>
      </header>

      <Section n="1" title="Symptom">
        <p className="body-reading m-0 max-w-2xl">
          Daily&rsquo;s evaluation harness records, for every article, the stage at which it left
          the pipeline and any reason logged beside it. Reading those traces, three rejection
          reasons described articles that were not the articles they were attached to.
        </p>
        <ul className="m-0 flex list-none flex-col gap-4 p-0">
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
        <p className="m-0 max-w-2xl text-sm text-ink-60">
          These are not vague mismatches. A music rationale landed on a sports story, a sports
          rationale landed on an Uzbek policy story: a clean offset, which is the signature of a
          list applied at the wrong index rather than a model reasoning badly. The middle case is
          the sharpest — <code className="font-mono text-xs">n-dil-02</code> is a{' '}
          <em>planted needle</em>, an article injected at run time specifically so its correct
          answer is known by construction. It was rejected with another article&rsquo;s reasoning.
        </p>
      </Section>

      <Section n="2" title="Trace">
        <p className="body-reading m-0 max-w-2xl">
          The production feed scores candidates in batches of 40 through{' '}
          <Code href={`${GH}/backend/app/services/openai_service.py`}>
            openai_service.score_articles_batch
          </Code>
          . Following one batch through it:
        </p>
        <ol className="m-0 flex list-decimal flex-col gap-2 pl-6 text-sm">
          <li>
            The prompt numbers the articles —{' '}
            <code className="font-mono text-xs">{`f"{i}. [{source}] {title}"`}</code> — and asks
            for <code className="font-mono text-xs">{`{"results": [...]}`}</code> with{' '}
            <em>&ldquo;one entry per article, same order&rdquo;</em>.
          </li>
          <li>
            <strong>No article identifier is sent, and the model is never asked to echo an index
            back.</strong> Nothing in the response says which article a verdict belongs to.
          </li>
          <li>
            A count mismatch was logged and then ignored: the handler emitted{' '}
            <em>&ldquo;returned N results for M articles; normalizing&rdquo;</em> and fell through.
          </li>
          <li>
            The parse was positional, assigning{' '}
            <code className="font-mono text-xs">results_list[i]</code> to{' '}
            <code className="font-mono text-xs">articles[i]</code> regardless of length.
          </li>
          <li>
            No output cap was set and{' '}
            <code className="font-mono text-xs">finish_reason</code> was never checked, so a
            truncated response looked identical to a complete one.
          </li>
        </ol>
        <p className="m-0 max-w-2xl text-sm text-ink-60">
          Downstream, <Code href={`${GH}/backend/app/services/feed_service.py`}>feed_service</Code>{' '}
          applies that list positionally too, and the harness records each reason into the trace by
          zipping the batch against the result — so the misattribution is carried faithfully into
          the scorecard rather than introduced by the measurement.
        </p>
      </Section>

      <Section n="3" title="Cause">
        <p className="body-reading m-0 max-w-2xl">
          Positional output misalignment. One missing, merged or reordered entry shifts every later
          verdict onto the wrong article. Because the score travels with the wrong story, a story
          the reader needed is dropped on another article&rsquo;s reasoning, and the log records a
          confident explanation for a decision that was never made about it.
        </p>
        <p className="body-reading m-0 max-w-2xl">
          The contrast inside the same repository is what confirms the diagnosis. The prototype
          pipeline requires every verdict to echo its{' '}
          <code className="font-mono text-xs">id</code> and drops unmatched verdicts rather than
          trusting position — and every rejection reason in the prototype scorecards matches its
          own headline. A correct implementation also already exists on the product side, in{' '}
          <Code href={`${GH}/backend/app/services/ranking_provider.py`}>ranking_provider.py</Code>,
          which keys judgments by article id, sets an explicit output cap, uses a strict JSON
          schema, and treats truncation as failure instead of salvage. It is gated behind{' '}
          <code className="font-mono text-xs">S7_PROVIDER_ENABLED</code> and is not what the live
          feed calls.
        </p>
        <Aside>
          Misattributed relevance is worse than absent relevance. Absent scoring is visible
          downstream as a fallback reason and can be retried. A shifted verdict silently drops a
          story and files a plausible rationale about a different one, which is indistinguishable
          from the model simply disagreeing with you.
        </Aside>
      </Section>

      <Section n="4" title="Fix, and one deliberate non-fix">
        <p className="body-reading m-0 max-w-2xl">
          Two changes landed in{' '}
          <Code href={`${GH}/backend/app/services/openai_service.py`}>openai_service.py</Code>,
          both chosen so that the bytes of the outbound request are untouched:
        </p>
        <ul className="m-0 flex list-disc flex-col gap-2 pl-6 text-sm">
          <li>
            A length mismatch now <strong>discards the batch</strong> and lets the retry loop try
            again, instead of assigning verdicts by position. If every attempt mismatches, the
            batch reports itself unscored rather than partly guessed.
          </li>
          <li>
            The evaluation harness&rsquo;s <code className="font-mono text-xs">CacheMiss</code> and{' '}
            <code className="font-mono text-xs">BudgetExceeded</code> now propagate instead of
            being swallowed by the blanket handler. Both subclass{' '}
            <code className="font-mono text-xs">RuntimeError</code>, so an offline replay that
            should have failed closed was instead producing a fully degraded run in which every
            article scored 0.0 — while still reporting zero cache misses, because the harness only
            counts a miss on the live network path.
          </li>
        </ul>
        <p className="body-reading m-0 max-w-2xl">
          <strong>What was not done, and why.</strong> The complete fix is id-keyed output, exactly
          as <code className="font-mono text-xs">ranking_provider.py</code> already does it. That
          necessarily changes the scoring prompt — and the regression gate replays model responses
          keyed by a content hash of the request. Changing the prompt invalidates every committed
          response for this runner, which is the evidence base the gate runs against. Bundling a
          correctness fix with the destruction of the baseline that proves it would leave no way to
          show the fix helped. So the alignment guard lands first, and the prompt change is staged
          behind a cache rebuild.
        </p>
      </Section>

      <Section n="5" title="Verification">
        <p className="body-reading m-0 max-w-2xl">
          Nine tests in{' '}
          <Code href={`${GH}/backend/tests/test_batch_scoring_alignment.py`}>
            test_batch_scoring_alignment.py
          </Code>
          . Five of them fail against the unfixed code and pass with the fix; the other four are
          non-regression guards that correctly pass either way.
        </p>
        <table className="w-full max-w-2xl border-collapse text-sm">
          <caption className="sr-only">Regression tests and their behaviour before the fix</caption>
          <thead>
            <tr className="border-b border-ink text-left">
              <th scope="col" className="py-2 pr-3 font-semibold">Test</th>
              <th scope="col" className="py-2 font-semibold">Before the fix</th>
            </tr>
          </thead>
          <tbody>
            {[
              ['short response is discarded rather than shifted', 'fails — applied by position'],
              ['short response is retried before giving up', 'fails — never retried'],
              ['long response is also discarded', 'fails — extra entry silently dropped'],
              ['cache miss propagates', 'fails — swallowed, returned all-zero scores'],
              ['budget exceeded propagates', 'fails — swallowed'],
              ['aligned response is applied in order', 'passes — unchanged behaviour'],
              ['scores are clamped to the unit interval', 'passes — unchanged behaviour'],
              ['ordinary provider errors still fall back', 'passes — unchanged behaviour'],
              ['request kwargs are the expected shape', 'passes — documents the remaining gap'],
            ].map(([name, before]) => (
              <tr key={name} className="border-b border-sepia">
                <th scope="row" className="py-2 pr-3 text-left font-normal">{name}</th>
                <td className="py-2 text-ink-60">{before}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <h3 className="meta-caps m-0 mt-4 text-ink-60">How often the defect fires</h3>
        <p className="body-reading m-0 max-w-2xl">
          Not rarely. One runner against one corpus, replayed offline with zero cache misses,
          trips the new guard <strong>63 times</strong> across the ten fixtures. The observed
          mismatches are not off-by-one: 27 verdicts returned for 40 articles, 33 for 40, 18 for
          20, and in one case <strong>201 for 40</strong> — the documented looping failure, five
          times over. Every one of those was previously applied by position.
        </p>
        <p className="body-reading m-0 max-w-2xl">
          Which means the uncomfortable part: <strong>every production-pipeline number in the
          committed scorecards was computed with verdict lists shifted against their
          articles.</strong>
        </p>

        <h3 className="meta-caps m-0 mt-4 text-ink-60">Measured cost, identical inputs</h3>
        <p className="body-reading m-0 max-w-2xl">
          Same corpus, same k, same ten fixtures, same response cache, zero cache misses on both
          sides. Only the parse differs, so this is a comparable measurement rather than two
          unrelated runs.
        </p>
        <table className="w-full max-w-2xl border-collapse text-sm">
          <caption className="sr-only">
            Metrics before and after the alignment guard, under identical evaluation inputs
          </caption>
          <thead>
            <tr className="border-b border-ink text-left">
              <th scope="col" className="py-2 pr-3 font-semibold">Metric</th>
              <th scope="col" className="py-2 pr-3 text-right font-semibold">Committed</th>
              <th scope="col" className="py-2 pr-3 text-right font-semibold">With the fix</th>
              <th scope="col" className="py-2 text-right font-semibold">Delta</th>
            </tr>
          </thead>
          <tbody>
            {[
              ['Capped recall@12', '22.1%', '18.7%', '\u22123.4 pp', 'worse'],
              ['Reached the scorer', '32.1%', '32.1%', 'unchanged', 'flat'],
              ['Unwanted rate', '26.9%', '42.5%', '+15.6 pp', 'worse'],
              ['Planted-needle recall', '60.0%', '45.0%', '\u221215.0 pp', 'worse'],
              ['Lookalike rate', '15.0%', '25.0%', '+10.0 pp', 'worse'],
              ['World-critical delivery', '25.0%', '10.0%', '\u221215.0 pp', 'worse'],
              ['Model calls', '44', '84', '+40', 'flat'],
            ].map(([metric, before, after, delta, tone]) => (
              <tr key={metric} className="border-b border-sepia">
                <th scope="row" className="py-2 pr-3 text-left font-normal">{metric}</th>
                <td className="py-2 pr-3 text-right tabular-nums text-ink-60">{before}</td>
                <td className="py-2 pr-3 text-right tabular-nums">{after}</td>
                <td className={`py-2 text-right tabular-nums ${tone === 'worse' ? 'text-danger' : 'text-ink-60'}`}>
                  {delta}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="m-0 max-w-2xl text-sm text-ink-60">
          <em>Reached the scorer</em> is the control: the fix touches scoring, not retrieval, and
          retrieval is unchanged exactly as it should be.
        </p>

        <Aside>
          That table is not &ldquo;the fix made the product worse&rdquo;. It is two facts at once.
          The committed numbers were inflated by misattribution — 22.1% was never a measurement
          of the pipeline judging correctly, because it included verdicts that landed on the right
          article by accident. And refusing to guess is currently expensive, because on a mismatch
          the guard discards all forty verdicts, so those candidates carry no relevance signal at
          all. That is why the unwanted rate climbs: with no signal, nothing is filtering unwanted
          stories out. Neither number describes a healthy pipeline. The first is meaningless; the
          second is the honest price of having no way to salvage a partial response — which is
          precisely what article ids would buy.
        </Aside>

        <h3 className="meta-caps m-0 mt-4 text-ink-60">What this does to CI, stated plainly</h3>
        <p className="body-reading m-0 max-w-2xl">
          The regression gate goes from <span className="font-mono text-xs">42 passed, 59 subtests
          passed</span> to <span className="font-mono text-xs">6 failed, 53 subtests passed</span>.
          <strong> The baseline was deliberately not re-recorded.</strong> The gate is correctly
          reporting that behaviour changed materially; re-recording it to get a green badge would
          destroy the only evidence that the change had a cost. Re-baselining in this repository
          requires reviewed promotion evidence, which is a separate gated step — and
          &ldquo;the badge is green&rdquo; is not that evidence.
        </p>
      </Section>

      <Section n="6" title="What remains true">
        <ul className="m-0 flex list-disc flex-col gap-2 pl-6 text-sm">
          <li>
            The production scorer still sends no article ids, so a response that is the{' '}
            <em>right length</em> but internally reordered would still be misapplied. The guard
            catches count mismatches, which is what the evidence showed, not every possible
            misalignment.
          </li>
          <li>
            Still no output cap and no{' '}
            <code className="font-mono text-xs">finish_reason</code> check on this path. Both
            belong with the prompt change.
          </li>
          <li>
            The stored scorecards on this site were executed at a revision that is{' '}
            <strong>not reachable from the default branch</strong>, and none of them records an
            evaluation protocol. They are evidence about that historical run, not about the code
            shipping today. Every run in the explorer carries this caveat.
          </li>
          <li>
            The regression gate&rsquo;s prototype tier runs a historical legacy adapter, so the
            corrected default prototype pipeline is not exercised by the committed suite at all.
          </li>
        </ul>
      </Section>

      <Section n="7" title="How the pieces fit">
        <p className="body-reading m-0 max-w-2xl">
          Daily is an iPhone app against a FastAPI backend and Postgres. The backend is a stateful
          process: its startup path launches seven background loops — ingestion, prewarm, source
          quality, interest evolution, per-user refresh, account maintenance, ranking refresh —
          applies schema, and elects a leader with a Postgres advisory lock. That is a daemon, and
          it stays where it runs today.
        </p>
        <p className="body-reading m-0 max-w-2xl">
          This site is a separate read tier. It does not reimplement ranking: the reader demo
          replays a dated frozen corpus, and the evaluation explorer renders immutable artifacts
          exported from the harness&rsquo;s own scorecards. Nothing on this site scores an article.
        </p>
        <dl className="m-0 grid gap-x-6 gap-y-4 text-sm sm:grid-cols-2">
          <Boundary term="Web tier">
            Next.js on Vercel. Server components read validated artifacts; public results are
            immutable and cached; no personalized response is ever shared between users.
          </Boundary>
          <Boundary term="Artifacts">
            A versioned, validated export with explicit provenance. Three revisions are kept apart:
            the one that executed an evaluation, the one that stores the scorecard, and the one that
            built the artifact.
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
      </Section>
    </div>
  )
}

function Section({ n, title, children }: { n: string; title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-4 border-t border-sepia pt-8 first:border-0 first:pt-0">
      <h2 className="m-0 flex items-baseline gap-3">
        <span className="signature-caps text-ochre">{n}</span>
        <span className="row-headline text-xl">{title}</span>
      </h2>
      {children}
    </section>
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
    <li className="border-l-2 border-danger pl-4">
      <p className="row-headline m-0">{title}</p>
      <p className="dek m-0 mt-1 text-ink-60">&ldquo;{reason}&rdquo;</p>
      <p className="m-0 mt-1.5 text-xs text-ink-60">
        fixture <span className="font-mono">{persona}</span> · dropped at{' '}
        <span className="font-mono">{stage}</span>
        {needle === true ? ' · planted needle' : ''} ·{' '}
        <Link
          href={explorerHref(
            { run: RUN },
            { persona, view: 'stories', story, outcome: 'all' },
          )}
          className="text-ink-blue underline"
        >
          open this story&rsquo;s recorded trace
        </Link>
      </p>
    </li>
  )
}

function Code({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} className="font-mono text-xs text-ink-blue underline" rel="noreferrer">
      {children}
    </a>
  )
}

function Aside({ children }: { children: React.ReactNode }) {
  return (
    <p className="m-0 max-w-2xl border-l-2 border-ochre pl-4 text-sm text-ink-60">{children}</p>
  )
}

function Boundary({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="meta-caps m-0 text-ink-60">{term}</dt>
      <dd className="m-0 mt-1">{children}</dd>
    </div>
  )
}
