# S9 — Delivery and reading: analyse and challenge

Date: 2026-09-09. Scope: current `mmarufov/sydney-v7` worktree, including uncommitted
S1–S8 and UI work. Repository analysis, not a deployed-system audit. No runtime edits,
provider calls, hosted SQL or deployment. Implementation is not yet authorized.

## Verdict

S9 is **partially implemented, with delivery-state and lifecycle gaps**. The main problem
is not the choice of SwiftUI or FastAPI. The client stores and displays article arrays
without owning the edition's freshness, identity and invalidation as one contract.

Example: a returning reader cold-launches offline. The token and cached feed survive,
but failed `/me` restoration sends them to sign-in. If they instead lose connectivity
after signing in, cached headlines can appear under today's date without any saved-edition
label. Faster downloads would not fix either behavior.

Keep the existing stack, S2 provenance boundary and S7/S8 authoritative order. Make the
delivery contract explicit, then optimize the measured critical path. Do not add a new
ranker, model, recommendation service, Redis, push system or custom web reader for S9.

## What already works and should survive

- S2 distinguishes `native_full_text`, `source_web` and `unavailable`. Native text requires
  verified provenance; source-only stories already open the publisher directly through
  item-based Safari presentation. The old system-map claim about a footer-only Reader is stale.
- `ArticleCacheStore` scopes feed/native caches by account; native entries have a 24-hour
  TTL, 12-entry/1-MB-per-body bounds, version checks and downgrade eviction. Authoritative
  empty writes invalidate feed membership for late detail insertion.
- Authentication already has a session generation, including A → B → A transitions.
  Foreground edition fetches check it. Reuse it for all delivery-side writers.
- S8 preserves request ID, reader generation/revision and immutable delivery position.
  Standalone bookmarks/detail caches strip feed receipts. S9 must not renumber receipts.
- S7 cached serving is provider-free and revalidates current eligibility. Do not remove
  those checks to make a benchmark look better.
- The typography theme uses semantic fonts; the native body uses `UIFontMetrics`.
  This is not a blanket fixed-font failure. Item-based navigation and stable article IDs exist.
- Bookmark creation from the reader strips the native body. Do not claim bookmarks currently
  provide permanent offline full text or bypass the native-body TTL through that call site.

## Findings

Severity is implementation priority, not a claim that every theoretical interleaving was
reproduced. “Source-confirmed” identifies the actual control flow; performance and race
outcomes still need the tests listed in the plan.

### F1 — Cold offline launch has no saved-reader route (high, source-confirmed)

`AuthService.resolveTransientRestoreFailure` clears `currentUser` and sets unauthenticated
while retaining credentials and their owner marker. `ContentView` then chooses `AuthView`;
`NewsViewModel.loadFeed` requires an authenticated current user before restoring the cache.
Warm-session fallback is not cold-launch offline support.

Recommendation: a separate, read-only saved-account presentation, based on the last
successfully verified owner. Never turn a cached token into proof of current server
authorization. Explicit sign-out, rejected sessions and account replacement must clear it.

### F2 — Feed cache has no edition envelope or truthful age (high, source-confirmed)

`BackgroundNewsFetcher.swift: ArticleCacheStore.loadFeed/storeFeed` persists `[NewsArticle]`
and a local fetch date, not the complete response. `NewsViewModel.applyReadyFeed:367`
discards response-level information and sets the date to local now. `NewsView.editionDateLabel:149`
always formats today. Metadata cache reads have no expiration decision.

The S7 public result includes reader identity and receipt information, but not a complete
published-at/valid-until/revalidated-at/ordered-publication contract. UUID request IDs are
identities, not sortable versions. Keeping old metadata for offline reading can be useful;
presenting it as a current personalized edition is the defect.

Recommendation: distinct current, saved/stale and hard-invalid states; explicit metadata
retention separate from ranking validity and native-content permission. A successful cache
read must not renew any server validity window.

### F3 — Empty updates and hard policy changes do not consistently reach the screen (high)

`NewsViewModel.restoreCachedFeed:386` returns when the cached list is empty, including the
`feedReady` replacement path. Thus a stored authoritative empty edition cannot clear a
previously displayed list through that observer. Foreground `applyReadyFeed([])` does clear
it: the two paths disagree. The background request starter is currently unused, so this is
a reachable helper/observer inconsistency, not evidence of a scheduled production refresh.

`submitFeedback:225` removes only the tapped article after `hide_source`; it neither removes
all matching publisher cards nor updates the stored edition. `needsReaderReview` clears
visible articles but does not consistently invalidate saved membership. Cached fallback can
therefore restore material the current UI has just rejected.

Recommendation: one reconciliation path; distinguish a missing cache from an authoritative
empty snapshot. Apply acknowledged hard exclusions to every current/saved surface using
canonical source identity. Do not turn soft `less_like_this` feedback into a hard ban.

### F4 — No single owner for request order, cancellation and cache publication (high)

