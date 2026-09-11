import XCTest
@testable import Daily

@MainActor
final class EditionReceiptTests: XCTestCase {
    private let edition = "8bbc2235-f4d6-4193-af3f-3f197ea88970"

    private func card() throws -> NewsArticle {
        // Shared with backend publication tests; no separately hand-maintained wire shape.
        let fixture = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .appendingPathComponent("Fixtures/s8-edition.json")
        let response = try JSONDecoder().decode(BackendService.FeedResponse.self, from: Data(contentsOf: fixture))
        XCTAssertEqual(response.articles.first?.id, "story-0")
        XCTAssertNil(response.articles.first?.image)
        return try XCTUnwrap(response.articles.last)
    }

    func testFeedRequestBuilderAdvertisesEditionContractWithoutS4Capability() throws {
        for (path, method) in [("/feed", "GET"), ("/feed/build", "POST"), ("/feed/refresh", "POST")] {
            let url = try XCTUnwrap(URL(string: "https://daily.example\(path)?limit=50"))
            let request = BackendService.editionRequest(url: url, accessToken: "test-token", method: method)
            XCTAssertEqual(request.value(forHTTPHeaderField: "X-Daily-Edition-Version"), "1")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer test-token")
            XCTAssertEqual(request.httpMethod, method)
            XCTAssertEqual(request.url, url)
            XCTAssertNil(request.value(forHTTPHeaderField: "X-Daily-Event-Delivery-Version"))
        }
    }

    func testDecoderNormalizationMergeAndFeedCachePreserveOriginalIdentity() throws {
        let original = try card()
        var detail = original
        detail.readerGeneration = 99
        detail.feedRequestID = UUID().uuidString
        detail.deliveryPosition = 0
        let merged = original.normalizedForDisplay().mergingReaderDetail(detail).safeForReaderCache()
        let decoded = try JSONDecoder().decode(NewsArticle.self, from: JSONEncoder().encode(merged))
        XCTAssertEqual(decoded.readerGeneration, 3)
        XCTAssertEqual(decoded.readerRevision, 7)
        XCTAssertEqual(decoded.deliveryReceipt?.requestID, edition)
        XCTAssertEqual(decoded.deliveryReceipt?.position, 4)
    }

    func testFeedbackPayloadUsesStampedCardPositionAndGeneration() throws {
        let article = try card().normalizedForDisplay().safeForReaderCache()
        let receipt = try XCTUnwrap(article.deliveryReceipt)
        let body = BackendService.feedFeedbackBody(articleID: article.id, action: "not_relevant",
            feedRequestID: receipt.requestID, position: receipt.position,
            eventID: UUID().uuidString, readerGeneration: article.readerGeneration)
        let data = try JSONSerialization.data(withJSONObject: body)
        let wire = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(wire["reader_generation"] as? Int, 3)
        XCTAssertEqual(wire["position"] as? Int, 4)
        XCTAssertEqual(wire["feed_request_id"] as? String, edition)
    }

    func testPersistentFeedCacheRetainsReceiptAndAccountBoundary() throws {
        let suiteName = "EditionReceiptTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        let store = ArticleCacheStore(defaults: defaults)
        try store.storeFeed([card()], forUserID: "reader-a")
        let cached = try XCTUnwrap(store.loadFeed(forUserID: "reader-a").first)
        XCTAssertEqual(cached.deliveryReceipt?.requestID, edition)
        XCTAssertEqual(cached.deliveryReceipt?.position, 4)
        XCTAssertEqual(cached.readerGeneration, 3)
        XCTAssertTrue(store.loadFeed(forUserID: "reader-b").isEmpty)
    }

    func testInvalidReceiptIsNotAttributed() throws {
        let original = try card()
        var invalidID = original
        invalidID.feedRequestID = "not-an-edition"
        var negativePosition = original
        negativePosition.deliveryPosition = -1
        var missingRevision = original
        missingRevision.readerRevision = nil
        for value in [invalidID, negativePosition, missingRevision] {
            XCTAssertNil(value.deliveryReceipt)
        }
    }

    func testBackgroundEditionAndLocalHideCannotRewriteReceipt() async throws {
        let tracker = ReadingEventTracker(tokenProvider: { "test-token" }, submit: { _, _ in })
        let displayed = try card()
        var backgroundCard = displayed
        backgroundCard.feedRequestID = UUID().uuidString
        backgroundCard.deliveryPosition = 0
        tracker.logImpression(article: backgroundCard)
        // Displayed card is now UI index zero after a hide, but delivery position remains four.
        tracker.logTap(article: displayed)
        tracker.logRead(article: displayed, durationSeconds: 12)
        for event in tracker.pendingEvents.suffix(2) {
            XCTAssertEqual(event.feedRequestId, edition)
            XCTAssertEqual(event.position, 4)
        }
    }

