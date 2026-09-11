# S2 — Article content and reading audit

## Implementation closure — 2026-09-05

**Repository verdict: S2 implementation passes. Production verdict: not deployed yet.** The
2026-09-03 audit below is retained as the before-state and rationale; its 19 original repository
findings and five final iOS lifecycle findings have now been closed in code and negative-path
coverage. This does not turn an unreviewed feed into licensed content, and it does not claim the
currently deployed backend has changed.

The implemented boundary is now:

- Editorial selection never depends on republishing availability. Presentation resolves
  independently to `native_full_text`, `source_web`, or `unavailable`.
- `native_full_text` is default-deny and requires a current, article-owned artifact; validated
  identity and completeness; an explicit normalized rights basis; matching policy/content
  versions; and either an exact reviewed feed URL or a current same-origin extractor version.
- Publisher-feed, origin, legacy, and cross-source analysis text are separate versioned artifacts.
  Analysis remains available through private `_analysis_text` / `_analysis_summary` fields for
  every ranking consumer and is stripped at the API boundary.
- Acquisition is a durable leased state machine. Article registration, completion, and policy
  rematerialization share article-then-job lock order; stale worker versions cannot publish.
- Outbound origin and image fetches validate every redirect and resolved address, pin the validated
  transport address, block HTTPS downgrade/private networks, and bound hops, time, media type,
  encoding, decompression, and bytes.
- Fresh, cached, semantic, and detail reads use the same fail-closed serializer. Startup and
  `/readyz` reject a missing or incomplete S2 schema rather than serving ambiguous content.
- iOS routes source stories directly to item-based `SFSafariViewController`. Native text requires
  the typed provenance contract; online detail refresh can revoke it. The account-scoped offline
  cache is version-fenced, TTL-bounded, cleared by newer feed policy, and never self-renewed by a
  fallback read. Authoritative feed membership also fences late detail completions after an empty
  or omitting refresh. Metadata and the original-source action survive auth, timeout, cancellation,
  offline, and server failures. Auth loss and account replacement clear every identity-owned local
  store before another identity becomes visible.

### Verification evidence

- Focused S2/backend contract suite: **178 passed, 1 skipped, 19 subtests passed**.
- Full backend suite: **275 passed, 24 skipped, 75 subtests passed**, plus the same three
  independently failing S0 metric-gate subtests listed below.
- Real PostgreSQL S2 suite: **19 passed**, including additive migration/backfill idempotence,
  composite article/artifact ownership, `SKIP LOCKED`, lease/version fencing, exact feed-policy
  scope, policy-transition requeue, and a deterministic deadlock regression.
- iOS unit target: **52 passed**. S2 UI scenarios: **5 passed**, with no SwiftUI
  publish-during-view-update runtime warning. Release simulator build: **BUILD SUCCEEDED**.
- The repository-wide S0 evaluation test still reports the same **3 pre-existing 2026-09-02
  ranking-metric regressions** documented by the audit: `followup_recall_mean`,
  `never_rate_mean`, and `event_delivery_mean`. S2's public/private content split retains the same
  private ranking inputs; these are S0/S7 product-quality failures and were not hidden by changing
  baselines.

### Production-only gates still required

1. Finish S1's canonical source registry and safe central poller so every acquisition identity is
   controlled before S2 receives it.
2. Back up production, run the S2 backfill in read-only mode, then a bounded `--apply --max-rows`
   canary; inspect outcomes before the full resumable backfill and constraint validation.
3. Keep every source `source_only` unless a human review records the exact allowed artifact kinds,
   exact feed URLs, rights basis, reviewer, and access hint. Publisher/counsel review remains a
   product/legal prerequisite, not something code can infer.
4. Deploy by build SHA, prove `/readyz`, then canary **0** publisher/body mismatches, **0** synthetic
   publisher bodies, at least **99.5%** valid one-tap destinations, and the latency/outcome metrics
   specified below before widening rollout.

No production database mutation, source-policy grant, deploy, commit, or push was performed during
this implementation pass.

## Original audit snapshot — 2026-09-03

