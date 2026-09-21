# Vercel integration plan — 2026-09-21

**Context.** Written to answer "what is the best way to integrate Vercel heavily in this
project", in service of a Vercel job application. The brief is deliberately re-read as:
*what does this repository actually need that Vercel is the right answer to?* A checklist of
twelve products wired in for display would be the wrong deliverable — this repository's whole
character is that claims trace to evidence, and a reviewer who reads `README.md` and then finds
a bolt-on will trust the rest of it less.

## The finding that reframes the brief

Every remaining gate in this project is blocked on readers that do not exist.

| Evidence | Source |
|---|---|
| Never shipped to the App Store | `README.md:426` "Not released" |
| Zero `/feed/*` requests, ever, in the log window checked | `docs/architecture/bulletproof-architecture-plan.md:505` |
| 3 accounts, 0 real learning events | `docs/notes/plan.md` S10 section |
| S10 Tier 1/2 need ≥20 events per reader-intent pair and ≥1,000 receipted impressions from ≥50 accounts | `docs/stages/s10-implementation-plan.md` |
| Eval labels have no human review; absolute values provisional | `README.md:415` |
| S6/S7 activation gated on production evidence there is no traffic to produce | `docs/architecture/bulletproof-architecture-plan.md:500` |

The pipeline is built. The ruler is built. The thing missing is **readers**, and the App Store
is the bottleneck. A web edition on Vercel is the only path to readers that does not require
App Store review — which makes Vercel the *unblock* for S7 serving, S10 Tier 1/2, and human
eval labels, not a line on a résumé.

That is also the strongest possible thing to say in the application: *"I put it on Vercel
because my own activation gates required traffic I had no way to get."*

## Second finding: the best asset in the repo is invisible

`backend/evals/` produces rich, committed, dashboard-ready JSON — and nothing renders it.

- 9 committed scorecards in `backend/evals/results/` (620 KB total), schema per
  `metrics.py:179`: `summary`, `per_persona`, `cache_keys`, `meta`.
- Per persona: `recall_at_k`, `recall_at_retrieval`, `never_rate`, `judge_precision`,
  `needle_recall`, `cost_usd`, plus the three funnel shapes — `stage_counts` (survivorship),
  `loss_by_stage` (must-see attribution), `drop_counts` (all-article attrition with
  sub-reasons), and `losses[]` with the model's own rejection text per lost story.
- `compare.py:33` already defines the metric polarity map and a ±0.02 significance threshold
  a dashboard can reuse directly.
- **The gap:** CI calls `evaluate(..., write=False)`, so no scorecard file is ever emitted.
  There are no `upload-artifact` or `$GITHUB_STEP_SUMMARY` steps in
  `.github/workflows/backend-tests.yml`. The only history is one git SHA, `47edb50`.
  The markdown tables in `backend/evals/README.md:127` have already drifted from the JSON
  (README says recall@12 `0.23`, `docs/notes/session-summary-2026-09-02.md:40` says `0.28`,
  the JSON says `0.2297`).

A public evidence dashboard plus a nightly run is therefore both the most differentiated
portfolio artifact available here and a fix for a real documented gap.

## Third finding: the #1 technical bottleneck is a database compute limit

S6 retrieval — the project's own stated top bottleneck — completes ~2 calls in 6 before hitting
its 2-second deadline. Root cause confirmed by `pg_buffercache` inspection, not guessed:
the production Supabase free tier gives Postgres 224 MB of `shared_buffers`, not enough to hold
the ~123 MB lexical working set (`articles` + GIN index) cache-resident
(`docs/architecture/bulletproof-architecture-plan.md:490`,
`docs/stages/s6-lexical-cache-limitation.md`). The documented complete fix is a paid compute
upgrade, deliberately deferred.

Staging already runs **Neon** successfully — pg 16.15 + pgvector 0.8.0, and the ~100-statement
DDL bootstrap completes on Neon's pooled endpoint
(`docs/architecture/bulletproof-architecture-plan.md:609,647`). So Neon through the Vercel
Marketplace is not a speculative migration; it is a rehearsed one.

