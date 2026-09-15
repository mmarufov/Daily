import XCTest
@testable import Daily

@MainActor
final class ArticleReaderContractTests: XCTestCase {
    func testDecodesExplicitNativeContractAndProvenance() throws {
        let data = Data(
            """
            {
              "id":"article-1",
              "title":"Verified story",
              "summary":"Summary",
              "content":"legacy text that must not win",
              "url":"https://publisher.com/story",
              "presentation":{
                "mode":"native_full_text",
                "original_url":"https://publisher.com/story",
                "body":"The explicitly verified publisher body.",
                "body_state":"verified_full",
                "access_hint":null,
                "reason":"policy_approved",
                "provenance":{
                  "kind":"origin_extract",
                  "method":"readability",
                  "source_url":"https://publisher.com/story",
                  "rights_policy":"publisher_permission",
                  "completeness":"complete",
                  "content_version":7,
                  "policy_version":3
                }
              }
            }
            """.utf8
        )

        let article = try BackendService.iso8601Decoder.decode(NewsArticle.self, from: data)

        XCTAssertEqual(article.verifiedNativeBody, "The explicitly verified publisher body.")
        XCTAssertEqual(article.presentation?.provenance?.contentVersion, 7)
        XCTAssertEqual(article.presentation?.provenance?.policyVersion, 3)
        XCTAssertEqual(article.readerRoute, .native)
    }

    func testUnknownPresentationValuesFailClosed() throws {
        let data = Data(
            """
            {
              "id":"article-1",
              "title":"Story",
              "content":"untrusted legacy body",
              "presentation":{
                "mode":"future_mode",
                "body":"future body",
                "body_state":"future_state"
              }
            }
            """.utf8
        )

        let article = try BackendService.iso8601Decoder.decode(NewsArticle.self, from: data)

        XCTAssertEqual(article.presentation?.mode, .unavailable)
        XCTAssertEqual(article.presentation?.bodyState, ArticleBodyState.none)
        XCTAssertNil(article.verifiedNativeBody)
        XCTAssertEqual(article.readerRoute, .unavailable)
    }

    func testLegacyContentNeverEnablesNativeReader() throws {
        let data = Data(
            """
            {
              "id":"legacy-1",
              "title":"Legacy story",
              "content":"A long legacy body that has no provenance or rights assertion.",
              "url":"https://publisher.com/story"
            }
            """.utf8
        )

        let article = try BackendService.iso8601Decoder.decode(NewsArticle.self, from: data)

        XCTAssertNil(article.verifiedNativeBody)
        XCTAssertEqual(article.readerRoute, .source(URL(string: "https://publisher.com/story")!))
        XCTAssertNil(article.safeForReaderCache().content)
    }

    func testNativeBodyFailsClosedWithoutEveryTrustAssertion() throws {
        let invalidProvenance: [[String: Any]] = [
            ["kind": "analysis_text", "rights_policy": "publisher_permission", "completeness": "complete", "content_version": 1, "policy_version": 1],
            ["kind": "origin_extract", "rights_policy": "unknown", "completeness": "complete", "content_version": 1, "policy_version": 1],
            ["kind": "origin_extract", "rights_policy": "UNKNOWN", "completeness": "complete", "content_version": 1, "policy_version": 1],
            ["kind": "origin_extract", "rights_policy": "none", "completeness": "complete", "content_version": 1, "policy_version": 1],
            ["kind": "origin_extract", "rights_policy": "revoked", "completeness": "complete", "content_version": 1, "policy_version": 1],
            ["kind": "origin_extract", "rights_policy": "publisher_permission", "completeness": "partial", "content_version": 1, "policy_version": 1],
            ["kind": "origin_extract", "rights_policy": "publisher_permission", "completeness": "complete", "content_version": 0, "policy_version": 1],
            ["kind": "origin_extract", "rights_policy": "publisher_permission", "completeness": "complete", "content_version": 1, "policy_version": 0]
        ]

        for provenance in invalidProvenance {
            let payload: [String: Any] = [
                "id": "article-1",
                "title": "Story",
                "presentation": [
                    "mode": "native_full_text",
                    "body": "Body that must not render",
                    "body_state": "verified_full",
                    "provenance": provenance
                ]
            ]
            let data = try JSONSerialization.data(withJSONObject: payload)
            let article = try BackendService.iso8601Decoder.decode(NewsArticle.self, from: data)
            XCTAssertNil(article.verifiedNativeBody, "Expected trust contract to fail closed for \(provenance)")
        }
    }

