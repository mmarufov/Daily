# S9 implementation status

Updated 2026-09-10. Repository implementation on `mmarufov/sydney-v7`.
No commit, push, hosted SQL, source-policy grant, provider call, deployment or activation.
Existing unrelated worktree changes were preserved.

## Implemented

- Negotiated delivery v1 envelope with immutable edition identity, durable per-account
  publication sequence, reader identity, publication/validation/expiry dates and reasoned
  transient states. Publication counters participate in the existing transaction and survive
  result cleanup. Legacy responses do not receive invented publication authority.
- Provider-free, freshly authorized cached serving; bounded worker-owned detail/auth database
  access; private/no-store responses; default-deny native offline policy grants and management
  schema/CLI support. Existing S7/S8 activation controls remain unchanged.
- One injected feed coordinator: bounded fast GET, one build for true setup/miss, bounded
  GET-only build polling, foreground refresh, cancellation/session fencing, monotonic response
  acceptance, authoritative empty handling and immediate hard-invalidation cache barriers.
- Account-owned protected file caches with bounded metadata/native retention; explicit cache
  miss/corruption/unavailability; durable serialized bookmarks; generation-fenced cleanup.
  Unowned legacy bookmark files are preserved, not assigned to a new account.
- Cold-launch read-only saved-account shell, separate from authenticated tabs. Cached identity
  grants no server token or attributed-event access. Rejected sessions/sign-out clear access.
- Native cached bodies require explicit server offline grants. Eligible bodies display before
  revalidation, without renewing expiry on fallback. Current session and membership are checked
  before display/persistence. Revocation removes old copies, including when the fresh response
  permits online reading but removes offline permission.
- Reader retry and expiry have separate request/display lifetimes: cancellation-insensitive old
  transports cannot overwrite a retry, and expiration does not discard a valid current refresh.
  Expired bodies leave a retryable state. Newer verified canonical detail corrections can update
  reader metadata without rewriting the edition receipt.
- Related semantic search is user-triggered, not an automatic article-open cost. Source-only
  stories retain the existing publisher handoff. Native reading intervals exclude loading,
  inactive scenes and source/chat sheets, retain the actual displayed body/receipt, and require
  visible body content. Paragraph preparation is outside view construction.
- Bounded, coalesced image pipeline (four active requests, compressed bytes/pixels/decoded
  memory limits, ImageIO downsampling, cancellation and account fencing); no global URLCache
  mutation or all-feed prefetch. Lazy feed rows, adaptive text sizes, selectable native text,
  accessible feedback/retry, accurate opened traits and Reduce Motion-aware button effects.
- Feed impressions require continuous viewport visibility, active scene and visible tab with
  no covering modal. Saved editions strip receipt authority. Optional unbound briefing is hidden.
- Privacy-safe backend stage timings, feed acceptance logs and Instruments events for feed-load
  start and metadata publication. Publication events are not proof of a rendered frame.

## Deliberate scope refinements

- Public cards do not carry a trusted source ID everywhere. An acknowledged hard exclusion
  invalidates the whole saved membership and reloads rather than guessing a publisher match.
  Soft `less_like_this` retains its non-ban semantics.
- Image demand comes from lazy visible/near-viewport card tasks; no separate prefetch scheduler
  or new image dependency was added. Cache validators/freshness follow the owned pipeline.
- Legacy editions are explicitly freshness-unverified; new authoritative metadata is available
  only from the capable server path. The client does not silently enable S4 priority capability.
- Unleased online native content is revalidated on activation and removed after a bounded
  five-minute in-memory display interval; it is never saved as an offline grant. Native grants
  remain at most 24 hours and default to zero until an operator approves a source policy.
- Existing character wrapping is retained to preserve S2 overflow safety; language-specific
  typography and large-body rendering still require device review. No claim of universal
  publisher availability, instant offline revocation or guaranteed background delivery.

## Verification

- Full backend offline suite: **1,833 passed, 143 skipped, 235 subtests passed**; the same three
  pre-existing S0 snapshot-quality failures remain (`followup_recall_mean`, `never_rate_mean`,
  `event_delivery_mean`, prod-llm 2026-09-02). No new S9 backend failures.
  Evidence: `.context/s9-backend-full-final.log`, `.context/s9-backend-status.md`.
- Focused backend: 230 tests and 34 subtests passed after timing integration. Additional source
  inspection checks: 17 tests and four subtests passed. Backend compile checks passed.
- iOS unit regression: 118 passed, zero failed/skipped on 2026-09-10 before final UI refinements.
  Result: `Test-Daily-2026.09.10_02-13-20--0700.xcresult` under the existing Daily DerivedData test directory.
- Five isolated S2 reader UI tests passed on 2026-09-10, covering native, source handoff,
  missing token, offline/timeout retry, and invalid URL. Test bootstrap suppresses live auth
  restoration; provider calls were not needed.
- Final combined iOS rerun: **123 tests passed (118 unit + five reader UI), zero failures or
  skips**, after the final reader retry/expiry, geometry, text-preparation and instrumentation
  changes. Result: `Test-Daily-2026.09.10_02-15-36--0700.xcresult` in the same DerivedData directory.
- Added one final regression for online-only response membership fencing/offline-grant revocation;
  reran all iOS unit tests: **119 passed, zero failed/skipped**. Result:
  `Test-Daily-2026.09.10_02-18-05--0700.xcresult`. No runtime edits after the combined UI run.
- Release simulator build passed (2026-09-10), `CODE_SIGNING_ALLOWED=NO`. Existing unrelated
  onboarding/test-isolation/deprecation warnings remain; this is not a device archive or deployment.
- Final `git diff --check` passed. The branch remains unchanged and work is uncommitted.

## Remaining release gates — not completed by repository tests

1. Explicitly install/review S2/S7 schema changes and execute the opt-in PostgreSQL sequence,
   concurrent-publication and rollback tests without skips against an approved disposable DB.
2. Approve actual source offline-cache policy grants; deploy compatible API and client builds
   by SHA. Verify readiness and rollback before changing serving flags. No grants were made here.
3. Measure cold/warm saved launch, first rendered frame, long-body reader and scroll performance
   on a defined physical device/Release build. The plan's p95 goals remain targets, not results.
4. Device accessibility review (VoiceOver, largest text, contrast, RTL, Reduce Motion), plus
   end-to-end saved-account launch/reconnect tests and slow-network deployed canaries.
5. Resolve the existing S0 quality gate failures before making an overall launch-quality claim.

Repository S9 completion does not mean production activation or “bulletproof” performance.
