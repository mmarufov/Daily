import XCTest
@testable import Daily

@MainActor
final class ReadingEventTrackerTests: XCTestCase {
    func testFlushChunksAndPreservesStableIdentity() async {
        var batches: [[ReadingEventTracker.ReadingEvent]] = []
        let tracker = ReadingEventTracker(tokenProvider: { "a" }, submit: { events, _ in batches.append(events) })
        for index in 0..<205 { tracker.logTap(articleId: String(index)) }
        let original = tracker.pendingEvents.map(\.eventId)
        await tracker.flush()
        XCTAssertEqual(batches.map(\.count), [100, 100, 5])
        XCTAssertEqual(batches.flatMap { $0.map(\.eventId) }, original)
        XCTAssertTrue(tracker.pendingEvents.isEmpty)
    }

    func testFailureRetriesSameIDs() async {
        var fail = true
        var identities: [String] = []
        let tracker = ReadingEventTracker(tokenProvider: { "a" }, submit: { events, _ in
            identities.append(events[0].eventId)
            if fail { throw URLError(.timedOut) }
        })
        tracker.logTap(articleId: "story")
        await tracker.flush()
        XCTAssertEqual(tracker.pendingEvents.count, 1)
        fail = false
        await tracker.flush()
        XCTAssertEqual(identities.count, 2)
        XCTAssertEqual(identities[0], identities[1])
    }

    func testOldFailureCannotRequeueAfterAccountReset() async {
        var tracker: ReadingEventTracker!
        tracker = ReadingEventTracker(tokenProvider: { "same-token" }, submit: { _, _ in
            tracker.discardPending()
            tracker.logTap(articleId: "new-session")
            throw URLError(.timedOut)
        })
        tracker.logTap(articleId: "old-session")
        await tracker.flush()
        XCTAssertEqual(tracker.pendingEvents.map(\.articleId), ["new-session"])
    }

    // MARK: - S10 B1: quick-back / skip

    private func makeArticle(id: String = "article-1") -> NewsArticle {
        NewsArticle(id: id, title: "A story", summary: "Summary", content: "body",
            author: "Author", source: "Publisher", imageURL: nil, publishedAt: nil,
            category: "News", url: "https://publisher.example/story")
    }

    func testLogSkipQueuesASkipTypeEvent() async {
        let tracker = ReadingEventTracker(tokenProvider: { "a" }, submit: { _, _ in })
        tracker.logSkip(article: makeArticle())
        XCTAssertEqual(tracker.pendingEvents.count, 1)
        XCTAssertEqual(tracker.pendingEvents[0].type, "skip")
        XCTAssertNil(tracker.pendingEvents[0].durationSeconds)
    }

    func testLogSkipIsANoopWithoutAnAccessToken() async {
        let tracker = ReadingEventTracker(tokenProvider: { nil }, submit: { _, _ in })
        tracker.logSkip(article: makeArticle())
        XCTAssertTrue(tracker.pendingEvents.isEmpty)
    }

    func testLogSkipDoesNotRequireTheFiveSecondDwellFloorLogReadEnforces() async {
        // Unlike logRead, a skip is meaningful precisely because dwell was
        // short -- it must never be silently dropped the way a <5s read is.
        let tracker = ReadingEventTracker(tokenProvider: { "a" }, submit: { _, _ in })
        tracker.logRead(article: makeArticle(), durationSeconds: 1)
        XCTAssertTrue(tracker.pendingEvents.isEmpty, "a <5s read is correctly dropped")
        tracker.logSkip(article: makeArticle())
        XCTAssertEqual(tracker.pendingEvents.count, 1, "a skip is not subject to the same floor")
    }
}