    func testOnlyTypedProvenanceBearingImagesRender() throws {
        let legacyOnly = try BackendService.iso8601Decoder.decode(
            NewsArticle.self,
            from: Data(#"{"id":"legacy","title":"Story","image_url":"https://publisher.com/legacy.jpg"}"#.utf8)
        )
        XCTAssertNil(legacyOnly.displayImageURL)

        let typed = try BackendService.iso8601Decoder.decode(
            NewsArticle.self,
            from: Data(#"{"id":"typed","title":"Story","image":{"url":"https://images.publisher.com/photo.jpg","origin":"stock","source_url":"https://images.publisher.com/photo","attribution":"Photographer","illustrative":true}}"#.utf8)
        )
        XCTAssertEqual(typed.displayImageURL?.absoluteString, "https://images.publisher.com/photo.jpg")
        XCTAssertTrue(typed.imageIsIllustrative)

        let unknown = try BackendService.iso8601Decoder.decode(
            NewsArticle.self,
            from: Data(#"{"id":"unknown","title":"Story","image":{"url":"https://images.publisher.com/photo.jpg","origin":"future_origin","illustrative":false}}"#.utf8)
        )
        XCTAssertNil(unknown.displayImageURL)
    }

    func testRoutingRequiresExplicitModeOrSafeOriginalSource() {
        XCTAssertEqual(makeArticle(mode: .nativeFullText).readerRoute, .native)
        XCTAssertEqual(
            makeArticle(mode: .sourceWeb).readerRoute,
            .source(URL(string: "https://publisher.com/story")!)
        )
        XCTAssertEqual(makeArticle(mode: .unavailable, originalURL: nil, legacyURL: nil).readerRoute, .unavailable)
    }

    func testExplicitUnavailableOutranksRetainedLegacyURL() {
        let unavailable = makeArticle(
            mode: .unavailable,
            originalURL: nil,
            legacyURL: "https://publisher.com/legacy-story"
        )

        XCTAssertNil(unavailable.originalSourceURL)
        XCTAssertEqual(unavailable.readerRoute, .unavailable)
    }

    func testTypedContractNeverFallsBackToRetainedLegacyURL() {
        for mode in [ArticlePresentationMode.nativeFullText, .sourceWeb] {
            let missingCanonical = makeArticle(
                mode: mode,
                originalURL: nil,
                legacyURL: "https://publisher.com/legacy-story"
            )
            let invalidCanonical = makeArticle(
                mode: mode,
                originalURL: "https://localhost/story",
                legacyURL: "https://publisher.com/legacy-story"
            )

            XCTAssertNil(missingCanonical.originalSourceURL)
            XCTAssertEqual(missingCanonical.readerRoute, .unavailable)
            XCTAssertNil(invalidCanonical.originalSourceURL)
            XCTAssertEqual(invalidCanonical.readerRoute, .unavailable)
        }
    }

    func testReaderURLValidationRejectsLocalAndAmbiguousDestinations() {
        let invalidURLs = [
            "file:///etc/passwd",
            "javascript:alert(1)",
            "https://user:secret@publisher.com/story",
            "https://localhost/story",
            "https://news.internal/story",
            "https://publisher.test/story",
            "https://intranet/story",
            "https://127.0.0.1/story",
            "https://127.1/story",
            "https://0177.0.0.1/story",
            "https://169.254.169.254/latest/meta-data",
            "https://192.168.1.2/story",
            "https://198.51.100.4/story",
            "https://[::1]/story",
            "https://[fc00::1]/story",
            "https://[fe80::1]/story",
            "https://[2001:db8::1]/story",
            "https://[::ffff:127.0.0.1]/story"
        ]

        for rawURL in invalidURLs {
            XCTAssertNil(NewsArticle.validSourceURL(rawURL), "Expected rejection for \(rawURL)")
        }
        XCTAssertNotNil(NewsArticle.validSourceURL("https://publisher.com/story"))
        XCTAssertNotNil(NewsArticle.validSourceURL("https://[2606:4700:4700::1111]/story"))
    }

    func testCoordinatorGatesDuplicateTapAndTrackingTogether() {
        let article = makeArticle(mode: .sourceWeb)
        var markedIDs: [String] = []
        var taps: [(String, Int?)] = []

        let first = ArticleReaderCoordinator.open(
            article: article,
            position: 4,
            currentDestination: nil,
            markAsRead: { markedIDs.append($0) },
            logTap: { taps.append(($0, $1)) }
        )
        let duplicate = ArticleReaderCoordinator.open(
            article: article,
            position: 4,
            currentDestination: first,
            markAsRead: { markedIDs.append($0) },
            logTap: { taps.append(($0, $1)) }
        )

        XCTAssertNotNil(first)
        XCTAssertNil(duplicate)
        XCTAssertEqual(markedIDs, [article.id])
        XCTAssertEqual(taps.count, 1)
        XCTAssertEqual(taps.first?.0, article.id)
        XCTAssertEqual(taps.first?.1, 4)
    }

    func testCachedBodyRequiresMatchingExplicitVersionAndSourceHost() {
        let current = makeArticle(mode: .nativeFullText, body: nil, version: 8)
        let matching = makeArticle(mode: .nativeFullText, body: "Cached body", version: 8)
        XCTAssertEqual(current.mergingCompatibleCachedDetail(matching)?.verifiedNativeBody, "Cached body")

        let stale = makeArticle(mode: .nativeFullText, body: "Stale body", version: 7)
        XCTAssertNil(current.mergingCompatibleCachedDetail(stale))

        let unversionedCurrent = makeArticle(mode: .nativeFullText, body: nil, version: nil)
        XCTAssertNil(unversionedCurrent.mergingCompatibleCachedDetail(matching))

        let differentHost = makeArticle(
            mode: .nativeFullText,
            body: "Wrong source",
            version: 8,
            originalURL: "https://other.com/story"
        )
        XCTAssertNil(current.mergingCompatibleCachedDetail(differentHost))

        let revoked = makeArticle(mode: .sourceWeb, body: nil, version: 9)
        XCTAssertNil(revoked.mergingCompatibleCachedDetail(matching))
    }

    func testAuthenticatedDetailCanRevokeNativePresentationWithoutProvenance() {
        let current = makeArticle(mode: .nativeFullText, body: nil, version: 8)
        let revoked = makeArticle(mode: .sourceWeb, body: nil, version: nil)

        XCTAssertTrue(current.acceptsReaderDetail(revoked))
        XCTAssertEqual(current.mergingReaderDetail(revoked).readerRoute, revoked.readerRoute)
    }

    func testNativeDetailRequiresTypedCanonicalOrigin() {
        let current = makeArticle(mode: .nativeFullText, body: nil, version: 8)
        let missingCanonical = makeArticle(
            mode: .nativeFullText,
            body: "Body",
            version: 8,
            originalURL: nil,
            legacyURL: "https://publisher.com/story",
            provenanceSourceURL: "https://publisher.com/story"
        )
        let invalidCanonical = makeArticle(
            mode: .nativeFullText,
            body: "Body",
            version: 8,
            originalURL: "https://localhost/story",
            legacyURL: "https://publisher.com/story",
            provenanceSourceURL: "https://publisher.com/story"
        )

        XCTAssertFalse(current.acceptsReaderDetail(missingCanonical))
        XCTAssertFalse(current.acceptsReaderDetail(invalidCanonical))
    }

    func testNativeDetailProvenanceMustMatchOriginalPublisher() {
        let current = makeArticle(mode: .nativeFullText, body: nil, version: 8)
        let normalizedWWWHost = makeArticle(
            mode: .nativeFullText,
            body: "Publisher body",
            version: 8,
            provenanceSourceURL: "https://www.publisher.com/story"
        )
        let siblingHost = makeArticle(
            mode: .nativeFullText,
            body: "Sibling-host body",
            version: 8,
            provenanceSourceURL: "https://feeds.publisher.com/daily.xml"
        )
        let reviewedPublisherFeed = makeArticle(
            mode: .nativeFullText,
            body: "Reviewed feed body",
            version: 8,
            provenanceKind: "publisher_feed",
            provenanceSourceURL: "https://feeds.publisher-cdn.com/daily.xml"
        )
        let crossPublisher = makeArticle(
            mode: .nativeFullText,
            body: "Body from somewhere else",
            version: 8,
            provenanceSourceURL: "https://other.com/copied-story"
        )

        XCTAssertEqual(normalizedWWWHost.verifiedNativeBody, "Publisher body")
        XCTAssertTrue(current.acceptsReaderDetail(normalizedWWWHost))
        XCTAssertNil(siblingHost.verifiedNativeBody)
        XCTAssertFalse(current.acceptsReaderDetail(siblingHost))
        XCTAssertEqual(reviewedPublisherFeed.verifiedNativeBody, "Reviewed feed body")
        XCTAssertTrue(current.acceptsReaderDetail(reviewedPublisherFeed))
        XCTAssertNil(crossPublisher.verifiedNativeBody)
        XCTAssertFalse(current.acceptsReaderDetail(crossPublisher))
    }

    func testPublisherBindingDoesNotCollapseCountryCodePublicSuffix() {
        let publisher = URL(string: "https://bbc.co.uk/story")!
        let unrelated = URL(string: "https://evil.co.uk/copied-story")!

        XCTAssertFalse(NewsArticle.hasSamePublisherOrigin(publisher, unrelated))
    }

    func testSourceAccessHintsUseServerVocabulary() {
        XCTAssertTrue(
            ArticleReaderModel.sourceMessage(
                for: makeArticle(mode: .sourceWeb, accessHint: "subscription_may_be_required")
            ).contains("subscription")
        )
        XCTAssertTrue(
            ArticleReaderModel.sourceMessage(
                for: makeArticle(mode: .sourceWeb, accessHint: "publisher_sign_in_required")
            ).contains("sign in")
        )
        XCTAssertTrue(
            ArticleReaderModel.sourceMessage(
                for: makeArticle(mode: .sourceWeb, accessHint: "publisher_consent_required")
            ).contains("privacy or cookie")
        )
    }

    private func makeArticle(
        mode: ArticlePresentationMode,
        body: String? = nil,
        version: Int? = 1,
        policyVersion: Int? = 1,
        originalURL: String? = "https://publisher.com/story",
        legacyURL: String? = "https://publisher.com/story",
        provenanceKind: String = "origin_extract",
        provenanceSourceURL: String? = nil,
        accessHint: String? = nil
    ) -> NewsArticle {
        var article = NewsArticle(
            id: "article-1",
            title: "A story",
            summary: "Summary",
            content: "legacy body",
            author: "Author",
            source: "Publisher",
            imageURL: nil,
            publishedAt: nil,
            category: "News",
            url: legacyURL
        )
        article.presentation = ArticlePresentation(
            mode: mode,
            originalURL: originalURL,
            body: body,
            bodyState: body == nil ? .none : .verifiedFull,
            accessHint: accessHint,
            reason: nil,
            provenance: version.map {
                ArticleContentProvenance(
                    kind: provenanceKind,
                    sourceURL: provenanceSourceURL ?? originalURL,
                    rightsPolicy: "publisher_permission",
                    completeness: "complete",
                    contentVersion: $0,
                    policyVersion: policyVersion
                )
            }
        )
        return article
    }
}

@MainActor
final class ArticleReaderModelTests: XCTestCase {
    func testSourceContractDoesNotCallDetailEndpoint() async {
        let article = makeArticle(mode: .sourceWeb)
        var fetchCount = 0
        let model = ArticleReaderModel(article: article) { _, _ in
            fetchCount += 1
            return article
        }

        let result = await model.load(accessToken: "token")

        XCTAssertEqual(result, .none)
        XCTAssertEqual(fetchCount, 0)
        guard case .sourceAvailable = model.state else {
            return XCTFail("Expected sourceAvailable")
        }
    }

    func testNativeContractWithoutTokenPreservesMetadataAndRequestsAuthentication() async {
        let article = makeArticle(mode: .nativeFullText, body: nil)
        let model = ArticleReaderModel(article: article) { _, _ in
            XCTFail("Fetch must not start without a token")
            return article
        }

        let result = await model.load(accessToken: "  ")

        XCTAssertEqual(result, .none)
        guard case .authenticationRequired(let retained, _) = model.state else {
            return XCTFail("Expected authenticationRequired")
        }
        XCTAssertEqual(retained.id, article.id)
        XCTAssertEqual(retained.title, article.title)
    }

    func testHTTPAuthenticationFailuresAreNotShownAsGenericErrors() async {
        for statusCode in [401, 403] {
            let article = makeArticle(mode: .nativeFullText, body: nil)
            let model = ArticleReaderModel(article: article) { _, _ in
                throw NSError(domain: "BackendService", code: statusCode)
            }

            _ = await model.load(accessToken: "token")

            guard case .authenticationRequired = model.state else {
                return XCTFail("Expected authenticationRequired for HTTP \(statusCode)")
            }
        }
    }

    func testTimeoutIsDistinctFromOfflineFailure() async {
        let article = makeArticle(mode: .nativeFullText, body: nil)
        let timeoutModel = ArticleReaderModel(article: article) { _, _ in
            throw URLError(.timedOut)
        }
        _ = await timeoutModel.load(accessToken: "token")
        guard case .failed(_, let timeoutMessage) = timeoutModel.state else {
            return XCTFail("Expected failed timeout state")
        }
        XCTAssertTrue(timeoutMessage.localizedCaseInsensitiveContains("timed out"))

        let offlineModel = ArticleReaderModel(article: article) { _, _ in
            throw URLError(.notConnectedToInternet)
        }
        _ = await offlineModel.load(accessToken: "token")
        guard case .offline = offlineModel.state else {
            return XCTFail("Expected offline state")
        }
    }

    func testRetryAfterOfflineCanRecoverWithoutLosingMetadata() async {
        let feedArticle = makeArticle(mode: .nativeFullText, body: nil, version: 2)
        let detail = makeArticle(mode: .nativeFullText, body: "Verified body", version: 2)
        var attemptCount = 0
        let model = ArticleReaderModel(article: feedArticle) { _, _ in
            attemptCount += 1
            if attemptCount == 1 {
                throw URLError(.notConnectedToInternet)
            }
            return detail
        }

        let firstResult = await model.load(accessToken: "token")
        XCTAssertEqual(firstResult, .none)
        guard case .offline(let retained, _) = model.state else {
            return XCTFail("Expected offline state")
        }
        XCTAssertEqual(retained.title, feedArticle.title)

        let recovered = await model.load(accessToken: "token")
        guard case .store(let recoveredArticle) = recovered else {
            return XCTFail("Expected verified detail to be stored")
        }
        XCTAssertEqual(recoveredArticle.verifiedNativeBody, "Verified body")
        guard case .ready = model.state else {
            return XCTFail("Expected retry to recover")
        }
        XCTAssertEqual(attemptCount, 2)
    }

    func testVerifiedDetailTransitionsToReady() async {
        let feedArticle = makeArticle(mode: .nativeFullText, body: nil, version: 2)
        let detail = makeArticle(mode: .nativeFullText, body: "Verified body", version: 2)
        let model = ArticleReaderModel(article: feedArticle) { id, token in
            XCTAssertEqual(id, feedArticle.id)
            XCTAssertEqual(token, "token")
            return detail
        }

        let result = await model.load(accessToken: "token")

        guard case .store(let stored) = result else {
            return XCTFail("Expected verified detail to be stored")
        }
        XCTAssertEqual(stored.verifiedNativeBody, "Verified body")
        guard case .ready(let ready) = model.state else {
            return XCTFail("Expected ready")
        }
        XCTAssertEqual(ready.verifiedNativeBody, "Verified body")
    }

    func testOnlineDetailRevocationWinsOverCompatibleCachedBody() async {
        let feedArticle = makeArticle(mode: .nativeFullText, body: nil, version: 2)
        let cachedDetail = makeArticle(mode: .nativeFullText, body: "Cached body", version: 2)
        let revokedDetail = makeArticle(mode: .sourceWeb, body: nil, version: nil)
        var fetchCount = 0
        let model = ArticleReaderModel(article: feedArticle) { _, _ in
            fetchCount += 1
            return revokedDetail
        }

        let result = await model.load(accessToken: "token", cachedDetail: cachedDetail)

        XCTAssertEqual(result, .evict(articleID: feedArticle.id))
        XCTAssertEqual(fetchCount, 1)
        guard case .sourceAvailable(let revoked, _) = model.state else {
            return XCTFail("Expected the authenticated source-only contract to win")
        }
        XCTAssertNil(revoked.verifiedNativeBody)
    }

    func testAuthenticatedUnavailableDetailEvictsCachedNativeBody() async {
        let feedArticle = makeArticle(mode: .nativeFullText, body: nil, version: 2)
        let cachedDetail = makeArticle(mode: .nativeFullText, body: "Cached body", version: 2)
        let unavailableDetail = makeArticle(
            mode: .unavailable,
            body: nil,
            version: nil,
            originalURL: nil,
            legacyURL: "https://publisher.com/legacy-story"
        )
        let model = ArticleReaderModel(article: feedArticle) { _, _ in unavailableDetail }

        let result = await model.load(accessToken: "token", cachedDetail: cachedDetail)

        XCTAssertEqual(result, .evict(articleID: feedArticle.id))
        guard case .unavailable(let unavailable, _) = model.state else {
            return XCTFail("Expected unavailable state")
        }
        XCTAssertNil(unavailable.originalSourceURL)
        XCTAssertNil(unavailable.verifiedNativeBody)
    }

    func testOfflineCompatibleCacheIsFallbackWithoutRenewingItsTTL() async {
        let feedArticle = makeArticle(mode: .nativeFullText, body: nil, version: 2)
        let cachedDetail = makeArticle(mode: .nativeFullText, body: "Cached body", version: 2)
        var fetchCount = 0
        let model = ArticleReaderModel(article: feedArticle) { _, _ in
            fetchCount += 1
            throw URLError(.notConnectedToInternet)
        }

        let result = await model.load(accessToken: "token", cachedDetail: cachedDetail)

        XCTAssertEqual(result, .none, "A cache fallback must not be persisted again and extend its TTL")
        XCTAssertEqual(fetchCount, 1)
        guard case .ready(let cached) = model.state else {
            return XCTFail("Expected the compatible offline body")
        }
        XCTAssertEqual(cached.verifiedNativeBody, "Cached body")
    }

    func testCompatibleCacheRemainsAvailableWithoutAccessToken() async {
        let feedArticle = makeArticle(mode: .nativeFullText, body: nil, version: 2)
        let cachedDetail = makeArticle(mode: .nativeFullText, body: "Cached body", version: 2)
        let model = ArticleReaderModel(article: feedArticle) { _, _ in
            XCTFail("Fetch must not start without a token")
            return feedArticle
        }

        let result = await model.load(accessToken: nil, cachedDetail: cachedDetail)

        XCTAssertEqual(result, .none)
        guard case .ready(let cached) = model.state else {
            return XCTFail("Expected the bounded cached body")
        }
        XCTAssertEqual(cached.verifiedNativeBody, "Cached body")
    }

    func testMismatchedDetailIdentityFailsClosed() async {
        let feedArticle = makeArticle(mode: .nativeFullText, body: nil, version: 2)
        var wrongArticle = makeArticle(mode: .nativeFullText, body: "Wrong body", version: 2)
        wrongArticle = NewsArticle(
            id: "different-article",
            title: wrongArticle.title,
            summary: wrongArticle.summary,
            content: nil,
            author: wrongArticle.author,
            source: wrongArticle.source,
            imageURL: wrongArticle.imageURL,
            publishedAt: wrongArticle.publishedAt,
            category: wrongArticle.category,
            url: wrongArticle.url,
            presentation: wrongArticle.presentation
        )
        let model = ArticleReaderModel(article: feedArticle) { _, _ in wrongArticle }

        let result = await model.load(accessToken: "token")

        XCTAssertEqual(result, .none)
        guard case .failed(let retained, let message) = model.state else {
            return XCTFail("Expected failed")
        }
        XCTAssertEqual(retained.id, feedArticle.id)
        XCTAssertTrue(message.localizedCaseInsensitiveContains("mismatched"))
    }

    func testCancellationRestoresPreviewInsteadOfPublishingFailure() async {
        let article = makeArticle(mode: .nativeFullText, body: nil)
        let model = ArticleReaderModel(article: article) { _, _ in
            try await Task.sleep(nanoseconds: 5_000_000_000)
            return article
        }

        let load = Task { await model.load(accessToken: "token") }
        await Task.yield()
        load.cancel()
        _ = await load.value

        guard case .preview(let retained) = model.state else {
            return XCTFail("Expected preview after cancellation")
        }
        XCTAssertEqual(retained.id, article.id)
    }

    private func makeArticle(
        mode: ArticlePresentationMode,
        body: String? = nil,
        version: Int? = 1,
        originalURL: String? = "https://publisher.com/story",
        legacyURL: String? = "https://publisher.com/story",
        provenanceSourceURL: String? = nil
    ) -> NewsArticle {
        var article = NewsArticle(
            id: "article-1",
            title: "A story",
            summary: "Summary",
            content: nil,
            author: nil,
            source: "Publisher",
            imageURL: nil,
            publishedAt: nil,
            category: nil,
            url: legacyURL
        )
        article.presentation = ArticlePresentation(
            mode: mode,
            originalURL: originalURL,
            body: body,
            bodyState: body == nil ? .none : .verifiedFull,
            accessHint: nil,
            reason: nil,
            provenance: version.map {
                ArticleContentProvenance(
                    kind: "origin_extract",
                    sourceURL: provenanceSourceURL ?? originalURL,
                    rightsPolicy: "publisher_permission",
                    completeness: "complete",
                    contentVersion: $0,
                    policyVersion: 1
                )
            },
            offlineValidUntil: Date().addingTimeInterval(3600),
            validatedAt: Date().addingTimeInterval(-1)
        )
        return article
    }
}

@MainActor
final class ArticleCacheStoreTests: XCTestCase {
    func testFeedCacheRoundTripStripsBodiesButKeepsPresentationVersion() throws {
        let suiteName = "ArticleCacheStoreTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let store = ArticleCacheStore(defaults: defaults)
        let serverArticle = makeArticle(mode: .nativeFullText, body: "Do not persist from feed", version: 6)

        let stored = try store.storeFeed([serverArticle], forUserID: "user-a")
        let loaded = store.loadFeed(forUserID: "user-a")

        XCTAssertEqual(stored.count, 1)
        XCTAssertEqual(loaded.count, 1)
        XCTAssertNil(loaded[0].content)
        XCTAssertNil(loaded[0].presentation?.body)
        XCTAssertNil(loaded[0].verifiedNativeBody)
        XCTAssertEqual(loaded[0].presentation?.mode, .nativeFullText)
        XCTAssertEqual(loaded[0].presentation?.provenance?.contentVersion, 6)
    }

    func testVerifiedReaderCacheIsAccountScopedAndExpires() throws {
        let suiteName = "ArticleCacheStoreTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        var clock = Date(timeIntervalSince1970: 1_000)
        let store = ArticleCacheStore(
            defaults: defaults,
            now: { clock },
            readerTimeToLive: 60,
            maximumReaderEntries: 2
        )
        let detail = makeArticle(mode: .nativeFullText, body: "Verified body", version: 3, validatedAt: clock)

        try store.storeVerifiedDetail(detail, forUserID: "user-a")

        XCTAssertEqual(
            store.loadVerifiedDetail(articleID: detail.id, forUserID: "user-a")?.verifiedNativeBody,
            "Verified body"
        )
        XCTAssertNil(store.loadVerifiedDetail(articleID: detail.id, forUserID: "user-b"))

        clock = clock.addingTimeInterval(61)
        XCTAssertNil(store.loadVerifiedDetail(articleID: detail.id, forUserID: "user-a"))
    }

    func testFeedContractRevokesCachedNativeBody() throws {
        let suiteName = "ArticleCacheStoreTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let store = ArticleCacheStore(defaults: defaults)
        let detail = makeArticle(mode: .nativeFullText, body: "Verified body", version: 3)
        try store.storeVerifiedDetail(detail, forUserID: "user-a")
        XCTAssertNotNil(store.loadVerifiedDetail(articleID: detail.id, forUserID: "user-a"))

        let revokedFeedRow = makeArticle(mode: .sourceWeb, body: nil, version: 4)
        try store.storeFeed([revokedFeedRow], forUserID: "user-a")

        XCTAssertNil(store.loadVerifiedDetail(articleID: detail.id, forUserID: "user-a"))
    }

    func testAuthoritativeEmptyFeedReplacesPreviouslyCachedRows() throws {
        let suiteName = "ArticleCacheStoreTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let store = ArticleCacheStore(defaults: defaults)
        let oldArticle = makeArticle(mode: .sourceWeb, body: nil, version: 1)
        try store.storeFeed([oldArticle], forUserID: "user-a")
        XCTAssertEqual(store.loadFeed(forUserID: "user-a").map(\.id), [oldArticle.id])

        try store.storeFeed([], forUserID: "user-a")

        XCTAssertTrue(store.loadFeed(forUserID: "user-a").isEmpty)
    }

    func testFeedPolicyVersionChangeRevokesCachedNativeBody() throws {
        let suiteName = "ArticleCacheStoreTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let store = ArticleCacheStore(defaults: defaults)
        let detail = makeArticle(
            mode: .nativeFullText,
            body: "Verified body",
            version: 3,
            policyVersion: 2
        )
        try store.storeVerifiedDetail(detail, forUserID: "user-a")

        let changedPolicy = makeArticle(
            mode: .nativeFullText,
            body: nil,
            version: 3,
            policyVersion: 3
        )
        try store.storeFeed([changedPolicy], forUserID: "user-a")

        XCTAssertNil(store.loadVerifiedDetail(articleID: detail.id, forUserID: "user-a"))
    }

    func testUnversionedBodyIsNeverPersistedForOfflineReading() throws {
        let suiteName = "ArticleCacheStoreTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let store = ArticleCacheStore(defaults: defaults)
        let unversioned = makeArticle(mode: .nativeFullText, body: "Body", version: nil)

        try store.storeVerifiedDetail(unversioned, forUserID: "user-a")

        XCTAssertNil(store.loadVerifiedDetail(articleID: unversioned.id, forUserID: "user-a"))
    }

    private func makeArticle(
        mode: ArticlePresentationMode,
        body: String?,
        version: Int?,
        policyVersion: Int? = 1,
        validatedAt: Date = Date()
    ) -> NewsArticle {
        var article = NewsArticle(
            id: "article-1",
            title: "A story",
            summary: "Summary",
            content: "legacy body",
            author: nil,
            source: "Publisher",
            imageURL: nil,
            publishedAt: nil,
            category: nil,
            url: "https://publisher.com/story"
        )
        article.presentation = ArticlePresentation(
            mode: mode,
            originalURL: "https://publisher.com/story",
            body: body,
            bodyState: body == nil ? .none : .verifiedFull,
            accessHint: nil,
            reason: nil,
            provenance: version.map {
                ArticleContentProvenance(
                    kind: "origin_extract",
                    sourceURL: "https://publisher.com/story",
                    rightsPolicy: "publisher_permission",
                    completeness: "complete",
                    contentVersion: $0,
                    policyVersion: policyVersion
                )
            },
            offlineValidUntil: validatedAt.addingTimeInterval(3600),
            validatedAt: validatedAt
        )
        return article
    }
}
