# S9 — Delivery implementation plan

Date: 2026-09-09. **Implementation approved; repository work verified 2026-09-10, not activated.**
See [implementation status](s9-implementation-status.md) for refinements and remaining release gates.
Basis: [source-backed audit](s9-delivery-audit.md). This plan covers delivery, not changes
to what S6 retrieves, what S7 judges or how S8 selects and orders an edition.

## Outcome and scope

A returning reader sees their last eligible saved edition quickly, with its real age.
Revalidation replaces it only with a current authorized result. Empty, stale, offline,
building, rejected-session and reader-review states are distinct. Opening a story promptly
shows permitted native text or the original publisher, with honest fallback behavior.

Keep SwiftUI, FastAPI, PostgreSQL, URLSession, SFSafariViewController and S2–S8 contracts.
No paid model in the feed/detail read path. No new Redis, CDN for personalized JSON, APNs,
web scraper, durable mobile job framework, ranking model or wholesale app rewrite.
Preserve the existing editorial visual design; change layouts where readability requires it.

Implementation authorization would cover repository changes and offline verification only.
Hosted SQL, migration execution, provider spend, source-policy approval, deployment and
feature activation remain separate owner-approved operations. Do not run a localhost server.

## Ownership and invariants

```text
S7/S8 atomic publication + fresh authorization
                 |
       versioned delivery envelope
                 |
 Auth session -> NewsViewModel (single delivery coordinator) <- foreground / refresh intents
                 |                       |
    account-owned ArticleCacheStore      UI state + immutable ordered cards
                 |                       |
        saved edition/body lease         reader + viewport image requests
```

Refactor `NewsViewModel` to own delivery rather than introducing a competing coordinator.
Evolve `ArticleCacheStore` into the serialized async persistence boundary. Keep the existing
reader model and image service, improving their interfaces. Small value types/helpers are
fine; no service per status. Retain legacy observation wrappers where changing them would
only add churn. Root ownership and injected dependencies matter more than wrapper names.

Required invariants:

1. Account ownership, session epoch and local request intent are checked before every UI
   publication and disk mutation. A → sign-out → A is a new session, not the same request owner.
2. A later accepted publication cannot be replaced by an older one. Reader generation/revision
   are not edition sequence numbers. S8 request IDs and original positions remain immutable.
3. `ready([])` is an authoritative empty edition. Missing/corrupt cache, unavailable and
   building are not empty editions. Unknown wire states never become ready implicitly.
4. Saved metadata, fresh ranking authority, critical-event expiry and native-body permission
   have separate lifetimes. Reading the cache, retrying or foregrounding renews none of them.
5. Known hard exclusions/revocations apply immediately; soft learning feedback is not a ban.
   Expired critical cards cannot retain urgency, reserved-slot priority or live authorization.
6. Sign-out is a write barrier: late requests/saves cannot recreate cleared account data.
7. No network, full-body decode, all-image prefetch or optional related search blocks the
   first metadata frame. No automatic paid-build retry loop is added.

## A — Backend delivery envelope and failure contract

Files: `ranking_service.py`, `ranking_repository.py`, `ranking_schema.sql`, relevant
`assembly_integration.py`, `main.py`, `feed_service.py`; matching backend tests and management
schema checks. Swift decoding in `BackendService.swift` and a small delivery value model.

- Add a negotiated delivery contract independently of existing S8 edition receipt capability.
  Preserve version-1 clients; require explicit capability for new semantics. Do not silently
  activate S4 or S7/S8. Test default-off/legacy and enabled paths separately.
- The ready envelope carries: contract version, immutable edition/request ID, reader
  generation/revision, publication sequence, publication time, server validation time,
  original validity deadline, personalization status/reason, and ordered article cards.
  Keep request ID semantics consistent with existing receipt records.
- Allocate the publication sequence inside the existing successful publication transaction,
  using a durable per-account counter. It must survive result expiry/cleanup and never advance
  on a cached read or failed publication. Retain the current locking/CAS order and receipt
  transaction. Counter reset is permitted only with account deletion; expose no global traffic
  counter. Use a checked integer representation supported by Python/SQL/Swift.
