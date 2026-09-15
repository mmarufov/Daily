import XCTest
@testable import Daily

@MainActor
final class DeliveryReaderLifecycleTests: XCTestCase {
    private func article(body: String? = nil, leased: Bool = false) -> NewsArticle {
        var result = NewsArticle(id: "story", title: "Publisher report", summary: nil,
            content: nil, author: nil, source: "Publisher", imageURL: nil,
            publishedAt: nil, category: nil, url: "https://publisher.com/story")
        result.presentation = ArticlePresentation(mode: .nativeFullText, originalURL: result.url,
            body: body, bodyState: .verifiedFull,
            provenance: ArticleContentProvenance(kind: "origin_extract", sourceURL: result.url,
                contentHash: String(repeating: "a", count: 64), rightsPolicy: "publisher_permission",
                completeness: "complete", contentVersion: 1, policyVersion: 1),
            offlineValidUntil: leased ? Date().addingTimeInterval(600) : nil,
            validatedAt: leased ? Date().addingTimeInterval(-1) : nil)
        return result
    }
    func testSavedBodyDisplaysBeforeNetworkCompletes() async {
        var resume: CheckedContinuation<NewsArticle, Error>?
        let model = ArticleReaderModel(article: article(), fetchArticle: { _, _ in
            try await withCheckedThrowingContinuation { resume = $0 }
        })
        let saved = article(body: "Saved publisher body", leased: true)
        let task = Task { await model.load(accessToken: "token", cachedDetail: saved, revalidate: true) }
        while resume == nil { await Task.yield() }
        XCTAssertTrue(model.state.isDisplayingNativeBody)
        XCTAssertTrue(model.isSavedBody)
        resume?.resume(throwing: URLError(.notConnectedToInternet))
        _ = await task.value
        XCTAssertTrue(model.state.isDisplayingNativeBody)
    }
    func testMissingGrantNeverMakesOfflineBodyEligible() async {
        let model = ArticleReaderModel(article: article(), fetchArticle: { _, _ in throw URLError(.notConnectedToInternet) })
        _ = await model.load(accessToken: nil, cachedDetail: article(body: "Ungrantable body"))
        XCTAssertFalse(model.state.isDisplayingNativeBody)
    }
    func testExpiryIsRetryableAndDoesNotRejectFreshRevalidation() async {
        var resume: CheckedContinuation<NewsArticle, Error>?
        let model = ArticleReaderModel(article: article(), fetchArticle: { _, _ in
            try await withCheckedThrowingContinuation { resume = $0 }
        })
        let task = Task { await model.load(accessToken: "token", cachedDetail: article(body: "Saved body", leased: true)) }
        while resume == nil { await Task.yield() }
        model.expireDisplayedBody()
        XCTAssertFalse(model.state.isDisplayingNativeBody)
        resume?.resume(returning: article(body: "Fresh response"))
        _ = await task.value
        XCTAssertEqual(model.state.article.verifiedNativeBody, "Fresh response")
        model.expireDisplayedBody()
        XCTAssertTrue(model.state.canRetry)
    }
    func testInvalidateAllowsRetryBeforeCancelledTransportCompletes() async {
        var resume: CheckedContinuation<NewsArticle, Error>?
        var calls = 0
        let newer = article(body: "New response")
        let model = ArticleReaderModel(article: article(), fetchArticle: { _, _ in
            calls += 1
            if calls == 1 { return try await withCheckedThrowingContinuation { resume = $0 } }
            return newer
        })
        let old = Task { await model.load(accessToken: "token") }
        while resume == nil { await Task.yield() }
        old.cancel(); model.invalidate()
        _ = await model.load(accessToken: "token")
        resume?.resume(returning: article(body: "Old response"))
        _ = await old.value
        XCTAssertEqual(model.state.article.verifiedNativeBody, "New response")
    }
    func testAccountChangeRejectsLateDisplayAndPersistence() async {
        var ownerCurrent = true
        var resume: CheckedContinuation<NewsArticle, Error>?
        var stores = 0
        let model = ArticleReaderModel(article: article(), fetchArticle: { _, _ in
            try await withCheckedThrowingContinuation { resume = $0 }
        })
        let task = Task { await model.load(accessToken: "token", isCurrent: { ownerCurrent }, accept: { _ in stores += 1; return true }) }
        while resume == nil { await Task.yield() }
        ownerCurrent = false; model.invalidate()
        resume?.resume(returning: article(body: "Late body"))
        _ = await task.value
        XCTAssertFalse(model.state.isDisplayingNativeBody)
        XCTAssertEqual(stores, 0)
    }
    func testPersistenceFenceRejectsBodyBeforeDisplay() async {
        let body = article(body: "Revoked while loading")
        let model = ArticleReaderModel(article: article(), fetchArticle: { _, _ in body })
        _ = await model.load(accessToken: "token", accept: { _ in false })
        XCTAssertFalse(model.state.isDisplayingNativeBody)
    }
    func testAuthenticationFailureEvictsSavedBody() async {
        let model = ArticleReaderModel(article: article(), fetchArticle: { _, _ in
            throw NSError(domain: "BackendService", code: 401)
        })
        var evicted = false
        _ = await model.load(accessToken: "token", cachedDetail: article(body: "Saved body", leased: true), accept: {
            if case .evict = $0 { evicted = true }; return true
        })
        XCTAssertTrue(evicted)
        XCTAssertFalse(model.state.isDisplayingNativeBody)
    }
}