`NewsViewModel` has load, force-refresh, setup, preference-notification and background
notification paths. It has useful session/reader-epoch checks, but no ordered edition
comparison shared with cache publication. A valid but older response can replace a newer
edition from another path. Preference changes cancel the build handle but not the current
foreground load. Legacy preference rebuilding can run outside the ordinary in-flight guard.

The setup timeout dismisses the overlay after 90 seconds; it does not cancel the underlying
request. `BackendService.feedSession` waits for connectivity and permits 300-second requests.
These are source-confirmed lifetime mismatches, not measured 300-second user waits.

Recommendation: make the existing feed model the single coordinator, inject its dependencies,
and use one operation token containing account session, reader epoch and request intent.
All response acceptance, UI publication and persistence must share that token and an ordered
server publication version. Cancellation is an ordinary state, not a user-facing error.

### F5 — Detached bookmark writes can outlive account cleanup (high, source-confirmed race)

`BookmarkService.saveBookmarks/saveReadIDs` capture snapshots in detached tasks and write
shared `Documents/bookmarks.json` / `read_articles.json`. `clearAll` deletes those files
without waiting for or invalidating outstanding writers. Atomic file replacement prevents
a torn file; it does not prevent stale writes or account mixing.

An old writer scheduled after cleanup can recreate a deleted file; concurrent saves can
finish in reverse order. Existing identity-cleanup tests do not prove these interleavings.
Recommendation: serialized account-owned persistence and generation-fenced writes, including
the cleanup barrier. Treat this as part of S9 delivery privacy, not an unrelated bookmark feature.

### F6 — Native reader validates content but not the complete display lifetime (high)

`ArticleReaderModel.load` publishes ready content before `ArticleDetailView.loadReaderContent`
checks the user. That caller checks user ID, not session generation. `fetchFeedArticle` lacks
the generation fence used by foreground edition requests. A same-account logout/login race
therefore needs explicit coverage before calling the display/cache lifecycle safe.

With a token present, compatible cached native content waits behind the network attempt
and appears only on eligible failure. Once the model has a verified body, subsequent `load`
returns early without revalidation. An in-memory body can therefore outlive the cache TTL
or a later authoritative downgrade unless another owner closes/reconciles the reader.

Recommendation: carry a bounded cached-body permission envelope into the reader, display
eligible saved text promptly, label it, and reconcile on foreground/revalidation/expiry.
Check the session and operation epoch before both display and persistence. Offline clients
cannot discover a remote revocation instantly; define that limitation rather than implying
that a 24-hour TTL is immediate revocation.

### F7 — Canonical detail corrections and optional related content need separate handling (medium)

`NewsArticle.mergingReaderDetail` intentionally retains the old title/summary while accepting
a newer body. That protects against metadata substitution, but a legitimate publisher
correction can leave a new body under an old title. Add a versioned canonical metadata rule;
do not simply trust arbitrary detail text or rewrite the S8 feed card/receipt in place.

`ArticleDetailView.loadRelatedArticles` invokes semantic search on every detail load.
`POST /search/semantic` generates a query embedding. This is optional reading enrichment,
not a requirement to deliver the materialized article. Its response also needs account and
task fences. Prefer explicit related-content loading for this phase, or reuse an already
materialized relation; do not add a new recommendation engine to remove one automatic call.

### F8 — Server delivery is more than an indexed SELECT (medium, source-confirmed)

`ranking_service.cached_feed:378` loads and validates the private ranking envelope, current
reader, candidate authorization, event dependencies and S8 membership. Work is bounded and
provider-free, but includes substantial parsing/SQL/locking. The old S9 description is false.

Its broad exception path returns `needs_build` for cache/database failures as well as true
missing/stale editions. The client interprets that status as a reason to start setup/build.
An outage can therefore trigger an inappropriate build attempt; this is not a claim that
the backend bypasses its existing spend controls.

`GET /feed/{id}` is `async`, but its awaited helper executes synchronous DB cursor work.
The route's authentication lookup is synchronous too. Audit the full DB lifetime when moving
this work into the existing bounded worker pattern; never hand one connection across awaits.

Recommendation: explicit unavailable/busy/stale/review outcomes, bounded DB execution,
private non-shared HTTP caching rules and per-phase measurements. Optimize redundant work
only after profiling, while preserving the fresh authorization fence.

### F9 — Image preloading has weak resource and cache ownership (medium)

`ImageCacheService` eagerly starts a task for every feed image. There is no application-level
concurrency cap, request coalescing, cancellation, byte/pixel bound or downsampling. Its
manual cache insertion checks neither HTTP success nor image type. It mutates global
`URLCache.shared`; cards use independent `AsyncImage` views. Shared reuse is assumed in a
comment, not demonstrated by a test. System networking still has its own limits; this is
not a claim of literally unlimited simultaneous sockets or that AsyncImage never caches.

Recommendation: one explicit image-loading path, bounded near-viewport work, decoded-image
cost limits and thumbnail downsampling. Images must never gate the first headline frame.
Publisher image requests disclose network activity; don't prefetch every article by default.