- Same reader identity + higher sequence replaces; same sequence must have identical
  immutable edition content. Validation timestamps may advance after a fresh fence; the
  ranking validity deadline may not. Reject same-sequence content changes. New reader identity
  is installed through an explicit reader transition, never by blindly sorting tuples.
- Distinguish legitimate missing/stale edition from backend unavailable/busy, reader review,
  auth rejection and unsupported-client responses. Add bounded retry guidance and a reason
  enum; never expose SQL errors or model prose as UI status text.
- Return `Cache-Control: private, no-store` for personalized feed/detail responses in this
  phase. App-owned offline persistence is explicit and separate from HTTP caching. Skip ETags
  initially: a later conditional read must still run auth/current policy checks before 304.
- Reuse bounded DB execution for detail and its auth lookup, with connection ownership wholly
  inside the worker. Measure pool wait, validation, hydration, serialization and bytes. Keep
  GET provider-free and preserve S3/S5/S6/S8 freshness checks on every current delivery.
- Include a bounded native offline-use deadline in the new detail contract only where source
  policy permits it. It cannot exceed the configured S2 cap or a shorter policy limit.
  Without an explicit usable deadline, fall back to metadata/source on offline cold restore.

Acceptance: wire fixtures decode on both sides; duplicate/out-of-order publications are
rejected; empty is preserved; outage never masquerades as `needs_build`; GET makes zero
provider calls; existing stale-policy/recipe/evidence tests remain green. Real PostgreSQL
tests must prove publication sequence, rollback and concurrent publish behavior before rollout.

## B — Account-owned storage and saved-edition launch

Files: `BackgroundNewsFetcher.swift`/`ArticleCacheStore`, `AuthService.swift`, `ContentView.swift`,
`MainTabView.swift`, `BookmarkService.swift`; cache/auth tests and new persistence tests.

- Replace feed-array persistence with a versioned envelope. Return explicit missing, corrupt,
  saved and authoritative-empty results. Store local receive time separately from server time.
  Use the existing account namespace plus an owner binding inside the decoded envelope.
- Move bounded JSON/file I/O away from the main actor. Use one serialized owner for feed,
  native-body reconciliation and cleanup. Atomic protected files suit one small edition and
  bounded bodies; a database is not required for this scope. Preserve the public S2 cache
  invariants while replacing UserDefaults as the multi-megabyte body store.
- Store disposable caches under the account-owned cache directory, excluded from backup and
  recoverable on eviction. Store durable bookmark metadata separately in account-owned
  Application Support, with an explicit backup/file-protection policy. Handle device-locked
  file access as unavailable, never as an empty overwrite. Do not describe OS protection as
  application-level end-to-end encryption.
- Keep at most one saved edition per account, initially 7 days/100 cards/2 MB metadata.
  Native cache retains the current 12 entries/1 MB body maximum and **at most** 24 hours, also
  bounded by the server's policy deadline; cap aggregate storage and prune expired files.
  These are proposed product limits, not performance results. Saving a bookmark stores
  metadata only and does not grant permanent offline full text.
- Serialize bookmark/read-ID saves with the same account lifecycle guarantees. Capture
  ownership and revision before scheduling; reject stale writes and serialize deletion
  after invalidation. Atomic writes alone are insufficient. Fence late image tasks too.
- Migrate old account-scoped feed metadata as an explicitly unverified saved snapshot, not
  a current edition. Never guess the owner of legacy global bookmarks or carry unbounded
  native text forward. Preserve recoverable legacy files until ownership can be established;
  do not import them automatically into a newly logged-in account.
- Add a local saved-account presentation state distinct from server-authenticated state.
  Only the last successfully verified account with a secure owner marker is eligible.
  Show cached content while a bounded restore runs; network failure retains read-only saved
  access. No authenticated requests, chat, preference mutations, builds or attributed event
  submission are authorized by this state. Allow a clear reconnect/sign-in action.
- Explicit sign-out, credential persistence failure, account replacement, 401/403 and known
  hard invalidation remove saved access and close sensitive navigation. Ensure bootstrap and
  cleanup finish before another account can load its stores. Unknown prior identity shows no cache.