Read-only architecture and correctness review, 2026-09-03. Evidence: the current dirty
worktree, focused and full test runs, an iOS simulator build, the 2026-09-02 production
measurements in `tasks/s1-ingestion-audit.md`, and read-only probes of the production API.
No product code or production state was changed.

## Verdict

The product principle was right: every selected story should either have trustworthy native
text or open cleanly at its original source. At audit time, the implementation did not uphold
that principle and was not ready to ship as S2.

The largest problem is not extraction recall. It is that `articles.content` has no stable
meaning. It can contain feed text, a same-URL scrape, or text found at a different publisher by
Tavily. The API then returns the original publisher and byline without returning the body's
provenance, and iOS treats character count as proof of completeness. This can show another
publisher's reporting under the wrong publisher and author, or show a deterministic 2,000-
character truncation as though it were the complete article.

**Audit-time ship gate: fail. Review status: `DONE_WITH_CONCERNS`.** The closure section above
records the replacement contract and current repository result.

## Product decision

Do **not** select stories based on whether Daily can republish their body. That would bias the
edition toward RSS-friendly publishers and away from important, local, paywalled, or
JavaScript-heavy reporting.

Keep these two decisions independent:

1. **Editorial selection:** is this the best trustworthy story for this reader?
2. **Reading presentation:** may Daily show a verified body natively, or should the user read it
   at the original source?

For v1, the correct experience is:

- `native_full_text`: only for a body tied to this article and allowed by an explicit source
  policy; tap opens Daily's native reader.
- `source_web`: for unknown rights, paywalls, extraction failure, partial text, or low confidence;
  tap directly presents `SFSafariViewController` for the canonical source URL.
- `unavailable`: only when neither a valid body nor a valid original URL exists; these articles
  should normally be excluded before feed assembly.

An optional `daily_brief` can exist later, but it must be labeled as Daily-authored and must
never occupy the publisher-body field or appear under a journalist's byline.