## Fourth finding: the live path has no cost accounting

`feed_service.py:56` — `EST_COST_PER_SCORING_CALL_USD = 0.002`, commented "an estimate for the
build log, not a bill". Feed scoring, chat, `/briefing`, `/chat/interests`,
`/sources/discover`, embeddings, Gemini image generation, Tavily and Unsplash have **zero**
token accounting. Only the S3/S4/S5/S7 pipelines have real reserve/settle ledgers.

AI Gateway supplies exactly what is missing, on exactly the path that lacks it — and for the
main OpenAI path it is an environment variable, not a code change: the installed `openai`
1.12.0 already reads `OPENAI_BASE_URL` (`openai/_client.py:107`).

## What must NOT move to Vercel, and why

Stated first, because getting this wrong is the failure mode that would make the whole exercise
read as cargo-culting.

`lifespan()` at `backend/app/main.py:525` starts **seven** infinite loops — ingestion,
prewarm, account maintenance, source quality, interest evolution, per-user refresh, S7 refresh
— plus ~500 lines of inline DDL in `_ensure_tables` (`main.py:1027`), `pg_prewarm` setup, and
`pg_try_advisory_lock` leader election. That is a stateful daemon. Vercel runs Python well on
Fluid Compute and FastAPI deploys with zero config, but a seven-loop daemon with advisory-lock
leader election is still not a function, and moving it would trade a working system for a
demo.

The honest split:

| Component | Target | Why |
|---|---|---|
| Web frontend, evidence dashboard, article permalinks, OG images | **Vercel** | Greenfield; no web surface exists today |
| One domain fronting the API (`rewrites` → Fly) | **Vercel** | `AppConfig.swift:22` is a single constant; one-line client change |
| Nightly offline eval run | **Vercel Cron + Python Function** | `EVAL_OFFLINE=1` needs no DB and no API key; ~16 s, $0 |
| Scheduled loops (source quality, interest evolution, account maintenance) | **Vercel Cron, one at a time** | They are sleep-then-work loops — cron in disguise |
| `_prewarm_loop`, advisory-lock leader election, ingestion daemon | **Stays on Fly** | Needs a warm pooled connection and a stable process identity |
| Production Postgres | **Neon via Vercel Marketplace** | Fixes the documented S6 `shared_buffers` blocker; branching per preview |

Migrate the loops behind the same evidence gates the repository already uses for stages. Do not
flag-flip on faith.

## Build plan

### Tier 1 — the product and the showpiece

- [ ] **1.1** `web/` — Next.js 16 App Router, deployed on Vercel. Tailwind config transcribed
      directly from `docs/DESIGN.md:21` colour tokens and `:43` type scale, so the web surface
      is the same design system rather than a second one. Note `Daily/Theme/AppTheme.swift:19`
      has already drifted from `DESIGN.md` — transcribe from the doc, and file the drift.
- [ ] **1.2** `/evidence` — the eval dashboard. Server Components reading the 9 committed
      scorecards. Renders the mean/min metric table with `compare.py:33` polarity, the
      per-persona funnel from `stage_counts`, the `loss_by_stage` attribution, and `losses[]`
      with each story's own rejection reason — including the S7 batch-misalignment artefact
      (`README.md:118`), whose `losses[]` rows carry text like "discusses a music EP" against
      a flood-warning headline. Showing a bug in your own product, in the model's own words,
      is the most credible thing that could go on the site.
- [ ] **1.3** `/a/[id]` article permalinks + `next/og` OG images using the
      `SEP 21 · SARAH EDITION` masthead. Today `ArticleDetailView.swift:201` shares the
      *publisher's* URL because Daily has nowhere to land. Needs: an
      `/.well-known/apple-app-site-association` route (trivial on Vercel), a
      `CODE_SIGN_ENTITLEMENTS` associated-domains entry (none exists today), and an
      `onOpenURL` branch in `DailyApp.swift:65`, which currently only handles Google Sign-In.
