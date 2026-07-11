<div align="center">

# Daily

**Your own daily edition — a personalized news app that reads like a magazine that knows you.**

*iOS ([SwiftUI](https://developer.apple.com/xcode/swiftui/)) front end + a Python ([FastAPI](https://fastapi.tiangolo.com/)) intelligence engine that ingests the open web, understands each article, and ranks a feed around who you actually are — steered by conversation, not toggles.*

<br/>

![iOS](https://img.shields.io/badge/iOS-17%2B-000000?logo=apple&logoColor=white)
![Swift](https://img.shields.io/badge/Swift-SwiftUI-F05138?logo=swift&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![Postgres](https://img.shields.io/badge/Postgres-pgvector-4169E1?logo=postgresql&logoColor=white)
![OpenAI](https://img.shields.io/badge/OpenAI-embeddings%20%2B%20chat-412991?logo=openai&logoColor=white)
![Fly.io](https://img.shields.io/badge/Deploy-Fly.io-8B5CF6)

</div>

---

## The idea

Most news apps ask you to pick from a wall of category checkboxes and then bury the one story you cared about under ten you didn't. Daily inverts that.

You **talk** to it. During onboarding you have a short conversation — *"I run a small design studio, I follow AI tooling and typography, I couldn't care less about crypto"* — and Daily builds a profile from your own words. Behind the scenes it discovers credible sources for those interests, pulls their feeds, reads every article in full, embeds them, and ranks a feed that looks like a hand-set magazine edition with your name on the masthead: `JUL 11 · SARAH EDITION`.

Then it keeps learning. A **Tune** chat lets you nudge the feed in plain language — *"more on the design side, less product-launch noise"* — and the feed visibly re-sorts in front of you. What you open, how long you read, and what you save quietly sharpen the model over time. No scoring numbers, no "because you read X" receipts, no dark-pattern engagement bait. The personalization is felt, not exposed.

## Why it's interesting

- **Conversation is the control surface.** Onboarding and the Tune panel turn natural language into a structured interest profile and re-rank the feed — no settings grid, no manual source management.
- **Full-article understanding, not headline matching.** The backend extracts clean body text ([Trafilatura](https://trafilatura.readthedocs.io/)), enriches it, and embeds it with `text-embedding-3-small`, so ranking and semantic search work on what an article *says*, not just its title.
- **Autonomous source discovery.** Give it an interest and it finds and quality-scores real publications for it, seeds their feeds, and starts ingesting — you never paste an RSS URL.
- **An editorial design system, not a card wall.** One signature element per surface, a warm ink-and-ochre palette, provenance shown only when it's rare and certain. See [`DESIGN.md`](DESIGN.md).
- **Batch-first and cost-aware.** A background worker does ingestion, extraction, embedding, and enrichment on a loop; user requests read from pre-built, cached feeds instead of hitting an LLM in the hot path.

## Architecture

```
┌──────────────────────────┐        ┌───────────────────────────┐        ┌────────────────────────┐
│  iPhone — Daily (SwiftUI) │        │   Backend — FastAPI       │        │  Postgres + pgvector   │
│                           │        │   (Fly.io, iad)           │        │                        │
│  Onboarding chat  ─────────►  /user/preferences, /chat        │        │  users, sessions       │
│  Feed (hero + rows) ◄───────  /feed, /feed/build, /briefing   │◄──────►│  user_preferences      │
│  Tune chat        ─────────►  /chat/threads/*/stream (SSE)    │        │  articles (+embedding) │
│  Semantic search  ─────────►  /search/semantic                │        │  user_sources          │
│  Reading + saves  ─────────►  /reading-events, /feed/feedback │        │  reading_events        │
│  Sign in w/ Google/Apple ──►  /auth/google, /auth/apple       │        │  briefing/feed caches  │
└──────────────────────────┘        └─────────────┬─────────────┘        └────────────────────────┘
                                                   │
                                     ┌─────────────▼─────────────┐   Background ingestion loop
                                     │  RSS + topic feeds        │   (runs continuously):
                                     │  Trafilatura extraction   │   fetch → extract → embed →
                                     │  OpenAI embed + enrich    │   enrich → rank → cache
                                     │  Source discovery/scoring │
                                     │  Tavily search · Gemini/  │
                                     │  Unsplash imagery         │
                                     └───────────────────────────┘
```

**The closed loop:** you describe yourself → the engine finds sources and reads the web → a ranked edition is built → you read, save, and Tune → your signals feed back into the next edition.

## Repo layout

```
Daily/                         SwiftUI iPhone app (the one you build & run)
├── DailyApp.swift             App entry, background URLSession bridge, Google Sign-In config
├── AppConfig.swift            Single source of truth for the backend URL
├── ContentView.swift          Root routing (auth → onboarding → main tabs)
├── Features/
│   ├── Auth/                  Sign in with Google / Apple
│   ├── Chat/                  Onboarding conversation that builds your profile
│   ├── News/                  Feed, article reader, search, bookmarks, profile, settings
│   │   ├── Views/Components/  HeroStory, StoryRow, BriefingCard, EditionHeader, ProvenanceLine…
│   │   └── ViewModels/        NewsViewModel, PersonalizationSettingsViewModel
│   └── Tune/                  Live feed-tuning chat (DiffToast, LiveFeedPeek, TuneComposer…)
├── Services/                  BackendService, BackgroundNewsFetcher, Bookmark/ImageCache/Haptic,
│                              ReadingEventTracker, Authentication
├── Models/                    Shared data models
└── Theme/                     AppTheme — the ink+ochre editorial design tokens

backend/                       FastAPI intelligence engine (deployed to Fly.io)
├── app/main.py                API surface + background ingestion loop + schema bootstrap
├── app/services/
│   ├── news_ingestion.py      RSS + topic feed fetching
│   ├── content_extractor.py   Full-text extraction (Trafilatura)
│   ├── article_enrichment.py  Summaries, metadata, entity enrichment
│   ├── source_discovery.py    Finds + seeds credible sources for an interest
│   ├── source_quality.py      Scores source reliability
│   ├── feed_service.py        Per-user ranking + feed assembly
│   ├── interest_evolution.py  Learns from reading behavior over time
│   ├── profile_model.py       User profile v2 derivation + normalization
│   ├── openai_service.py      Chat + embeddings (gpt-4o-mini, text-embedding-3-small)
│   ├── chat_service.py        Onboarding / Tune conversation logic (SSE streaming)
│   ├── image_generation_service.py  Gemini imagery · image_extraction.py · web_search_service.py (Tavily)
│   └── …
├── Dockerfile · fly.toml      Container + Fly.io deploy config
└── requirements.txt

scripts/setup.sh               Workspace bootstrap (syncs env/config, sets up venv)
tasks/                         Design system + execution plans (DESIGN.md is the visual source of truth)
```

## Tech stack

| Layer | Choices |
|---|---|
| **iOS** | SwiftUI (iOS 17+), `@Observable` state, async/await, background `URLSession` fetch, Google Sign-In, Sign in with Apple |
| **Backend** | FastAPI, `psycopg` + connection pool, server-sent events for streaming chat, background asyncio ingestion worker |
| **Data** | PostgreSQL + `pgvector` for embeddings and semantic search |
| **AI / content** | OpenAI (`gpt-4o-mini` chat, `text-embedding-3-small` embeddings), Trafilatura extraction, Tavily web search, Gemini + Unsplash imagery |
| **Auth** | Google & Apple ID-token verification against provider JWKS, server-issued session tokens |
| **Infra** | Docker, Fly.io (`iad`), HTTPS-forced with health checks (`/healthz`, `/readyz`) |

## API surface (selected)

| Method & path | Purpose |
|---|---|
| `POST /auth/google`, `POST /auth/apple` | Verify a provider ID token, create/return a session |
| `GET /me` | Current user + profile |
| `POST /user/preferences`, `/user/preferences/complete` | Save onboarding-derived interests / finish onboarding |
| `POST /chat`, `POST /chat/threads/{id}/messages/stream` | Onboarding + Tune conversations (streamed) |
| `POST /sources/discover`, `GET /sources` | Discover & list personalized sources |
| `POST /feed/build`, `GET /feed`, `POST /feed/refresh` | Build and read the ranked edition |
| `GET /briefing` | A short daily briefing |
| `POST /search/semantic` | Vector search over ingested articles |
| `POST /reading-events`, `POST /feed/feedback` | Behavioral signals that sharpen ranking |
| `GET/POST/DELETE /entities`, `GET /interests/suggestions` | Pinned entities + proactive interest suggestions |

Interactive docs are served at `/docs` (Swagger) when the backend is running.

## Local setup

### Backend

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # then fill in the values below
uvicorn app.main:app --reload --port 8080
```

Configure `backend/.env` (never commit it — it's gitignored):

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | ✅ | Postgres with the `pgvector` extension enabled |
| `OPENAI_API_KEY` | ✅ | Chat + embeddings |
| `OPENAI_MODEL` | | Defaults to `gpt-4o-mini` |
| `OPENAI_SCORING_MODEL` | | Optional separate model for ranking |
| `ADMIN_API_KEY` | | Guards `/admin/*` diagnostics |
| `TAVILY_API_KEY` | | Web search enrichment |
| `GEMINI_API_KEY`, `UNSPLASH_ACCESS_KEY` | | Article imagery |
| `CORS_ORIGINS`, `ENVIRONMENT` | | Deployment tuning |

The app bootstraps its own schema on startup and starts the ingestion worker automatically.

### iOS app

1. Open `Daily.xcodeproj` in Xcode (iOS 17+ SDK).
2. Sign the target with your team + a unique bundle ID.
3. For Google Sign-In, drop in your own `GoogleService-Info.plist` (the checked-in one carries only the public OAuth client ID).
4. Point the app at your backend — either edit `AppConfig.swift` or set the `DAILY_BACKEND_URL` Info.plist key. It defaults to the hosted backend.
5. Build & run on a simulator or device.

## Deployment

The backend ships as a container to **Fly.io**:

```bash
cd backend
fly deploy                    # uses Dockerfile + fly.toml
fly secrets set OPENAI_API_KEY=... DATABASE_URL=...   # secrets live in Fly, not in git
```

`fly.toml` forces HTTPS, keeps at least one machine warm, and health-checks `/healthz` every 15s.

## How a story reaches your feed

1. **You describe yourself** in the onboarding chat; the backend derives a structured interest profile.
2. **Source discovery** finds and quality-scores credible publications for those interests and seeds their feeds.
3. **The ingestion worker** fetches new articles, extracts full body text, generates embeddings, and enriches metadata — continuously, in the background.
4. **Feed build** ranks candidates against your profile and behavior and caches a ready-to-serve edition.
5. **You read it** as a hero-plus-rows magazine layout; opens, dwell time, and saves are recorded.
6. **You Tune it** in natural language; the feed re-sorts live and an ephemeral diff toast shows what changed.
7. **Interest evolution** folds those signals back into your profile so tomorrow's edition is sharper.

## What's intentionally out of scope

- **No manual source management.** You don't paste RSS URLs or curate a source list — discovery does it.
- **No exposed scoring.** Match scores, ranking internals, and "why you saw this" plumbing are never surfaced as UI; provenance appears only when it's rare and high-confidence.
- **No real-time LLM in the hot path.** Personalization is batch-first; the feed you open is pre-built and cached to keep it fast and cost-efficient.
- **Localhost-optional by design.** The app targets a hosted production backend; running locally is for development, not a required setup step.

## Security & privacy notes

- Secrets live in `backend/.env` (gitignored) and in Fly.io secrets — never in the repository.
- The committed `GoogleService-Info.plist` contains only the **public** OAuth client identifier, which is embedded in every app binary anyway; it is not a secret.
- Auth relies on verifying Apple/Google ID tokens against their published JWKS before issuing a session.
- Responses set HSTS and standard security headers; the backend enforces HTTPS at the edge.

## License

No license file is currently included; treat this as **all rights reserved** unless a `LICENSE` is added.

---

<div align="center">
<sub>Built with SwiftUI, FastAPI, Postgres/pgvector, and OpenAI. Designed as an edition, not a feed.</sub>
</div>
