import XCTest
@testable import Daily

final class ArticleCacheMonotonicityTests: XCTestCase {
    func testLateDetailCannotReinsertBodyAfterFeedModeDowngrade() throws {
        try withStore { store in
            let userID = "mode-downgrade-user"
            let requestedContract = makeArticle(mode: .nativeFullText, version: 4, policyVersion: 2)
            try store.storeFeed([requestedContract], forUserID: userID)

            let newestContract = makeArticle(mode: .sourceWeb, version: 5, policyVersion: 3)
            try store.storeFeed([newestContract], forUserID: userID)

            let lateDetail = makeArticle(
                mode: .nativeFullText,
                body: "Stale body",
                version: 4,
                policyVersion: 2
            )
            XCTAssertEqual(
                try store.storeVerifiedDetail(lateDetail, forUserID: userID),
                .rejectedStale
            )
            XCTAssertNil(store.loadVerifiedDetail(articleID: lateDetail.id, forUserID: userID))
        }
    }

    func testLateDetailCannotReinsertArticleAfterAuthoritativeEmptyFeed() throws {
        try withStore { store in
            let userID = "empty-feed-user"
            let requestedContract = makeArticle(mode: .nativeFullText, version: 4, policyVersion: 2)
            try store.storeFeed([requestedContract], forUserID: userID)
            try store.storeFeed([], forUserID: userID)

            let lateDetail = makeArticle(
                mode: .nativeFullText,
                body: "Body for removed article",
                version: 4,
                policyVersion: 2
            )
            XCTAssertEqual(
                try store.storeVerifiedDetail(lateDetail, forUserID: userID),
                .rejectedStale
            )
            XCTAssertNil(store.loadVerifiedDetail(articleID: lateDetail.id, forUserID: userID))
        }
    }

    func testLateDetailCannotOverwriteNewerFeedContentVersion() throws {
        try withStore { store in
            let userID = "content-version-user"
            try store.storeFeed(
                [makeArticle(mode: .nativeFullText, version: 8, policyVersion: 2)],
                forUserID: userID
            )

            let staleDetail = makeArticle(
                mode: .nativeFullText,
                body: "Version seven body",
                version: 7,
                policyVersion: 2
            )
            XCTAssertEqual(
                try store.storeVerifiedDetail(staleDetail, forUserID: userID),
                .rejectedStale
            )
            XCTAssertNil(store.loadVerifiedDetail(articleID: staleDetail.id, forUserID: userID))
        }
    }

    func testLateDetailCannotOverwriteNewerFeedPolicyVersion() throws {
        try withStore { store in
            let userID = "policy-version-user"
            try store.storeFeed(
                [makeArticle(mode: .nativeFullText, version: 7, policyVersion: 4)],
                forUserID: userID
            )

            let staleDetail = makeArticle(
                mode: .nativeFullText,
                body: "Old-policy body",
                version: 7,
                policyVersion: 3
            )
            XCTAssertEqual(
                try store.storeVerifiedDetail(staleDetail, forUserID: userID),
                .rejectedStale
            )
            XCTAssertNil(store.loadVerifiedDetail(articleID: staleDetail.id, forUserID: userID))
        }
    }

    func testNewerDetailCanAdvanceBeyondCurrentFeedContract() throws {
        try withStore { store in
            let userID = "advancing-detail-user"
            try store.storeFeed(
                [makeArticle(mode: .nativeFullText, version: 7, policyVersion: 2)],
                forUserID: userID
            )
            let newerDetail = makeArticle(
                mode: .nativeFullText,
                body: "Version eight body",
                version: 8,
                policyVersion: 2
            )

            XCTAssertEqual(
                try store.storeVerifiedDetail(newerDetail, forUserID: userID),
                .stored
            )
            XCTAssertEqual(
                store.loadVerifiedDetail(articleID: newerDetail.id, forUserID: userID)?
                    .verifiedNativeBody,
                "Version eight body"
            )
        }
    }

    func testExplicitRemovalIsAtomicAndReportsDisposition() throws {
        try withStore { store in
            let userID = "removal-user"
            let detail = makeArticle(
                mode: .nativeFullText,
                body: "Verified body",
                version: 3,
                policyVersion: 1
            )
            XCTAssertEqual(try store.storeVerifiedDetail(detail, forUserID: userID), .stored)

            XCTAssertEqual(
                try store.removeVerifiedDetail(articleID: detail.id, forUserID: userID),
                .removed
            )
            XCTAssertNil(store.loadVerifiedDetail(articleID: detail.id, forUserID: userID))
            XCTAssertEqual(
                try store.removeVerifiedDetail(articleID: detail.id, forUserID: userID),
                .unchanged
            )
        }
    }

    func testConcurrentDetailMutationsDoNotLoseUnrelatedEntries() throws {
        try withStore(maximumReaderEntries: 40) { store in
            let userID = "concurrent-user"
            let queue = DispatchQueue(label: "ArticleCacheMonotonicityTests", attributes: .concurrent)
            let group = DispatchGroup()
            let errorLock = NSLock()
            var errors: [Error] = []

            for index in 0..<12 {
                group.enter()
                queue.async {
                    defer { group.leave() }
                    do {
                        let detail = self.makeArticle(
                            id: "article-\(index)",
                            mode: .nativeFullText,
                            body: "Verified body \(index)",
                            version: 1,
                            policyVersion: 1
                        )
                        try store.storeVerifiedDetail(detail, forUserID: userID)
                    } catch {
                        errorLock.lock()
                        errors.append(error)
                        errorLock.unlock()
                    }
                }
            }

            XCTAssertEqual(group.wait(timeout: .now() + 10), .success)
            XCTAssertTrue(errors.isEmpty)
            for index in 0..<12 {
                XCTAssertEqual(
                    store.loadVerifiedDetail(articleID: "article-\(index)", forUserID: userID)?
                        .verifiedNativeBody,
                    "Verified body \(index)"
                )
            }
        }
    }

    private func withStore(
        maximumReaderEntries: Int = 12,
        operation: (ArticleCacheStore) throws -> Void
    ) throws {
        let suiteName = "ArticleCacheMonotonicityTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suiteName))
        defer { defaults.removePersistentDomain(forName: suiteName) }
        try operation(
            ArticleCacheStore(
                defaults: defaults,
                maximumReaderEntries: maximumReaderEntries
            )
        )
    }

    private func makeArticle(
        id: String = "article-1",
        mode: ArticlePresentationMode,
        body: String? = nil,
        version: Int?,
        policyVersion: Int?
    ) -> NewsArticle {
        var article = NewsArticle(
            id: id,
            title: "A story",
            summary: "Summary",
            content: nil,
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
            offlineValidUntil: Date().addingTimeInterval(3600),
            validatedAt: Date().addingTimeInterval(-1)
        )
        return article
    }
}