- Do not trust a rolled-back device clock to extend native grants. Compare server time and
  elapsed time within a process; fail closed on suspicious clock changes across launches.

Acceptance: cold offline launch with/without a verified owner; warm offline; token rejected;
credential write failure; A → B → A; sign-out during queued writes; reverse-order bookmark
saves; corrupt/truncated/oversized cache; missing protected files; process restart; metadata
retention expiry and native permission expiry. No stale writer can repopulate another account.

## C — One feed state machine and bounded refresh

Files: `NewsViewModel.swift`, `BackendService.swift`, `NewsView.swift`, `DailyApp.swift`,
`MainTabView.swift`, relevant feedback integration; new injected coordinator tests.

- Represent content state separately from refresh progress: no edition, saved, current,
  authoritative empty, reader review, signed out. Refresh can be idle, validating, building
  or temporarily failed without deleting eligible saved content.
- Route startup, pull-to-refresh, foreground activation, preference acknowledgments and any
  background completion through one reconciliation function. Inject transport, cache, auth
  snapshot and clock so races can be tested deterministically.
- Coalesce repeated refreshes; cancel superseded requests and setup flows. Retain a task only
  when it belongs to the coordinator's lifetime. Guard every await boundary, error/defer
  mutation and final cache/UI publication with the captured operation token.
- Use separate fast-read and explicit-build network budgets. Initial targets: feed GET
  5-second request/8-second resource deadline, `waitsForConnectivity=false`; an explicit build
  gets a bounded overall budget aligned with the existing backend deadline (initially 30 seconds
  client-side). The visible timeout must cancel client work, not merely hide an overlay.
  First-time discovery remains a separate setup state, not a blocking refresh of an existing feed.
- A true cache miss may trigger the existing one-time setup/build policy. An outage must not.
  For a confirmed in-progress build, foreground-only GET rechecks can use 2/4/8-second delays,
  at most three attempts, then an explicit retry action. Never repeat paid POSTs automatically.
- Revalidate on `.active` when stale, coalescing scene transitions. Do not depend on the dormant
  background POST. Retire that request starter; preserve any required completion-handler
  cleanup for OS-restored legacy transfers without accepting their obsolete payloads.
- Known hard source exclusions remove all matching source cards and invalidate saved membership
  using canonical source IDs. If the client lacks enough identity to apply them safely, mark
  the edition unusable pending a valid refresh. Acknowledged review-required states prevent
  old saved personalization from resurfacing. Keep soft feedback semantics unchanged.
- Show the edition's publication date, last verified time and a saved/offline label. Use a
  separate “last checked” label where useful. Remove unsupported “tightly on-topic” status copy.
  Bind optional briefing content to the same edition, or hide it when that binding is absent.
- Never sort/filter and then regenerate S8 receipt positions. Archived impressions are not
  fresh delivery receipts. Strip expired S4 authority in the display projection; keep any
  still-eligible ordinary article only through an explicit ordinary fallback rule. Advertise
  S4 expiry capability only after its foreground expiry handling is integrated and tested.

Acceptance: newer response before older; new edition during disk save; authoritative empty
through every path; user hides source then restarts offline; reader change during build;
cancel during discovery; duplicate refresh; busy/unavailable/malformed/429/review states;
briefing from old edition; app inactive past expiry; expiry without a network response.

## D — Reader lifecycle and honest source fallback

Files: `ArticleReaderModel.swift`, `ArticleDetailView.swift`, `NewsArticle+Reader.swift`,
`BackendService.swift`, existing routing/Safari views and reader tests.

- Pass a session-bound load context and cached-body permission envelope, not just a token
  and article. Validate before publishing ready content, not only before the caller stores it.
- Immediately display a compatible unexpired saved body with a saved/revalidating indicator.
  Refresh asynchronously when authorized. Network failure does not renew the grant. Missing
  body shows preview/source promptly while a bounded detail request runs.
- Reconcile active readers on foreground, account change, current contract downgrade and
  permission expiry. Auth rejection or authoritative revocation clears native presentation
  and cache; preserve only permitted metadata/source actions. Same-account relogin cannot
  accept a response from the old session. Persistence rejection must inform display acceptance.