### F10 — Lazy layout, readability and interaction semantics need targeted work (medium)

`NewsView.feedContent:182` is an eager `VStack`, including another eager stack for all rows,
inside the outer lazy container. The outer container does not make the inner rows lazy.
`StoryRow` fixes thumbnails at 80 points, titles at two lines and source metadata at one line;
large accessibility sizes need an adaptive layout. Read cards use 0.6 opacity and the
accessibility “selected” trait, which is not the same as “opened”. Contrast failure has not
been measured, so do not claim one yet.

The body renderer already scales fonts, but disables text selection, forces character
wrapping and replaces attributed text on update. `nativeBody` prepares paragraphs inside
view construction. Measure long-text layout and support selection, normal word wrapping
with pathological-token fallback, RTL and accessible text sizes without discarding S2's
overflow protection. Feedback should have an accessible action, not only a long press.

### F11 — Background freshness and reading-quality promises exceed evidence (medium)

`startFeedRefresh` has no app call site; its legacy POST also omits the S8 capability header.
Reattaching a background URLSession is not scheduling periodic edition refresh. `DailyApp`
does not currently revalidate the edition on foreground activation. Add that before APNs.

Apple decides when background refresh and background pushes run; neither is a guaranteed
five-minute delivery clock. Publication-to-visible latency also includes S1–S8 and whether
the user has the app open. [Apple background strategies](https://developer.apple.com/documentation/backgroundtasks/choosing-background-strategies-for-your-app).

S7 currently emits `quality_met=false` even for its ordinary ready response; the client
turns this into “small ... tightly on-topic.” That explanation is not justified by the flag.
Use actual structured reasons. Source-web reading remains subject to connectivity,
publisher availability and access controls; Daily cannot promise offline full text for it.

### F12 — Existing tests do not establish on-screen performance or genuine exposure (medium)

Feed impressions use `onAppear`, not measured visibility. Detail dwell time covers the
view's lifetime rather than active native-body exposure. S8 receipt validity is necessary
but does not make these observations accurate. S9 should report visible/active intervals;
S10 owns how to learn from them. Source-web taps must not become proven native reads.

No delivery signpost/MetricKit/performance-test implementation was found in `Daily` or
`DailyTests`. Cold-launch, hitch, payload and image budgets need explicit measurement.

## Technology challenge

| Tempting approach | Recommendation and tradeoff |
| --- | --- |
| “Just shorten the cache TTL” | Add edition states first. Short TTL alone destroys offline usefulness and cannot enforce remote revocation while offline. |
| “Show every cached card instantly as current” | Show a labeled saved edition under a verified local owner; suppress expired urgency and enforce known hard exclusions. Slightly more state, truthful behavior. |
| “Use Redis/CDN to make personalized GET cheap” | Keep Postgres and current validation first. Profile the path; do not introduce a second invalidation authority or shared personalized cache. |
| “Add push to guarantee fresh news” | Foreground refresh is mandatory; push/BGAppRefresh are optional later hints, not correctness dependencies. |
| “Build a universal in-app scraper/reader” | Preserve S2 native-or-source routing. Delivery cannot manufacture publisher rights or bypass paywalls. |
| “Rewrite all state to Observation” | Reuse the existing feed model as coordinator. Modern ownership is useful; wholesale wrapper conversion is not an S9 requirement. |
| “Add an image library immediately” | First use URLSession, URLCache/NSCache and ImageIO behind one small owned interface. Reconsider a maintained library only if measured needs exceed bounded thumbnail loading. |

## Evidence collected in this audit

Executed, without a server or provider calls:

```text
backend/venv/bin/python -m pytest backend/tests/test_ranking_service.py \
  backend/tests/test_ranking_integration.py backend/tests/test_assembly_integration.py \
  backend/tests/test_article_content_contract.py -q
115 passed, 30 subtests passed in 0.37s

xcodebuild test -project Daily.xcodeproj -scheme Daily \
  -destination 'platform=iOS Simulator,id=4BABDD4D-FE3D-4642-9045-D07A85E6D4BC' \
  -parallel-testing-enabled NO -only-testing:DailyTests CODE_SIGNING_ALLOWED=NO -quiet
80 passed, 0 failed, 0 skipped (xcresult summary)
```

Result bundle: `/Users/mmarufov/Library/Developer/Xcode/DerivedData/Daily-hhybyatzshtarmcozjzzdtzdjxzp/Logs/Test/Test-Daily-2026.09.09_22-43-10--0700.xcresult`.

These are existing regression tests, not new reproductions of every finding. No physical-device
visual/accessibility audit, live load test, PostgreSQL suite, Release benchmark or deployment
validation was performed. The earlier S8 status still records unpassed rollout gates and
three pre-existing S0 quality failures; this focused run does not supersede that status.

Next: [S9 implementation plan](s9-implementation-plan.md).