    func testStandaloneOrPartialReceiptCannotLearnEditionNovelty() async throws {
        let tracker = ReadingEventTracker(tokenProvider: { "test-token" }, submit: { _, _ in })
        let original = try card()
        var partial = original
        partial.deliveryPosition = nil
        tracker.logTap(article: original.withoutFeedReceipt())
        tracker.logRead(article: partial, durationSeconds: 8)
        tracker.logTap(articleId: "legacy", position: 0)
        XCTAssertTrue(tracker.pendingEvents.allSatisfy { $0.feedRequestId == nil && $0.position == nil })
        XCTAssertNil(original.withoutFeedReceipt().readerGeneration)
    }

    func testBusyUnavailableAndReadyEmptyDecodeDistinctly() throws {
        for (status, expected) in [("building", BackendService.FeedStatus.building),
                                   ("unavailable", .unavailable), ("ready", .ready)] {
            let json = "{\"status\":\"\(status)\",\"articles\":[],\"retry_after_seconds\":5}"
            let result = try JSONDecoder().decode(BackendService.FeedResponse.self, from: Data(json.utf8))
            XCTAssertEqual(result.status, expected)
            XCTAssertTrue(result.articles.isEmpty)
        }
    }

    private func nativeCard(hash: String, version: Int, body: String?) throws -> NewsArticle {
        let source = try card()
        // S2 intentionally rejects reserved .example publisher origins.
        var article = NewsArticle(id: source.id, title: source.title, summary: source.summary,
            content: nil, author: nil, source: "Publisher", imageURL: nil,
            publishedAt: nil, category: nil, url: "https://publisher.com/story")
        article.readerGeneration = source.readerGeneration
        article.readerRevision = source.readerRevision
        article.feedRequestID = source.feedRequestID
        article.deliveryPosition = source.deliveryPosition
        article.presentation = ArticlePresentation(mode: .nativeFullText,
            originalURL: article.url, body: body, bodyState: body == nil ? .none : .verifiedFull,
            accessHint: nil, reason: nil,
            provenance: ArticleContentProvenance(kind: "origin_extract", sourceURL: article.url,
                contentHash: hash, rightsPolicy: "publisher_permission", completeness: "complete",
                contentVersion: version, policyVersion: 1))
        return article
    }

    func testReadTracksActuallyLoadedContentNotOriginalReceiptContent() async throws {
        let c1 = String(repeating: "a", count: 64)
        let c2 = String(repeating: "b", count: 64)
        let original = try nativeCard(hash: c1, version: 1, body: nil)
        let detail = try nativeCard(hash: c2, version: 2, body: "New publisher development.")
        let model = ArticleReaderModel(article: original, fetchArticle: { _, _ in detail })
        XCTAssertFalse(model.state.isDisplayingNativeBody)
        _ = await model.load(accessToken: "test-token")
        XCTAssertTrue(model.state.isDisplayingNativeBody)
        let tracker = ReadingEventTracker(tokenProvider: { "test-token" }, submit: { _, _ in })
        tracker.logRead(article: model.state.article, durationSeconds: 12,
                        nativeBodyWasDisplayed: model.state.isDisplayingNativeBody)
        let event = try XCTUnwrap(tracker.pendingEvents.last)
        XCTAssertEqual(event.readContentHash, c2)
        XCTAssertEqual(event.feedRequestId, edition)
        XCTAssertEqual(event.position, 4)
        let payload = try XCTUnwrap(BackendService.readingEventsBody([event])["events"] as? [[String: Any]])
        XCTAssertEqual(payload[0]["read_content_hash"] as? String, c2)
    }

    func testLoadingPreviewSourceWebAndMalformedHashHaveNoReadProof() async throws {
        let hash = String(repeating: "a", count: 64)
        let body = try nativeCard(hash: hash, version: 1, body: "Publisher report.")
        let preview = try nativeCard(hash: hash, version: 1, body: nil)
        let malformed = try nativeCard(hash: "not-a-content-hash", version: 1, body: "Publisher report.")
        var sourceWeb = body
        sourceWeb.presentation = ArticlePresentation(mode: .sourceWeb,
            originalURL: body.url, body: "Analysis text, not displayed native content.", bodyState: .verifiedFull,
            accessHint: nil, reason: nil, provenance: body.presentation?.provenance)
        let tracker = ReadingEventTracker(tokenProvider: { "test-token" }, submit: { _, _ in })
        let states: [ArticleReaderState] = [.loading(body), .preview(preview),
            .sourceAvailable(sourceWeb, message: "Open publisher"), .ready(malformed)]
        for state in states {
            tracker.logRead(article: state.article, durationSeconds: 10,
                            nativeBodyWasDisplayed: state.isDisplayingNativeBody)
        }
        tracker.logRead(articleId: "legacy", durationSeconds: 10)
        tracker.logTap(article: body)
        XCTAssertTrue(tracker.pendingEvents.allSatisfy { $0.readContentHash == nil })
        let payload = try XCTUnwrap(BackendService.readingEventsBody(tracker.pendingEvents)["events"] as? [[String: Any]])
        XCTAssertTrue(payload.allSatisfy { $0["read_content_hash"] == nil })
    }
}