- Version canonical metadata alongside the detail artifact. A legitimate newer publisher
  correction can update the reader title/body together after identity/provenance validation;
  it cannot rewrite the immutable feed edition or attribute a different body to its receipt.
  Preserve the S8 exact-body hash requirement for native-read novelty.
- Keep one-tap source Safari routing and available original-source actions. Source paywalls,
  missing connectivity and publisher failure are not native-body failures to “repair” with
  analysis text. Show explicit unavailable/offline/retry/sign-in states where Daily owns the UI.
- Make related semantic search explicitly user-triggered for this phase and fence/cancel it.
  Do not add automatic provider work merely because someone opens a materialized article.
- Preserve scroll position during revalidation; prepare text once per body version. Keep
  dynamic text scaling, selection and language-appropriate wrapping with safe long-token
  handling. Test long bodies before choosing one TextKit view versus paragraph components.

Acceptance: immediate valid saved body; expired/mismatched cache; cached body plus 401/403;
source downgrade during read; old response after relogin; correction during read; no native
body under a foreign publisher; invalid/missing URL; cancellation and retry; no automatic
embedding call on open; exact original receipt/body attribution remains intact.

## E — Viewport work, images, accessibility and delivery signals

Files: `NewsView.swift`, `HeroStory.swift`, `StoryRow.swift`, `ImageCacheService.swift`,
`ArticleBodyTextView.swift`, relevant theme/routing components and `ReadingEventTracker.swift`.

- Put individual feed rows directly in a lazy container with stable article identity.
  Keep optional header/briefing and hero independent; avoid rebuilding the whole edition for
  an image or bookmark change. Preserve current selection/order and scroll anchor on refresh.
- Share one explicit image loader between cards and prefetch. Start with at most four active
  requests and only visible plus a small near-viewport window; coalesce duplicates and cancel
  obsolete work. Use URLSession/URLCache for HTTP, cost-bounded NSCache for decoded thumbnails,
  and ImageIO for target-size downsampling. Cache keys include URL and rendering size/scale.
- Validate status, MIME and image decode; cap streamed bytes before buffering the whole image,
  reject unreasonable dimensions and avoid decoding all animated frames. Initial limits:
  5 MB compressed image, 40 MP input, 32 MB decoded cache; tune only against measurements.
  Respect HTTP freshness rather than blindly treating an existing cached response as valid.
  Do not mutate `URLCache.shared`. Clear account-derived image activity and cancel pending
  prefetch on sign-out; images never carry bearer tokens to publisher hosts.
- Use current SwiftUI primitives compatible with the checked iOS 26.0 deployment target.
  At accessibility sizes, remove rigid headline/source truncation and reposition or omit
  decorative thumbnails. Test VoiceOver reading order, accessible feedback actions, text
  selection, Reduce Motion, dark mode, contrast and RTL. Replace “selected” with an accurate
  opened/read accessibility value; do not equate a tap with completed reading.
- Measure actual card visibility for impressions with a documented threshold (initially
  at least 50% visible for one continuous second while active). Track native-body active
  display intervals, excluding loading/background/source sheets. Reuse bounded S8 receipts
  and queue ownership; S10 remains responsible for learning weights and behavioral models.

Acceptance: duplicate image URLs, scrolling cancellation, late completion after logout,
404/HTML/oversized/decompression-heavy images, missing image, memory pressure, 100 cards,
long headlines, largest accessibility size, VoiceOver feedback, RTL/unbroken tokens,
offscreen rows produce no impressions, and background time produces no native read duration.

## F — Proof, measurement and controlled release

Add deterministic tests as each phase lands, not a separate optional cleanup at the end.
Use existing URLProtocol/fake-provider/cache fixtures, clocks and suspended completions.
No new paid evaluation is necessary to establish delivery-state correctness.

