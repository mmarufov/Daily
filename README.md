<div align="center">

# Daily

### News that knows you.

An iOS news app that builds you a personal daily edition — and a backend that can prove
whether it actually got better.

[![backend tests + eval gate](https://github.com/mmarufov/Daily/actions/workflows/backend-tests.yml/badge.svg)](https://github.com/mmarufov/Daily/actions/workflows/backend-tests.yml)
![iOS 26+](https://img.shields.io/badge/iOS-26%2B-000000?logo=apple&logoColor=white)
![Swift](https://img.shields.io/badge/SwiftUI-F05138?logo=swift&logoColor=white)
![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![Postgres + pgvector](https://img.shields.io/badge/Postgres-pgvector-4169E1?logo=postgresql&logoColor=white)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

</div>

---

## The idea

Most news apps hand you a wall of category checkboxes and then bury the one story you
cared about under ten you didn't. Daily inverts that.

You **talk** to it. During onboarding you have a short conversation — *"I run a small
design studio, I follow AI tooling and typography, I couldn't care less about crypto"* —
and Daily builds a profile out of your own words. Behind the scenes it discovers credible
publications for those interests, pulls their feeds, works out what each story is actually
about, and assembles a feed that reads like a hand-set magazine with your name on the
masthead: `SEP 14 · SARAH EDITION`.

A **Tune** chat is meant to let you steer in plain language — *"more on the design side,
less product-launch noise."* The conversation surface is built; the backend event that
would re-sort the feed live is not, so today Tune answers questions rather than changing
what you see. That gap is named honestly in [Known gaps](#known-gaps) rather than papered
over here.

What the design does commit to: no match scores, no "because you read X" receipts, no
engagement bait. The personalization is meant to be felt, not displayed.

## Status: working product, partially activated pipeline

Daily is a real deployed app, not a prototype — but it is mid-rebuild, and the README
would be useless if it pretended otherwise.

There are two different questions, and they have two different answers:

|  | State |
|---|---|
| **Is it built?** | The full ten-stage pipeline is implemented, contract-tested, and merged — 2,145 backend tests collected, 1,960 passing and 185 skipped without a database. |
| **Is it live for readers?** | Partly. Stages ship **dark**. Every new stage defaults to `false` in [`backend/.env.example`](backend/.env.example) and is turned on only after its own evidence gate passes. |

That gap is deliberate. Personalization that goes live because a default changed is how
you ship a feed nobody asked for. So each stage carries its own activation gate — a
schema migration, a measured threshold, a dollar budget, a quality review — and the
repository records what is still owed. Per-stage detail lives in
[`docs/architecture/systems.md`](docs/architecture/systems.md).

Feed quality **as measured today is not good enough**, and the numbers are published
below rather than buried. Fixing them is the current work.

## Measured, not claimed

The interesting part of this repository is not the app. It's that the app has a ruler.

Deciding which stories a person needs is a claim you can be *wrong* about, and "the feed
looks better to me" is not evidence — an earlier proxy metric in this project scored a
junk feed 14/14. So Daily carries an evaluation harness ([`backend/evals/`](backend/evals/),
"S0") built to answer one question: **did this change make the feed better or worse, and
if a story went missing, which stage lost it?**

How it works:

- **Frozen snapshots.** Three content-hashed corpora committed to the repository — a
  1,328-article baseline across 51 feeds, a 1,234-article quiet-day derivative with the
  major events pruned out, and a second 1,358-article live capture 50 hours later — so a
  run in October is comparable to a run in August.
- **Ten personas**, seven of them built through the *production* profile builder from real
  onboarding transcripts — including a cold start, an exclusion collision, and a reader
  with non-English-named interests.
- **Labelled ground truth.** ~350 pooled articles per persona per snapshot marked
  `must_see` / `fine` / `never`, with tags for the genuinely hard cases: `lookalike`
  (right word, wrong thing), `need_to_know`, `followup`, `exclusion_collision`.
- **Planted needles.** Two must-see articles and two lookalikes injected per persona at
  run time — an NJ Transit shutdown for Ray, with a *Newark, **Delaware*** story as the
  decoy — so the answer is known by construction rather than by opinion.
- **A committed response cache.** Every model call ever made is stored keyed by request
  hash, so `EVAL_OFFLINE=1` replays the entire evaluation with **no API key and no cost**.
  CI runs the regression gate this way on every pull request. A cache miss fails the build
  rather than quietly spending money.
- **The runner measures the real product.** `ProductionRunner` calls the actual
  `feed_service.get_personalized_feed`. It fakes only the database and freezes `now()`.
  The real recency window, prefilter, batch scorer, dedupe, and diversity pass all run
  unchanged.

### What it currently says

2026-08-31 snapshot · 10 personas · k = 12 · means across personas:

| Metric | Production (keyword fallback) | **Production (LLM scorer)** | Prototype pipeline |
|---|---|---|---|
| recall@12 on must-see stories | 0.18 | **0.23** | 0.41 |
| must-see stories that reached the scorer | 0.40 | **0.40** | 0.76 |
| need-to-know recall | 0.11 | **0.18** | 0.48 |
| never-rate in top 12 *(lower is better)* | 0.41 | **0.22** | 0.08 |
| world-critical event delivered | 0.20 | **0.20** | 0.55 |
| planted needles found | 0.35 | **0.55** | 0.70 |
| judge precision / recall | – | **0.59 / 0.56** | 0.84 / 0.69 |
| cost, all ten readers | $0 | **$0.14** | $0.035 |

Read two things from that table:

1. **Retrieval is the bottleneck, not ranking.** Only 40% of must-see stories ever reach
   the scorer. For one persona, 1,028 of 1,328 pool articles never got past the 300-row
   recency window, and 193 of the surviving 300 were cut by a 100-candidate cap. You
   cannot rank a story you never loaded.
2. **The scorer itself is leaking quality.** A judge precision of 0.59 traces to a
   real batching bug the harness caught: with no `max_tokens` and positional output,
   `gpt-4o-mini` looped — *"The article discusses a music festival…"* hundreds of times —
   until it hit the 16k output limit, blew the 45-second guard, and silently fell back to
   keyword scoring. Measured, cached, reproducible.

**Honest caveat.** Labels are model-generated, then reviewed by an independent agent
editorial pass with explicit `source=agent` provenance. Product-owner human review is
still outstanding, so treat absolute values as provisional. **Deltas between runs** are
what the CI gate actually enforces, and those are trustworthy. Full methodology and every
metric definition: [`backend/evals/README.md`](backend/evals/README.md).

## How it works

```
┌───────────────────────────┐         ┌──────────────────────────────┐        ┌────────────────────────┐
│  iPhone — Daily (SwiftUI) │         │  Backend — FastAPI (Fly.io)  │        │  Postgres + pgvector   │
│                           │         │                              │        │                        │
│  Onboarding chat  ────────┼────────▶│  /user/preferences  /chat    │        │  users, sessions       │
│  Feed (hero + rows) ◀─────┼─────────│  /feed  /feed/build          │◀──────▶│  user_preferences      │
│  Tune chat        ────────┼────────▶│  /chat/threads/*/stream (SSE)│        │  articles (+ embedding)│
│  Semantic search  ────────┼────────▶│  /search/semantic            │        │  user_sources          │
│  Reading + saves  ────────┼────────▶│  /reading-events  /feedback  │        │  reading_events        │
│  Google sign-in   ────────┼────────▶│  /auth/google                │        │  edition + feed caches │
└───────────────────────────┘         └───────────────┬──────────────┘        └────────────────────────┘
                                                      │
                                        ┌─────────────▼─────────────┐   Background worker, on a loop:
                                        │  RSS + topic feeds        │   fetch → extract → understand →
                                        │  Origin-only extraction   │   cluster → retrieve → rank →
                                        │  OpenAI embed + enrich    │   assemble → cache
                                        │  Source discovery/scoring │
                                        └───────────────────────────┘
```

**The intended closed loop:** you describe yourself → the engine finds sources and reads
them → a ranked edition is built in the background → you read and save → those signals
feed the next edition. Every arrow is implemented. The last one is not yet *earning* its
keep: signal capture works, but the learning it feeds is inert until S7 serves.

What the loop does already guarantee is that no model call sits in the request path. The
edition you open was built in the background and cached. Latency and cost are treated as
features, not afterthoughts.

## The ten stages

The backend is built as a chain of numbered stages, each with one job, a typed contract at
its edges, its own tests, and its own definition of done. They were built in order,
because hardening stage 7 against a moving stage 3 is wasted work.

| Stage | Job | State in the repository |
|---|---|---|
| **S0** [Evaluation](backend/evals/README.md) | Tell you whether a change helped or hurt | Framework complete; product quality gates not yet met |
| **S1** [Sources & ingestion](docs/stages/s1-ingestion-audit.md) | Poll feeds politely, land each article exactly once | Phase 0 shipped; unified registry + conditional poller pending |
| **S2** [Content](docs/stages/s2-content-pipeline-audit.md) | Turn a URL into something readable — or admit it can't | Complete in repo; production rollout pending |
| **S3** [Understanding](docs/stages/s3-implementation-status.md) | Describe what each article's evidence supports, once | Guarded runtime implemented; quality validation pending |
| **S4** [Events](docs/stages/s4-implementation-status.md) | Notice what everyone should know, and how much it matters | Guarded runtime + eval tooling; hosted lifecycle pending |
| **S5** [Reader model](docs/stages/s5-implementation-status.md) | Hold what this person wants, in a queryable form | Lexical path implemented and enabled in production; semantic half still off |
| **S6** [Retrieval](docs/stages/s6-implementation-status.md) | Narrow the pool to a few hundred real candidates | Complete in repo; running in **shadow**, not serving |
| **S7** [Ranking](docs/stages/s7-implementation-status.md) | Judge relevance — accept, reject, or abstain — then order | Complete in repo; running in **shadow**, not serving |
| **S8** [Assembly](docs/stages/s8-implementation-status.md) | Turn a ranking into a non-repetitive edition | Complete in repo; activation gated |
| **S9** [Delivery](docs/stages/s9-implementation-status.md) | Get it on screen fast; make reading feel good | Verified in repo; rollout and budgets pending |
| **S10** [Learning](docs/stages/s10-implementation-status.md) | Notice what the reader does, change what comes next | Tier 0 verified; Tier 1/2 not started |

Each stage has three documents, written in this order: an **audit** that attacks the
existing design and states what is genuinely broken, an **implementation plan** that
commits to a fix, and a **status** file recording what landed and what is still owed. The
audits are deliberately unflattering — they exist so decisions trace to evidence rather
than to taste. Index: [`docs/`](docs/).

## The web companion

`web/` is a read-only web tier on Next.js: a reader demo that replays a dated frozen edition, an
interactive explorer for the evaluation results below, and one worked debugging case study. It
reimplements no ranking — nothing there scores an article — and it runs with no credentials,
no database and no provider key, because the exported artifacts are committed.

It is also where the evaluation stops being a JSON file nobody reads. The explorer selects a run,
a corpus, a pipeline and a reader fixture into a shareable URL; refuses to draw improvement arrows
between runs that are not comparable; reconstructs the candidate funnel correctly (the harness
records terminal stages, not survivors); and follows a single story down to the stage that lost it.

Setup, the artifact provenance rules, the CI publication model, and what the site is careful never
to claim: [`web/README.md`](web/README.md).

## Repository layout

```
Daily/                          SwiftUI iPhone app — 65 files, ~12k lines
├── DailyApp.swift              App entry, background URLSession bridge, Google Sign-In
├── AppConfig.swift             Single source of truth for the backend URL
├── ContentView.swift           Root routing: auth → onboarding → tabs
├── Features/
│   ├── Auth/                   Sign in with Google / Apple
│   ├── Chat/                   Onboarding conversation that builds your profile
│   ├── News/                   Feed, reader, search, bookmarks, profile, settings
│   │   └── Views/Components/   HeroStory, StoryRow, BriefingCard, EditionHeader…
│   └── Tune/                   Live feed-tuning chat (DiffToast, LiveFeedPeek…)
├── Services/                   BackendService, BackgroundNewsFetcher, ReadingEventTracker
├── Models/                     Shared data models
└── Theme/                      AppTheme — the ink-and-ochre editorial design tokens

backend/                        FastAPI intelligence engine — 66 modules, ~27k lines
├── app/main.py                 37 endpoints + background worker + schema bootstrap
├── app/services/               65 modules, one per concern:
│   ├── news_ingestion.py         RSS + topic feed fetching
│   ├── safe_http.py              Redirect/DNS/size/type-bounded outbound fetching
│   ├── content_extractor.py      Bounded, origin-only extraction (Trafilatura)
│   ├── article_content.py        Versioned artifacts, source policy, leased jobs
│   ├── understanding_*.py        S3 — what each article is
│   ├── event_*.py                S4 — clustering stories into events by gravity
│   ├── reader_*.py               S5 — the durable reader model
│   ├── retrieval_*.py            S6 — candidate retrieval
│   ├── ranking_*.py              S7 — relevance judgment
│   ├── assembly_*.py             S8 — edition assembly
│   ├── source_discovery.py       Finds and seeds credible sources for an interest
│   └── *_schema.sql              7 additive schema files, applied at boot
├── evals/                      S0 — the evaluation harness (see its own README)
├── tests/                      90 files, 822 test functions
├── scripts/                    Operational tooling; dry-run unless --apply
└── Dockerfile · fly.toml       Container + Fly.io deploy config

docs/                           40 documents, ~12k lines — audits, plans, design system
```

## Tech stack

| Layer | Choices |
|---|---|
| **iOS** | SwiftUI (iOS 26 deployment target), `@Observable` state, async/await, background `URLSession`, Google Sign-In |
| **Backend** | FastAPI, `psycopg` with a connection pool, server-sent events for streaming chat, an asyncio background worker |
| **Data** | PostgreSQL + `pgvector` for embeddings and semantic search |
| **AI** | OpenAI — `gpt-4o-mini` for chat and scoring, `text-embedding-3-small` for embeddings; Tavily-assisted source discovery |
| **Auth** | Google ID tokens verified against Google's JWKS, then server-issued session tokens. An Apple endpoint exists server-side; the iOS client does not call it yet. |
| **Infra** | Docker, Fly.io (`iad`), HTTPS forced at the edge, `/healthz` checked every 15s |

## Getting started

### Backend

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env      # fill in DATABASE_URL and OPENAI_API_KEY
uvicorn app.main:app --reload --port 8080
```

The backend bootstraps its own schema on startup and launches the ingestion worker
automatically. Interactive API docs are served at `/docs` **only when `ENVIRONMENT` is not
`production`** — which it defaults to, so set `ENVIRONMENT=development` locally if you
want Swagger.

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | ✅ | Postgres with the `pgvector` extension enabled |
| `OPENAI_API_KEY` | ✅ | Chat, scoring, and embeddings |
| `OPENAI_MODEL` | | Defaults to `gpt-4o-mini` |
| `OPENAI_SCORING_MODEL` | | Optional separate model for ranking |
| `ADMIN_API_KEY` | | Guards the `/admin/*` diagnostics endpoints |
| `TAVILY_API_KEY` | | Source discovery and analysis |
| `UNSPLASH_ACCESS_KEY`, `GEMINI_API_KEY` | | Article imagery |
| `S3_*` … `S8_*` | | Per-stage activation gates. All default to `false` — see the comments in `.env.example` for what each one requires first. |

### iOS app

1. Open `Daily.xcodeproj` in Xcode 26+ (the project sets an iOS 26.0 deployment
   target in all four build configurations).
2. Sign the target with your own team and a unique bundle ID.
3. For Google Sign-In, drop in your own `GoogleService-Info.plist`. The checked-in one
   carries only the public OAuth client identifier, which ships inside every app binary.
4. Point the app at your backend — edit `AppConfig.swift` or set the `DAILY_BACKEND_URL`
   key in `Info.plist`. It defaults to the hosted backend.
5. Build and run.

## Tests

```bash
cd backend
EVAL_OFFLINE=1 python -m pytest tests/ -q                  # 822 test functions
EVAL_OFFLINE=1 python -m pytest tests/test_eval_gate.py    # the feed-quality gate
```

Current local result: **1,960 passed, 185 skipped** in about 105 seconds. The skips are
the Postgres contract suites, which need a live database — CI supplies one.

CI ([`.github/workflows/backend-tests.yml`](.github/workflows/backend-tests.yml)) is
stricter than a plain `pytest` run in two ways worth copying:

- **Offline enforcement.** Everything runs with `EVAL_OFFLINE=1`, so a test that would
  reach the network fails instead of costing money and returning a different answer.
- **Skips are failures.** After each stage's suite, CI parses the JUnit XML and asserts
  that every required module actually executed and that nothing was skipped. A suite that
  silently stops collecting is the most expensive kind of green build.

A second job runs the transaction contracts against a disposable
`pgvector/pgvector:0.8.0-pg16` service and verifies the extension version before starting.

The iOS test target has 150 test functions but does **not** run in CI — the Xcode project
has no shared scheme, so `xcodebuild` can't drive it from a clean checkout. That's a known
gap, listed below.

## API surface

37 endpoints. The ones that matter:

| Method & path | Purpose |
|---|---|
| `POST /auth/google` | Verify a Google ID token, open a session (the iOS sign-in path) |
| `POST /auth/apple` | Apple ID-token verification — implemented server-side, not yet wired into the app |
| `DELETE /auth/session`, `/auth/sessions` | Revoke this session, or every session |
| `GET /me` | Current user and profile |
| `POST /user/preferences`, `/user/preferences/complete` | Save onboarding interests, finish onboarding |
| `POST /chat`, `POST /chat/threads/{id}/messages/stream` | Onboarding and Tune conversations (SSE) |
| `POST /sources/discover`, `GET /sources` | Discover and list personalized sources |
| `POST /feed/build`, `GET /feed`, `POST /feed/refresh` | Build and read the ranked edition |
| `GET /feed/{article_id}` | Article detail through the typed reader contract |
| `GET /briefing` | A short daily briefing — server-side only; no iOS surface calls it yet |
| `POST /search/semantic` | Vector search across ingested articles |
| `POST /reading-events`, `POST /feed/feedback` | Behavioural signals that sharpen ranking |
| `GET/POST/DELETE /entities`, `GET /interests/suggestions` | Pinned entities, proactive suggestions |
| `DELETE /user/account` | Account deletion |
| `GET /healthz`, `GET /readyz` | Liveness and readiness |

## Deployment

The backend ships as a container to Fly.io, staging first:

```bash
cd backend
fly deploy --config fly.staging.toml       # staging: provision, smoke, then promote
fly deploy                                 # production: daily-backend, iad
fly secrets set OPENAI_API_KEY=… DATABASE_URL=…
```

Secrets live in Fly, never in git. Production runs one always-warm
`shared-cpu-2x` / 1 GB machine in `iad` with HTTPS forced at the edge and `/healthz`
checked every 15 seconds. `backend/scripts/provision_staging.sh` and `smoke_staging.sh`
handle staging setup and verification.

Staging exists because of a specific lesson: the production deploy of Phase 7 surfaced two
bugs that no test could have caught — logging was never configured, so every
`logger.info` had been a silent no-op, and a `CREATE INDEX` race showed up only under a
real concurrent boot.

## Design

[`docs/DESIGN.md`](docs/DESIGN.md) is the visual source of truth, and the SwiftUI
components cite it by name. The rules that shape the app:

- **One signature element per surface.** A screen gets one thing that carries its
  identity — the hero story on the feed, the masthead on the edition header — and
  everything else stays quiet.
- **Ink and ochre.** A warm editorial palette, serif headlines, small-caps ochre labels.
  It should read like print, not like a dashboard.
- **Hero plus rows, never a card wall.** Cards flatten hierarchy. An edition has a lead
  story, and the layout should say so.
- **Provenance only when rare and certain.** A source line appears when it's genuinely
  informative, never as decoration.
- **Motion is specified, not improvised.** The Tune diff toast slides in over 200ms,
  holds 2000ms, fades over 300ms. Written down so it stays consistent.

## What's deliberately out of scope

- **No manual source management.** You never paste an RSS URL. Discovery does it, or it
  isn't worth doing.
- **No exposed scoring.** Match percentages, ranking internals, and "why you saw this"
  plumbing never reach the UI.
- **No model call in the hot path.** Personalization is batch-first. The edition you open
  is pre-built and cached.
- **No republishing.** Every publisher defaults to `source_only` and opens at its
  canonical page. Native full text requires a human-reviewed source policy plus a
  complete, identity-matched, versioned artifact. Text found elsewhere on the web can
  inform ranking but is never served as a publisher body.

## Security and privacy

- Secrets live in `backend/.env` (gitignored) and in Fly secrets. Never in the repository.
- The committed `GoogleService-Info.plist` holds only the **public** OAuth client
  identifier, which is already inside every copy of the app binary. It is not a secret.
- Google ID tokens are verified against Google's published JWKS before any session token
  is issued. The Apple path is implemented server-side and not yet used by the client.
- `safe_http.py` bounds redirects, DNS resolution, response size, and content type on
  every outbound request, so a hostile feed can't turn the ingester into an SSRF probe.
- Operational scripts read the database URL only from the environment and change nothing
  without an explicit `--apply`.
- Behavioural events expire with the article they describe: effective retention is
  `article.ingested_at + 14 days`, not 14 days from the tap. A deliberate choice, and a
  documented one (`backend/app/services/retention.py`).

Full policy, including how to report a vulnerability:
[`.github/SECURITY.md`](.github/SECURITY.md).

## Known gaps

Listed because a README that only lists wins isn't information.

- **Feed quality is not where it needs to be.** recall@12 of 0.23 in production, against a
  target of 0.8. Retrieval loses most must-see stories before ranking ever sees them;
  closing that is what S6 and S7 exist for.
- **The global-pool join gate.** The feed query inner-joins `article_source_links`, and
  only the per-user ingestion path ever writes rows there — so articles from the shared
  pool are unreachable by a personalized feed. It is tracked as a live bug, not a surprise
  ([bug #5](docs/architecture/bulletproof-architecture-plan.md)).
- **S6 and S7 are in shadow, not serving.** They compute a ranking and log what they would
  have done; the feed a reader opens still comes from the older path. S6's first real
  production observations complete roughly two calls in six before hitting a 2-second
  deadline — the lexical working set doesn't fit the database tier's cache. Diagnosed, and
  the fix is deliberately deferred.
- **Tune can't change the feed yet.** The chat, the diff toast, and the undo pill are all
  built client-side, but the backend never emits the `weight_diff` event they wait on, so
  Tune is currently a read-only surface.
- **Eval labels have no human review.** They are model-generated with an independent agent
  editorial pass and honest `source=agent` provenance. That makes run-to-run deltas
  trustworthy and absolute values provisional. It also means judge precision is partly
  circular: a `gpt-4o-mini` scorer measured against ground truth written by `gpt-4.1`.
- **The absolute quality targets are not enforced in CI.** The gate checks no-regression
  against a committed baseline. The absolute floors (`recall@12 ≥ 0.8`,
  `never_rate ≤ 0.05`) only run under `EVAL_GATE_STRICT=1`, which CI does not set, because
  production does not meet them.
- **iOS tests don't run in CI.** 150 test functions and no shared Xcode scheme, so
  `xcodebuild` can't drive them from a clean checkout. The backend has strict no-skip CI;
  the app has none. That asymmetry is the biggest structural hole here.
- **Not released.** The app has never shipped to the App Store, so none of the above has
  met real readers at volume.
- **No screenshots in this README.** The most obvious thing missing for a visual app.

## Documentation

| Path | What's there |
|---|---|
| [`docs/`](docs/) | Index of everything below |
| [`docs/architecture/systems.md`](docs/architecture/systems.md) | The best single overview — the app as ten systems |
| [`docs/DESIGN.md`](docs/DESIGN.md) | The design system |
| [`docs/stages/`](docs/stages/) | Per-stage audits, plans, and honest status |
| [`backend/evals/README.md`](backend/evals/README.md) | How feed quality is measured |
| [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) | Setup, conventions, and what a PR needs |
| [`AGENTS.md`](AGENTS.md) | House style, also read by coding agents |

## License

Copyright © 2026 Muhammadjon Marufov.

Released under the [GNU Affero General Public License v3.0](LICENSE). In short: you may
read, run, modify, and redistribute this code, but if you run a modified version as a
network service, you have to publish your source too.

---

<div align="center">
<sub>SwiftUI · FastAPI · Postgres/pgvector · OpenAI — designed as an edition, not a feed.</sub>
</div>
