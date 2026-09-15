import XCTest
@testable import Daily

@MainActor
final class DeliveryCoordinatorTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_789_000_000)
    private let session = NewsViewModel.Session(userID: "reader", token: "test", generation: 1)
    private func response(sequence: Int64 = 1, ids: [String] = ["story"]) -> BackendService.FeedResponse {
        let id = "00000000-0000-4000-8000-" + String(format: "%012d", sequence)
        let metadata = DeliveryMetadata(version: 1, editionID: id, sequence: sequence,
            publishedAt: now, validatedAt: now, validUntil: now.addingTimeInterval(600),
            readerGeneration: 1, readerRevision: 1)
        let cards = ids.enumerated().map { index, id in
            var card = NewsArticle(id: id, title: id, summary: nil, content: nil, author: nil,
                source: nil, imageURL: nil, publishedAt: nil, category: nil, url: nil)
            card.feedRequestID = metadata.editionID; card.readerGeneration = 1; card.readerRevision = 1
            card.deliveryPosition = index
            return card
        }
        return BackendService.FeedResponse(status: .ready, articles: cards, feedRequestId: id,
            articleCount: cards.count, qualityMet: nil, buildTimeSeconds: nil,
            profileSpecificity: nil, delivery: metadata)
    }
    private func deps(fetch: @escaping (String) async throws -> BackendService.FeedResponse) -> NewsViewModel.Dependencies {
        NewsViewModel.Dependencies(session: { self.session }, fetch: fetch,
            build: { _ in XCTFail("Unexpected build"); throw URLError(.badServerResponse) },
            discover: { _ in XCTFail("Unexpected discovery") }, load: { _ in .missing },
            store: { _, _, _, _ in .stored }, invalidate: {}, now: { self.now })
    }
    func testReadyEmptyReplacesPreviouslyDisplayedMembership() async {
        var next = response()
        let model = NewsViewModel(dependencies: deps(fetch: { _ in next }), startsAutomatically: false)
        await model.loadFeed()
        XCTAssertEqual(model.articles.count, 1)
        next = response(sequence: 2, ids: [])
        await model.refreshFeed()
        XCTAssertTrue(model.articles.isEmpty)
        XCTAssertEqual(model.deliveryStatusLabel, "No matching stories")
    }
    func testOutageDoesNotBuildAndPreservesLabeledSavedCards() async {
        let ready = response()
        var dependency = deps(fetch: { _ in throw URLError(.notConnectedToInternet) })
        dependency.load = { _ in .saved(CachedEdition(version: 1, ownerNamespace: "owner",
            articles: ready.articles, delivery: ready.delivery, receivedAt: self.now)) }
        let model = NewsViewModel(dependencies: dependency, startsAutomatically: false)
        await model.loadFeed()
        XCTAssertEqual(model.articles.count, 1)
        XCTAssertTrue(model.isSavedEdition)
        XCTAssertFalse(model.canAttributeImpressions)
        XCTAssertNil(model.articles.first?.deliveryReceipt)
        XCTAssertEqual(model.editionPublishedAt, now)
    }
    func testLateResponseCannotReplaceNewerRefresh() async {
        var continuation: CheckedContinuation<BackendService.FeedResponse, Error>?
        var calls = 0
        let newer = response(sequence: 2, ids: ["new"])
        let model = NewsViewModel(dependencies: deps(fetch: { _ in
            calls += 1
            if calls == 1 { return try await withCheckedThrowingContinuation { continuation = $0 } }
            return newer
        }), startsAutomatically: false)
        let old = Task { await model.loadFeed() }
        while continuation == nil { await Task.yield() }
        await model.refreshFeed()
        continuation?.resume(returning: response(ids: ["old"]))
        await old.value
        XCTAssertEqual(model.articles.map(\.id), ["new"])
    }
    func testReaderInvalidationFencesResponseAndClearsCache() async {
        var continuation: CheckedContinuation<BackendService.FeedResponse, Error>?
        var invalidations = 0
        var dependency = deps(fetch: { _ in try await withCheckedThrowingContinuation { continuation = $0 } })
        dependency.invalidate = { invalidations += 1 }
        let model = NewsViewModel(dependencies: dependency, startsAutomatically: false)
        let task = Task { await model.loadFeed() }
        while continuation == nil { await Task.yield() }
        model.invalidateForReaderChange(reload: false)
        continuation?.resume(returning: response())
        await task.value
        XCTAssertTrue(model.articles.isEmpty)
        XCTAssertEqual(invalidations, 1)
    }
    func testMetadataRejectsMutationAndOlderSequence() {
        let first = response().delivery!
        XCTAssertFalse(first.canReplace(response(sequence: 2).delivery))
        XCTAssertTrue(response(sequence: 2).delivery!.canReplace(first))
        let invalid = DeliveryMetadata(version: 2, editionID: first.editionID, sequence: 1,
            publishedAt: now, validatedAt: now, validUntil: now.addingTimeInterval(600),
            readerGeneration: 1, readerRevision: 1)
        XCTAssertFalse(invalid.canReplace(nil))
    }
    func testDuplicateMembershipAndMismatchedReceiptsRejected() {
        let value = response(ids: ["a", "a"])
        XCTAssertFalse(DeliveryValidation.accepts(value.delivery, articles: value.articles, requestID: value.feedRequestId))
        let ready = response()
        XCTAssertFalse(DeliveryValidation.accepts(ready.delivery, articles: ready.articles, requestID: UUID().uuidString))
    }
}
