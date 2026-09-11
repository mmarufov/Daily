import XCTest
@testable import Daily

final class DeliveryStorageTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_800_000_000)

    private func metadata(sequence: Int64 = 1, edition: String = "12345678-1234-1234-1234-123456789012") -> DeliveryMetadata {
        .init(version: 1, editionID: edition, sequence: sequence, publishedAt: now,
              validatedAt: now, validUntil: now.addingTimeInterval(900), readerGeneration: 1, readerRevision: 1)
    }

    private func article(grant: Bool = true) -> NewsArticle {
        var value = NewsArticle(id: "article", title: "Title", summary: "Summary", content: nil,
            author: nil, source: "Publisher", imageURL: nil, publishedAt: nil, category: nil,
            url: "https://publisher.com/story")
        value.presentation = ArticlePresentation(mode: .nativeFullText, originalURL: value.url,
            body: "Verified publisher body", bodyState: .verifiedFull,
            provenance: .init(kind: "origin_extract", sourceURL: value.url!, rightsPolicy: "publisher_permission",
                completeness: "complete", contentVersion: 1, policyVersion: 1),
            offlineValidUntil: grant ? now.addingTimeInterval(600) : nil, validatedAt: grant ? now : nil)
        return value
    }

    private func defaults() throws -> UserDefaults {
        try XCTUnwrap(UserDefaults(suiteName: "DeliveryStorageTests.\(UUID().uuidString)"))
    }

    func testEmptyEditionIsSavedNotMissingAndIsAccountBound() async throws {
        let store = ArticleCacheStore(defaults: try defaults(), now: { self.now })
        let result = try await store.storeEdition([], delivery: metadata(), forUserID: "a")
        XCTAssertEqual(result, .stored)
        guard case .saved(let edition) = await store.loadEdition(forUserID: "a") else { return XCTFail("Empty edition was lost") }
        XCTAssertTrue(edition.articles.isEmpty)
        guard case .missing = await store.loadEdition(forUserID: "b") else { return XCTFail("Cross-account cache access") }
    }

    func testOlderPublicationAndLegacyDowngradeCannotReplaceEdition() async throws {
        let store = ArticleCacheStore(defaults: try defaults(), now: { self.now })
        _ = try await store.storeEdition([], delivery: metadata(sequence: 2), forUserID: "a")
        let older = try await store.storeEdition([], delivery: metadata(), forUserID: "a")
        let legacy = try await store.storeEdition([], delivery: nil, forUserID: "a")
        XCTAssertEqual(older, .rejectedStale)
        XCTAssertEqual(legacy, .rejectedStale)
    }

    func testSameSequenceCannotChangeIdentity() async throws {
        let store = ArticleCacheStore(defaults: try defaults(), now: { self.now })
        _ = try await store.storeEdition([], delivery: metadata(), forUserID: "a")
        let changed = try await store.storeEdition([], delivery: metadata(edition: UUID().uuidString), forUserID: "a")
        XCTAssertEqual(changed, .rejectedStale)
    }

    func testSignOutLeaseRejectsLateFeedAndNativeWrites() async throws {
        let store = ArticleCacheStore(defaults: try defaults(), now: { self.now })
        let oldSession = store.lease()
        store.clearAll()
        let feed = try await store.storeEdition([], delivery: metadata(), forUserID: "a", expectedLease: oldSession)
        let detail = try await store.storeDetail(article(), forUserID: "a", expectedLease: oldSession)
        XCTAssertEqual(feed, .rejectedStale)
        XCTAssertEqual(detail, .rejectedStale)
    }

    func testSessionRotationFencesWritesWithoutDiscardingSavedEdition() async throws {
        let store = ArticleCacheStore(defaults: try defaults(), now: { self.now })
        _ = try await store.storeEdition([], delivery: metadata(), forUserID: "a")
        let oldSession = store.lease()
        store.invalidatePendingWrites()
        let result = try await store.storeEdition([], delivery: metadata(sequence: 2, edition: UUID().uuidString), forUserID: "a", expectedLease: oldSession)
        XCTAssertEqual(result, .rejectedStale)
        guard case .saved(let edition) = await store.loadEdition(forUserID: "a") else { return XCTFail("Saved edition deleted") }
        XCTAssertEqual(edition.delivery?.sequence, 1)
    }

    func testNativeOfflineGrantDefaultsToDeny() throws {
        let store = ArticleCacheStore(defaults: try defaults(), now: { self.now })
        XCTAssertEqual(try store.storeVerifiedDetail(article(grant: false), forUserID: "a"), .ignoredInvalid)
        XCTAssertNil(store.loadVerifiedDetail(articleID: "article", forUserID: "a"))
    }

    func testOnlineOnlyResponseStillChecksMembershipAndRevokesOldGrant() throws {
        let store = ArticleCacheStore(defaults: try defaults(), now: { self.now })
        XCTAssertEqual(try store.storeVerifiedDetail(article(), forUserID: "a"), .stored)
        XCTAssertEqual(try store.storeVerifiedDetail(article(grant: false), forUserID: "a"), .ignoredInvalid)
        XCTAssertNil(store.loadVerifiedDetail(articleID: "article", forUserID: "a"))
        _ = try store.storeFeed([], forUserID: "a")
        XCTAssertEqual(try store.storeVerifiedDetail(article(grant: false), forUserID: "a"), .rejectedStale)
    }

    func testNativeGrantExpiresWithoutRenewalOnRead() throws {
        var clock = now
        let store = ArticleCacheStore(defaults: try defaults(), now: { clock })
        XCTAssertEqual(try store.storeVerifiedDetail(article(), forUserID: "a"), .stored)
        clock = now.addingTimeInterval(599)
        XCTAssertNotNil(store.loadVerifiedDetail(articleID: "article", forUserID: "a"))
        clock = now.addingTimeInterval(601)
        XCTAssertNil(store.loadVerifiedDetail(articleID: "article", forUserID: "a"))
    }

    func testClockRollbackAcrossStoreInstancesCannotRestoreGrant() throws {
        let defaults = try defaults()
        var clock = now
        let first = ArticleCacheStore(defaults: defaults, now: { clock })
        XCTAssertEqual(try first.storeVerifiedDetail(article(), forUserID: "a"), .stored)
        clock = now.addingTimeInterval(300)
        XCTAssertNotNil(first.loadVerifiedDetail(articleID: "article", forUserID: "a"))
        clock = now
        let restarted = ArticleCacheStore(defaults: defaults, now: { clock })
        XCTAssertNil(restarted.loadVerifiedDetail(articleID: "article", forUserID: "a"))
    }

    func testMetadataExpiresAfterSevenDays() async throws {
        var clock = now
        let store = ArticleCacheStore(defaults: try defaults(), now: { clock })
        _ = try await store.storeEdition([], delivery: metadata(), forUserID: "a")
        clock = now.addingTimeInterval(7 * 86400)
        guard case .missing = await store.loadEdition(forUserID: "a") else { return XCTFail("Expired metadata remains eligible") }
    }

    func testFileStorageSurvivesRestartAndRejectsCorruptFile() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("DailyStorageTests-\(UUID())")
        defer { try? FileManager.default.removeItem(at: directory) }
        let defaults = try defaults()
        let first = ArticleCacheStore(defaults: defaults, now: { self.now }, directory: directory)
        _ = try await first.storeEdition([], delivery: metadata(), forUserID: "a")
        let restarted = ArticleCacheStore(defaults: defaults, now: { self.now }, directory: directory)
        guard case .saved = await restarted.loadEdition(forUserID: "a") else { return XCTFail("Atomic snapshot lost on restart") }
        let file = directory.appendingPathComponent("\(ArticleCacheStore.prefix).\(ArticleCacheStore.namespace(for: "a")).articles.json")
        try Data("broken".utf8).write(to: file, options: .atomic)
        guard case .corrupt = await restarted.loadEdition(forUserID: "a") else { return XCTFail("Corrupt data appeared empty") }
    }
}