This also matches the platform boundary. Apple's
[`SFSafariViewController`](https://developer.apple.com/documentation/safariservices/sfsafariviewcontroller)
is the native in-app browser for source pages, and its
[`entersReaderIfAvailable`](https://developer.apple.com/documentation/safariservices/sfsafariviewcontroller/configuration-swift.class/entersreaderifavailable)
configuration can request Reader when supported. Apple's
[App Review Guidelines 5.2](https://developer.apple.com/app-store/review/guidelines/) require
permission for third-party content; availability in a feed or successful scraping is not a
rights decision. The item-based routing recommendation also follows the project's referenced
[SwiftUI UI patterns](https://github.com/Dimillian/Skills/blob/main/swiftui-ui-patterns/SKILL.md).
`source_only` is the safe engineering default, not a legal opinion; publisher terms and any
license basis still need owner/counsel review before allowlisting native full-text display.

## What is already worth keeping

- `content:encoded` is now harvested at ingest.
- Failed extraction gets a bounded retry instead of becoming terminal on the first miss.
- Model-written expansion was removed from the article-body path.
- The static extractor records method/domain/attempt telemetry.
- iOS already wraps `SFSafariViewController` and enables Reader when the source supports it.
- The current app compiles, and the focused S2 backend tests pass.

Those are useful ingredients. They do not establish identity, completeness, permission, or a
reliable reader destination.

## Findings

### P0 — content integrity

1. **Cross-source text is attributed to the original publisher.**

   `web_search_service.py:29-107` searches a title, accepts the highest-scoring Tavily result,
   and can concatenate snippets from several results. `article_enrichment.py:127-141` copies
   only the returned text into `updates["content"]`; `_apply_enrichment` then overwrites
   `articles.content` without preserving the returned source URL or source name. The article API
   still returns the original `source_name`, author, and URL (`feed_service.py:1678-1688`).

   This is not an acceptable fallback for a publisher body. Even when search found the same
   underlying event, it found a different document. Disable this write. Tavily may support
   discovery, story matching, or separately labeled related coverage; it must never overwrite
   the original article's display body.

2. **Publisher-supplied feed bodies are immediately eligible for a lower-trust overwrite.**

   Ingest stores `content:encoded` with `content_extracted = true`
   (`news_ingestion.py:356-377`) but does not set its method or extractor version. The schema
   default is extractor version 1, so the re-extraction pass selects it (`main.py:190-200`) and
   unconditionally replaces the publisher-supplied body with whatever a page scrape returns
   (`:208-225`). This reverses the intended trust order and can turn complete publisher text into
   a partial or invalid scrape.

   Store feed text as a provenance-tagged artifact with higher precedence. A re-extractor may add
   a candidate variant, but it must not overwrite that artifact without a validated improvement.

3. **The client deterministically mistakes a truncated preview for a full article.**

   Fresh candidates clip `content` to 2,000 characters (`feed_service.py:494-519`), while cached
   feed rows clip it to 500 (`feed_service.py:1513-1518`). iOS skips the detail endpoint whenever
   incoming content is over 500 characters (`ArticleDetailView.swift:378-404`). A reproduced
   5,000-character database body therefore arrives as 2,000 characters and is rendered as
   complete; the same article coming from cache takes a different path.

   Feed payloads should expose an explicitly named `body_excerpt`, never a clipped `content`
   field. The server—not a length heuristic—must return `presentation_mode` and body state. Both
   fresh and cached feeds must use one serializer.

4. **There is no body-provenance or display-rights contract.**

   `NewsArticle` and `GET /feed/{article_id}` carry only `content`. They do not say where the text
   came from, whether it is complete, whether Daily may display it, or whether it is a summary.
   `content_quality` mixes body length with image availability: a summary plus image can score
   higher than a long body without an image. It is a ranking hint, not a reader contract.

   Feed availability also does not by itself establish a right to republish. Default every
   source to `source_only`; enable native full text only when a source-specific policy records a
   reviewed permission or license basis.

### P0 — reader dead ends

5. **Loading and failures replace the entire article, including the source escape hatch.**

   `ArticleDetailView.swift:33-60` renders only a spinner or a full-screen tap-to-retry error
   while `fullArticle` is nil. If there is no access token, `loadFullArticleIfNeeded` returns
   silently (`:386`) and the main view has no article content at all. On a network failure the
   source button is hidden with the metadata because it lives after the body at `:358-373`.

   The view must always render the title, source, summary, and original-source action from the
   feed record. A detail fetch should enhance that screen, never gate access to it. For a
   `source_web` article, skip the detail fetch and present the source directly. Replace the
   tap-anywhere retry gesture with an accessible button; move auth/network policy out of the
   400-line view behind an injected reader client/store and one enum state.

6. **The source reader exists but is not the primary route.**

   `SafariView.swift` correctly creates `SFSafariViewController` with
   `entersReaderIfAvailable = true`, but it is presented through a boolean sheet and only from a
   footer button. Use a typed destination and `.sheet(item:)` or `.fullScreenCover(item:)` so a
   card tap deterministically selects one mutually exclusive reading destination. Preserve feed
   scroll/state on dismissal.

7. **The existing offline feed cache is not connected to the foreground feed or reader.**

   `BackgroundNewsFetcher.swift:81-95,126-150` loads and persists cached articles, but
   `NewsViewModel.swift:42-114` starts with an empty list and goes directly to the network; it
   never consumes `lastFeedArticles`. Cached 500-character payloads also deliberately trigger a
   detail request, so they cannot provide a reliable offline reading state.

   Restore the last edition before starting a refresh. Persist complete, permitted native bodies
   explicitly; source-only stories retain metadata/summary and say that a connection is required.

### P1 — state, races, and recovery

8. **Best-effort telemetry controls the retry budget.**

   The scheduler and on-demand gate use `extraction_attempt_count`; its increment lives in
   `record_extraction`, whose exception handler deliberately swallows every database error.
   When telemetry fails, the operational attempt does not advance, so a failed URL can be
   retried indefinitely. Job state and observability must be separate writes or one atomic
   transaction in which the state transition is authoritative.

9. **Background extraction, on-demand extraction, and enrichment can race.**

   Work is selected without a lease or `FOR UPDATE SKIP LOCKED`. Separate request connections can
   extract the same row while the background loop or enrichment worker also updates it. Writes
   have no expected-version or provenance-precedence condition, so a later lower-quality or
   cross-source result can overwrite a verified origin body.

   Claim work atomically, give claims an expiry, and condition writes on job version. The write
   precedence must be explicit: licensed/origin full text beats partial text; non-displayable
   analysis can never replace display text.

10. **Derived article understanding can silently describe an older body.**

    Embeddings are generated before enrichment (`main.py:239-267`). Enrichment and on-demand
    extraction can replace `content` later without invalidating the embedding. Ranking, search,
    or chat can therefore use a vector derived from text the reader no longer sees. Every body
    artifact needs a version, and all summaries/embeddings/facets must record and rebuild from
    that version.

11. **Boolean state is semantically false.**

   `content_extracted` becomes true after the retry budget is exhausted even when no content was
   extracted. `enrichment_completed` can mean success or merely no attempts remain. Replace
   these with a state machine such as `pending`, `leased`, `ready`, `retryable_failure`, and
   `terminal_failure`, plus a reason and `next_retry_at`.

### P1 — extraction safety and validity

12. **Redirect SSRF protection runs after the redirect request.**

   `content_extractor.py:118-144` lets httpx follow redirects automatically, then validates the
   final URL. A redirect to a private address has already been requested when the check runs.
   `image_extraction.py:59-70` follows redirects with no public-address check at all. Neither
   path enforces an input Content-Type or a streamed response-byte ceiling before materializing
   the body.

   Restrict fetches to registered source hosts, disable automatic redirects, validate every hop,
   cap hop count and bytes while streaming, require expected content types, and enforce an
   egress-level private-network block as defense in depth.

13. **Length is treated as correctness.**

    Trafilatura is accepted at 100 characters and the BeautifulSoup fallback can return any
    text from `article`, `main`, or `body`. There is no validation against the expected headline,
    canonical URL, author/date, language, login wall, consent page, or error page. A long error
    page can be promoted to a publisher body.

    Validate identity and document shape, classify deterministic blocks separately, and track
    `complete`, `partial`, and `invalid` instead of one character threshold.

14. **Paywalls are retried like transient network failures.**

    A 401/403, subscription wall, consent wall, 404, 429, timeout, and parser miss need different
    policies. Known paywalls and access walls should immediately choose `source_web`; 429/5xx and
    network failures get bounded exponential backoff with jitter and `Retry-After` support.

### P1 — API and adjacent integrity

15. **The article endpoint accepts any bearer string.**

    `/feed/{article_id}` calls `_require_auth`, which checks only the `Bearer ` prefix, but never
    calls `_get_user_id_from_token`. A production probe returned 401 without a token and 404—not
    401—with `Bearer definitely-invalid-token`, proving the invalid token reached article lookup.

16. **Unknown publishers are labeled `Daily`.**

    `NewsArticle.displaySource` falls back to `"Daily"`. Missing third-party metadata must be
    `Unknown source` or derived from a validated original URL; it must never imply Daily authored
    or published the story.

17. **Generated and stock images still lack provenance.**

    Enrichment can attach Unsplash or Gemini images without exposing that provenance to the
    client. This is adjacent to S2 rather than its core body contract, but the same rule applies:
    synthetic or illustrative media cannot be presented as source photography. The approved S1
    plan already says to disable generated images.

### P2 — observability accuracy

18. **The extraction dashboard's thin-rate denominator is attempt rungs, not article outcomes.**

    One extraction cycle appends a row for each attempted method
    (`extraction_telemetry.py:45-59`), while `/admin/extraction-stats` computes thin/error rates
    over all of those rows (`main.py:591-605`). A failed trafilatura attempt followed by a
    successful BeautifulSoup attempt is partly counted as a failure. Keep rung telemetry, but
    report a separate final outcome per article/cycle so routing decisions use the correct
    denominator.

19. **Public documentation overstates the current system.**

    `README.md:27,34,186` says the backend reads every article in full and ranks from full-body
    understanding. The last production measure found only 26% with at least 400 characters and
    zero embeddings, while current code can rank from summaries and incomplete bodies. Rewrite
    those claims when the new presentation and analysis contracts land; until then describe
    best-effort extraction plus honest original-source handoff.

## Target architecture

```text
source registry + explicit display policy
                 |
                 v
canonical article identity and publisher metadata
                 |
        +--------+------------------+
        |                           |
        v                           v
display-content job             analysis pipeline
(same-origin only)              (ranking/embedding only;
        |                         never rendered as body)
        v
validated content artifact + provenance + rights basis
        |
        v
server-derived presentation mode
        |
        +--> native_full_text --> Daily reader
        +--> source_web -------> SFSafariViewController(original URL)
        +--> unavailable ------> exclude or honest metadata fallback
```

### Data ownership

Keep `articles` as canonical identity and source metadata. Add two explicit records rather than
continuing to overload it:

- `article_content_artifacts`: `article_id`, `kind`, `text`, `origin_url`, `origin_source_id`,
  `method`, `rights_basis`, `completeness`, `confidence`, `content_hash`, `fetched_at`,
  `extractor_version`, and `displayable`.
- `article_content_jobs`: `article_id`, `state`, `failure_reason`, `attempt_count`,
  `next_retry_at`, `lease_owner`, `lease_expires_at`, and optimistic `version`.

The source registry should own a reviewed `display_policy`, defaulting to `source_only`. The
presentation resolver may choose native text only from a `displayable` artifact whose source
identity matches the canonical article and whose policy permits that artifact kind.

Keep search snippets, embeddings, generated summaries, and related coverage in analysis or
separately labeled artifacts. They are valuable inputs, but they are not the publisher's body.

### API contract

Add fields without breaking older mobile clients, then retire ambiguous `content` after client
migration:

```json
{
  "id": "...",
  "title": "...",
  "publisher": {"name": "...", "canonical_url": "..."},
  "summary": {"text": "...", "kind": "publisher_preview"},
  "body_excerpt": "...",
  "presentation": {
    "mode": "native_full_text",
    "original_url": "https://publisher.example.com/story",
    "body": "...",
    "body_state": "verified_full",
    "access_hint": "free",
    "provenance": {
      "method": "publisher_feed",
      "origin_url": "https://publisher.example.com/story",
      "fetched_at": "...",
      "extractor_version": 4
    }
  }
}
```

Feed responses need only metadata, `body_excerpt`, and `presentation.mode`. Native full text can
remain on the detail endpoint or in an explicit offline cache. Fresh and cached feed paths must
call the same serializer and return the same semantics.

### Extraction cascade

1. Licensed publisher API or explicitly approved full-text feed artifact.
2. Precision extraction from the registered canonical/original source.
3. Recall extraction and same-publisher canonical/AMP path, with identity validation.
4. Optional isolated browser extraction only for measured JavaScript-heavy same-origin sources.
5. Honest `source_web` handoff.

Do not use a browser to bypass paywalls, and do not build the browser service until production
telemetry shows that static same-origin extraction leaves a valuable, recoverable gap. A source
handoff is cheaper, more reliable, and more respectful than server-side rendering for many
publishers.

### iOS state and routing

Use one value-typed destination and one reader state rather than multiple presentation booleans:

```swift
enum ArticleDestination: Identifiable {
    case native(NewsArticle)
    case source(URL)
}

enum ReaderState {
    case metadata(NewsArticle)
    case loading(NewsArticle)
    case ready(NewsArticle)
    case failed(NewsArticle, message: String)
}
```

- Card tap uses `presentation.mode`; it never infers completeness from string length.
- `source_web` is signaled subtly on the card with the publisher/domain and an external-link glyph,
  then opens the original URL immediately in a full-screen `SFSafariViewController` on iPhone
  (adaptive modal on iPad).
- `native_full_text` opens the native view from cached data, then refreshes asynchronously.
- Loading/error/offline states retain metadata, summary, and an always-visible source action.
- Invalid URL, missing auth, timeout, and backend failure all degrade to the original source when
  one exists.
- Known metered/subscription sources can show a small `Subscription may be required` hint before
  the user taps; do not attempt to evade the publisher's access controls.
- Do not introduce `WKWebView` for this flow unless Daily later needs controlled interaction with
  page content. Safari already supplies the appropriate browser, privacy, Reader, share, and
  navigation behavior.

## Verification required before S2 can pass

### Contract and backend

- Same article has identical presentation semantics through fresh and cached feed paths.
- Cross-source search results can never populate displayable publisher text.
- A publisher-feed body cannot be downgraded by a re-extraction result.
- Invalid and expired tokens get 401 from the detail endpoint.
- A leased job is processed once under concurrent worker/request pressure; stale results cannot
  overwrite higher-precedence artifacts.
- Changing a display or analysis artifact invalidates every derived value tied to its old version.
- Fixtures cover complete article, teaser, consent wall, login/paywall, 404 page, malformed HTML,
  non-HTML response, oversize/decompression limit, timeout, 429/`Retry-After`, 5xx, cross-domain
  canonical, and every redirect hop to a private address.
- Provenance and rights-policy tests deny native rendering by default.

### iOS

- Tests cover `native_full_text`, `source_web`, and `unavailable` routes.
- No-token, slow network, timeout, offline, invalid URL, retry, double tap, and dismissal preserve
  a usable screen and the feed's position.
- UI tests prove a thin/source-only article opens its source in one tap and a native article never
  displays a clipped preview as full text.

### Production gates

- **0** cross-publisher body/source mismatches.
- **0** synthetic or combined-search text attributed to a publisher or journalist.
- At least **99.5%** of visible cards have a valid one-tap destination; measure native-body rate
  separately rather than gaming it by selecting easier sources.
- p95 card tap to visible destination under 1 second from feed cache; source handoff must not wait
  for server extraction.
- Per-domain extraction success, failure reasons, retry volume, source-handoff rate, and latency
  are observable by build SHA.

## Implementation order

1. **Integrity stop-ship:** disable Tavily body writes; disable generated-image presentation;
   fix detail auth; stop sending clipped text as `content`; keep source metadata/CTA visible on
   every reader state; prevent re-extraction from replacing publisher-feed bodies; remove the
   `Daily` unknown-source fallback.
2. **S1 dependency:** land the canonical source registry and add its default-deny display policy.
3. **Additive S2 contract:** migrate content artifacts/jobs, add provenance and presentation
   fields, and use one fresh/cache serializer while retaining legacy optional fields.
4. **Origin-only pipeline:** implement atomic job leases, typed failure/retry policy, safe bounded
   fetches, document identity/completeness validation, conditional write precedence, and
   content-version invalidation for embeddings/summaries/facets.
5. **iOS router:** decode the new contract, use an item-based destination, make source web
   one-tap primary when required, and preserve metadata through loading/error/offline states.
6. **Corpus and chaos gate:** run deterministic extractor fixtures, concurrency/teardown tests,
   API contract tests, iOS routing/UI tests, and a production canary sample.
7. **Optional recall work:** add same-origin AMP/recall extraction, then an isolated browser only
   if measured source-level value justifies its cost and operational surface.
8. **Deploy and re-measure:** the current production backend is stale, so repository completion
   is not production completion. Gate rollout on live build identity and the production metrics
   above.

## Verification performed during this audit

- Focused S2 backend suite: **58 passed, 1 skipped, 4 subtests passed**.
- Full backend suite: **192 passed, 5 skipped, 60 subtests passed; 3 S0 evaluation-gate
  regressions** (`followup_recall_mean`, `never_rate_mean`, `event_delivery_mean` on the
  2026-09-02 `prod-llm` snapshot). These are not caused by S2, but the branch is not green.
- iOS simulator build on iPhone 17 Pro / iOS 26.5: **BUILD SUCCEEDED**.
- Behavioral truncation reproduction: stored body 5,000 chars -> fresh feed 2,000 chars -> iOS
  `>500` gate skips the detail fetch.
- Production 2026-09-03: `/healthz` **404**, `/readyz` **404**, OpenAPI version **0.2.0**, no
  `/admin/extraction-stats`; dummy Bearer token reached article lookup and returned **404**.
- A fresh production-database remeasure was unavailable because the configured database hostname
  did not resolve from this workspace. The last confirmed body-coverage measure remains the
  2026-09-02 audit: 3,829 / 14,991 seven-day articles (26%) had at least 400 characters.