- [ ] **1.4** `/` — the live web edition. This is the traffic instrument. Requires
      `CORS_ORIGINS` set on the Fly app (`main.py:612` — off by default, "no web clients").
- [ ] **1.5** `vercel.ts` (`@vercel/config`, the current recommendation over `vercel.json`)
      with `routes.rewrite('/api/(.*)', 'https://daily-backend.fly.dev/$1')`, cache-control
      headers, and the cron entries from 2.4.

### Tier 2 — platform depth, each justified by a documented gap

- [ ] **2.1** **Neon via Vercel Marketplace.** Migrate production off Supabase free tier and
      right-size compute to hold the 123 MB lexical working set. Re-run the S6 shadow
      measurement and publish before/after — the honest close of a deferred fix. Reuse
      `backend/scripts/provision_staging.sh` preflight (Postgres ≥16, `CREATE EXTENSION vector`).
- [ ] **2.2** **Neon branch per preview deployment.** Every PR gets its own database branch, its
      own preview URL, and its own eval run posted as a comment. This is the repository's
      "ruler" thesis expressed as platform-native CI, and it is the single most
      Vercel-flavoured idea in this document.
- [ ] **2.3** **AI Gateway.** Set `OPENAI_BASE_URL` for the SDK path (zero code change), then
      three `API_ROOT` constants — `understanding_provider.py:37`, `ranking_provider.py:25`,
      `event_provider.py:23`. Each provider hard-allowlists model IDs and prices and fails
      closed (`understanding_provider.py:253`, `ranking_provider.py:204`,
      `event_provider.py:78`), so also loosen those allowlists and `MODEL_PRICES`. Keep the
      reserve/settle ledgers — Gateway observability *reconciles* them, it does not replace
      them. Fold in Gemini (`image_generation_service.py:64`) for one cost surface.
- [ ] **2.4** **Cron + Blob + `updateTag`.** Nightly `EVAL_OFFLINE=1 python -m evals.run
      --all-snapshots` as a Python Function, scorecards to Blob, `updateTag('evidence')` to
      revalidate the dashboard. Closes the "CI emits no scorecard" gap and gives the dashboard
      a real time series instead of one SHA.
- [ ] **2.5** **Edge Config + Flags SDK** for the S3–S10 stage gates. Today they are env vars
      in `backend/.env.example` requiring a redeploy to flip. Edge Config gives instant flips
      and an audit trail while preserving fail-closed semantics. Philosophically this is the
      closest fit of any Vercel product to this repository's existing doctrine.

### Tier 3 — cheap, thematically apt

- [ ] **3.1** Vercel Agent PR reviews, on a repository whose culture is adversarial audits.
- [ ] **3.2** BotID + WAF on the API domain.
- [ ] **3.3** Rolling Releases for stage activation — the ship-dark doctrine as a platform feature.
- [ ] **3.4** Web Analytics + Speed Insights. `README.md:428` notes it has no screenshots;
      real Core Web Vitals is a better answer than screenshots.

### Tier 4 — the application artifact

- [ ] **4.1** `docs/architecture/vercel-migration.md` — what moved, what did not, and why, with
      before/after numbers. The "what did not" section is the part that demonstrates judgment.
- [ ] **4.2** Set the public repo's `homepageUrl` (currently empty) to the live deployment.

## If only one thing gets built

**Tier 1.2 plus Tier 2.4** — the evidence dashboard and the nightly cron behind it.

It is uniquely this project's (nobody else applying has a feed-quality ruler), it is genuinely
data-dense Next.js rather than a landing page, it fixes a real documented gap, it runs at $0
because the LLM cache replays offline, and it makes the single best claim in the README
clickable instead of asserted.

## Blockers

- `vercel whoami` reports no credentials. A device-code flow was started and not completed;
  this session cannot complete OAuth.
- The `plugin:vercel:vercel` MCP server is unauthorized — needs `claude mcp` or `/mcp` in an
  interactive session.
- `CORS_ORIGINS` is unset on the Fly app, so no web client can call the API yet
  (`main.py:611-620`).