final class DeliveryBookmarkStorageTests: XCTestCase {
    func testSignOutBarrierRejectsLateSaveAndAllowsNewSession() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("DailyBookmarkTests-\(UUID())")
        defer { try? FileManager.default.removeItem(at: directory) }
        let disk = BookmarkDiskStore(directory: directory)
        let old = disk.lease()
        disk.save(.init(owner: "a", bookmarks: [], readIDs: ["old"]), lease: old)
        disk.clear()
        disk.save(.init(owner: "a", bookmarks: [], readIDs: ["resurrected"]), lease: old)
        let fresh = disk.lease()
        disk.save(.init(owner: "a", bookmarks: [], readIDs: ["new"]), lease: fresh)
        await disk.drain()
        let result = await disk.load(owner: "a", lease: fresh)
        XCTAssertEqual(result?.readIDs, ["new"])
        let rejected = await disk.load(owner: "a", lease: old)
        XCTAssertNil(rejected)
    }

    func testSavesAreFIFOAndAccountScoped() async throws {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("DailyBookmarkTests-\(UUID())")
        defer { try? FileManager.default.removeItem(at: directory) }
        let disk = BookmarkDiskStore(directory: directory)
        let lease = disk.lease()
        disk.save(.init(owner: "a", bookmarks: [], readIDs: ["one"]), lease: lease)
        disk.save(.init(owner: "a", bookmarks: [], readIDs: ["two"]), lease: lease)
        await disk.drain()
        let a = await disk.load(owner: "a", lease: lease)
        let b = await disk.load(owner: "b", lease: lease)
        XCTAssertEqual(a?.readIDs, ["two"])
        XCTAssertEqual(b?.readIDs, [])
    }
}