| Layer | Required evidence |
| --- | --- |
| Pure contracts and reducer | Invalid envelopes, sequence monotonicity, every status transition, source exclusions and expired authority |
| Persistence/auth | Restart and migration; account swap; suspended writes released after sign-out; partial/corrupt/oversized files |
| Backend integration | Fresh fences on every read; zero provider calls; bounded pool/lock failure; capability compatibility; SQL sequence rollback/concurrency |
| Reader/image tests | Provenance, deadlines, cached permissions, cancellation, limits, response ordering and no automatic related embeddings |
| Simulator UI | Cold saved launch, reconnect, empty, retry, review, source fallback, large text and accurate date/status |
| Physical device + release backend | Measured launch/scroll/reader budgets, accessibility, slow/offline network and authorized deployed-build canaries |

Proposed targets, **not current measured results**:

| Measurement boundary | Initial acceptance target |
| --- | --- |
| Warm saved metadata available → first usable feed frame | p95 ≤ 300 ms |
| Cold launch → saved feed frame with locally verified owner, no network dependency | p95 ≤ 1 second |
| Authorized foreground feed GET, 50 cards/300 candidate evidence set, controlled backend load | p95 ≤ 1 second; no bypass of evidence checks to hit it |
| Reader tap → metadata/source action | p95 ≤ 200 ms |
| Reader tap → eligible locally saved native body | p95 ≤ 500 ms |
| Network failure → usable saved/retry state | No longer than the explicit request deadline; saved content stays interactive throughout |

Instrument first metadata frame separately from hero image, network-current edition and
complete native body. Define the minimum supported physical iPhone, Release build, fixture
sizes, cold/warm cache, thermal/network state and sample count before benchmarking. Capture
at least 30 runs per launch scenario and publish distributions, not one best run. Measure
scroll hitches with Instruments rather than inferring speed from lazy syntax. The simulator
unit run is not performance evidence.

Add privacy-safe signposts and backend phase timings with random correlation IDs. Do not log
tokens, raw user identity, article text, private interests or full publisher URLs. Record cache
age, status/reason, payload bytes, stale-response rejection, cancellation and first-frame time.
Cross-stage publish-to-visible latency is a separate S1–S9 observation, not a guaranteed
five-minute S9 SLA for closed/offline apps.

Release order: backward-compatible schema/API capability first; iOS consuming that capability
second; activate only after matching deployed versions and no-skip SQL/device gates are
verified. Keep existing S7/S8 serving controls default-off until separately approved. Rollback
must disable the new delivery capability safely and retain labeled metadata-only saved access,
never restore expired critical authority or legacy native content. Test migration and rollback
compatibility before touching hosted state.

## Recommended implementation sequence

- [x] A: wire contract, publication ordering, failure semantics and provider-free bounded reads.
- [x] B: serialized account storage, cleanup barriers and saved-account shell.
- [x] C: one coordinator, authoritative empty/policy invalidation and foreground refresh.
- [x] D: immediate permitted reader cache, lifecycle revalidation and source fallback.
- [x] E: bounded images, lazy/adaptive views and exposure instrumentation.
- [x] F: combined offline regression and documented remaining live gates.
- [ ] Release measurement: physical-device budgets/accessibility, no-skip SQL and deployed canaries.

Do A–C before visual optimization: optimizing the wrong/stale edition is not progress.
Keep each phase independently testable. No phase is called “bulletproof” on unit tests alone.

## References checked for this plan

- [Apple: background strategies](https://developer.apple.com/documentation/backgroundtasks/choosing-background-strategies-for-your-app): background scheduling is system-controlled, so refresh/push remain best-effort hints.
- [Apple: waitsForConnectivity](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/waitsforconnectivity): foreground requests can fail promptly without connectivity; background sessions always wait.
- [Apple: ImageIO thumbnails](https://developer.apple.com/documentation/imageio/cgimagesourcecreatethumbnailatindex(_:_:_:)): native downsampling API; no new image dependency is required for this bounded use.
- [Project-referenced SwiftUI async guidance](https://github.com/Dimillian/Skills/blob/main/swiftui-ui-patterns/references/async-state.md) and [performance guidance](https://github.com/Dimillian/Skills/blob/main/swiftui-ui-patterns/references/performance.md): narrow ownership, cancellation, stable identity and lazy rows inform the proposed refactor.

This document preserves the approved design. The implementation-status document records actual
scope refinements and verification; neither document is evidence of deployed behavior.
