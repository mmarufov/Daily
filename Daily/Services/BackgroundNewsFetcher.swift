//
//  BackgroundNewsFetcher.swift
//  Daily
//
//  Created by AI on 11/14/25.
//

import Foundation
import Combine
import CryptoKit
import UIKit

/// Persistent article storage with an explicit account namespace. Feed metadata
/// and permitted native bodies are separate so a new source-only feed contract
/// can invalidate a previously cached body without relying on text length.
nonisolated enum ArticleCacheMutationDisposition: Equatable {
    case stored
    case removed
    case rejectedStale
    case ignoredInvalid
    case unchanged
}

nonisolated struct CachedEdition: Codable, Sendable {
    let version: Int
    let ownerNamespace: String
    let articles: [NewsArticle]
    let delivery: DeliveryMetadata?
    let receivedAt: Date
}

nonisolated enum CachedEditionLoad: Sendable {
    case missing, corrupt, unavailable
    case saved(CachedEdition)
}

nonisolated final class ArticleCacheStore: @unchecked Sendable {
    private struct ReaderEntry: Codable {
        let article: NewsArticle
        let cachedAt: Date
    }

    static let prefix = "BackgroundNewsFetcher.v3"
    static let legacyFeedArticles = "BackgroundNewsFetcher.feedArticles"
    static let legacyLastFetchDate = "BackgroundNewsFetcher.lastFetchDate"

    private let defaults: UserDefaults
    private let now: () -> Date
    private let readerTimeToLive: TimeInterval
    private let maximumReaderEntries: Int
    private let maximumBodyBytes = 1_000_000
    /// Every UserDefaults read-modify-write sequence must share this lock. The
    /// foreground reader and background URLSession callback can otherwise race
    /// and resurrect a body that a newer feed contract already revoked.
    private let lock = NSRecursiveLock()
    private let queue = DispatchQueue(label: "Daily.article-storage", qos: .utility)
    private let directory: URL?
    private var generation: UInt64 = 0
    private let launchedAt = Date()
    private let launchedUptime = ProcessInfo.processInfo.systemUptime

    func lease() -> UInt64 { withLock { generation } }
    func invalidatePendingWrites() { withLock { generation &+= 1 } }

    init(
        defaults: UserDefaults = .standard,
        now: @escaping () -> Date = Date.init,
        readerTimeToLive: TimeInterval = 24 * 60 * 60,
        maximumReaderEntries: Int = 12,
        directory: URL? = nil
    ) {
        self.defaults = defaults
        self.now = now
        self.readerTimeToLive = min(24 * 60 * 60, max(0, readerTimeToLive))
        self.maximumReaderEntries = min(12, max(0, maximumReaderEntries))
        self.directory = directory ?? (defaults === UserDefaults.standard
            ? FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first?
                .appendingPathComponent("DailyArticleCache", isDirectory: true) : nil)
    }

    static func namespace(for userID: String) -> String {
        let digest = SHA256.hash(data: Data(userID.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
        return String(digest.prefix(24))
    }

    func removeUnownedLegacyCache() {
        // These keys lack ownership. Ignore them, but leave them recoverable;
        // never silently assign them to the next authenticated account.
    }

    func loadFeed(forUserID userID: String) -> [NewsArticle] {
        withLock {
            loadFeedUnlocked(forUserID: userID)
        }
    }

    private func loadFeedUnlocked(forUserID userID: String) -> [NewsArticle] {
        if case .saved(let edition) = loadEditionUnlocked(forUserID: userID) {
            return edition.articles
        }
        return []
    }

    private func loadEditionUnlocked(forUserID userID: String) -> CachedEditionLoad {
        let key = feedKey(forUserID: userID)
        do {
            guard let data = try readData(key) else {
                // Only account-bound legacy metadata can be recovered. Never
                // migrate old native bodies or assign global files a new owner.
                guard directory != nil, let legacy = defaults.data(forKey: key),
                      legacy.count <= 2_000_000,
                      let articles = try? BackendService.iso8601Decoder.decode([NewsArticle].self, from: legacy),
                      let received = defaults.object(forKey: lastFetchKey(forUserID: userID)) as? Date,
                      received <= now(), now().timeIntervalSince(received) < 7 * 86400 else { return .missing }
                return .saved(CachedEdition(version: 1, ownerNamespace: Self.namespace(for: userID),
                    articles: Array(articles.prefix(100)).map { $0.safeForReaderCache().withoutFeedReceipt() },
                    delivery: nil, receivedAt: received))
            }
            guard data.count <= 2_000_000 else { return .corrupt }
            if let edition = try? BackendService.iso8601Decoder.decode(CachedEdition.self, from: data) {
                guard edition.version == 1, edition.ownerNamespace == Self.namespace(for: userID),
                      edition.articles.count <= 100,
                      DeliveryValidation.accepts(edition.delivery, articles: edition.articles,
                          requestID: edition.delivery?.editionID) else { return .corrupt }
                guard edition.receivedAt <= now(), now().timeIntervalSince(edition.receivedAt) < 7 * 86400 else { return .missing }
                return .saved(CachedEdition(version: edition.version, ownerNamespace: edition.ownerNamespace,
                    articles: edition.articles.map { $0.safeForReaderCache() }, delivery: edition.delivery,
                    receivedAt: edition.receivedAt))
            }
            // Compatibility for old test fixtures; migrated snapshots have no
            // current-edition authority and retain their original receive date.
            let articles = try BackendService.iso8601Decoder.decode([NewsArticle].self, from: data)
            guard DeliveryValidation.accepts(nil, articles: articles, requestID: nil),
                  let received = defaults.object(forKey: lastFetchKey(forUserID: userID)) as? Date,
                  received <= now(), now().timeIntervalSince(received) < 7 * 86400 else { return .missing }
            return .saved(CachedEdition(version: 1, ownerNamespace: Self.namespace(for: userID),
                articles: articles.map { $0.safeForReaderCache() }, delivery: nil, receivedAt: received))
        } catch let error as CocoaError where error.code == .fileReadNoPermission {
            return .unavailable
        } catch {
            return .corrupt
        }
    }

    @discardableResult
    func storeFeed(_ articles: [NewsArticle], forUserID userID: String) throws -> [NewsArticle] {
        try withLock {
            let safeArticles = articles.map { $0.safeForReaderCache() }
            let encoded = try Self.encoder.encode(CachedEdition(version: 1,
                ownerNamespace: Self.namespace(for: userID), articles: safeArticles,
                delivery: nil, receivedAt: now()))
            guard safeArticles.count <= 100, encoded.count <= 2_000_000 else { throw CocoaError(.fileWriteOutOfSpace) }

            // A fresh source-only/unavailable contract revokes any older offline body.
            // This prune and the feed write are one serialized mutation so a late
            // detail result must observe this contract before it can be persisted.
            let articleContracts = Dictionary(
                safeArticles.map { ($0.id, $0) },
                uniquingKeysWith: { _, newest in newest }
            )
            var entries = loadReaderEntriesUnlocked(forUserID: userID)
            entries.removeAll { entry in
                guard let current = articleContracts[entry.article.id] else { return true }
                return current.mergingCompatibleCachedDetail(entry.article) == nil
            }
            let readerData = try encodedReaderEntries(entries)

            try writeData(encoded, key: feedKey(forUserID: userID))
            defaults.set(now(), forKey: lastFetchKey(forUserID: userID))
            saveEncodedReaderEntries(readerData, forUserID: userID)
            return safeArticles
        }
    }

    func loadVerifiedDetail(articleID: String, forUserID userID: String) -> NewsArticle? {
        withLock {
            let detail = loadReaderEntriesUnlocked(forUserID: userID)
                .first(where: { $0.article.id == articleID })?
                .article
                .safeForReaderCache(includeVerifiedNativeBody: true)
                .withoutFeedReceipt()
            guard let detail else { return nil }
            if (try? readData(feedKey(forUserID: userID))) != nil {
                guard let contract = loadFeedUnlocked(forUserID: userID).first(where: { $0.id == articleID }),
                      contract.readerRoute == .native, contract.acceptsReaderDetail(detail) else { return nil }
            }
            return detail
        }
    }

    /// Atomically compares a verified detail with the latest persisted feed
    /// contract and stores it only while that contract still permits the body.
    @discardableResult
    func storeVerifiedDetail(
        _ article: NewsArticle,
        forUserID userID: String
    ) throws -> ArticleCacheMutationDisposition {
        guard let body = article.verifiedNativeBody,
              (article.presentation?.provenance?.contentVersion ?? 0) > 0,
              (article.presentation?.provenance?.policyVersion ?? 0) > 0,
              body.utf8.count <= maximumBodyBytes,
              maximumReaderEntries > 0 else {
            return .ignoredInvalid
        }

        let safeArticle = article.safeForReaderCache(includeVerifiedNativeBody: true).withoutFeedReceipt()
        return try withLock {
            // Once any feed snapshot has been persisted, it is authoritative
            // for membership as well as presentation. An empty snapshot or a
            // refresh that omits this article must fence a late detail result.
            if (try readData(feedKey(forUserID: userID))) != nil {
                guard let currentFeedContract = loadFeedUnlocked(forUserID: userID)
                    .first(where: { $0.id == safeArticle.id }) else {
                    return .rejectedStale
                }
                guard currentFeedContract.readerRoute == .native,
                      currentFeedContract.acceptsReaderDetail(safeArticle) else {
                    return .rejectedStale
                }
            }

            var entries = loadReaderEntriesUnlocked(forUserID: userID)
            if let currentDetail = entries.first(where: { $0.article.id == safeArticle.id }),
               !currentDetail.article.acceptsReaderDetail(safeArticle) {
                return .rejectedStale
            }

            // Even online-only bodies must pass current membership/version fences.
            // A removed offline grant also revokes any previously stored copy.
            guard hasUsableOfflineGrant(article, at: now()) else {
                entries.removeAll { $0.article.id == safeArticle.id }
                try saveReaderEntriesUnlocked(entries, forUserID: userID)
                return .ignoredInvalid
            }

            entries.removeAll { $0.article.id == safeArticle.id }
            entries.insert(ReaderEntry(article: safeArticle, cachedAt: now()), at: 0)
            try saveReaderEntriesUnlocked(
                Array(entries.prefix(maximumReaderEntries)),
                forUserID: userID
            )
            return .stored
        }
    }

    @discardableResult
    func removeVerifiedDetail(
        articleID: String,
        forUserID userID: String
    ) throws -> ArticleCacheMutationDisposition {
        try withLock {
            var entries = loadReaderEntriesUnlocked(forUserID: userID)
            let previousCount = entries.count
            entries.removeAll { $0.article.id == articleID }
            guard entries.count != previousCount else { return .unchanged }
            try saveReaderEntriesUnlocked(entries, forUserID: userID)
            return .removed
        }
    }

    func clearAll() {
        withLock {
            generation &+= 1
            if let directory { try? FileManager.default.removeItem(at: directory) }
            for key in defaults.dictionaryRepresentation().keys where key.hasPrefix(Self.prefix) {
                defaults.removeObject(forKey: key)
            }
            defaults.removeObject(forKey: Self.legacyFeedArticles)
            defaults.removeObject(forKey: Self.legacyLastFetchDate)
        }
    }

    private func loadReaderEntriesUnlocked(forUserID userID: String) -> [ReaderEntry] {
        let key = readerKey(forUserID: userID)
        do {
            guard let data = try readData(key), data.count <= 13_000_000 else { return [] }
            let cutoff = now().addingTimeInterval(-readerTimeToLive)
            let decoded = try BackendService.iso8601Decoder.decode([ReaderEntry].self, from: data)
            let entries = Array(decoded.filter {
                $0.cachedAt >= cutoff && $0.cachedAt <= now() && $0.article.verifiedNativeBody != nil
                    && self.hasUsableOfflineGrant($0.article, at: self.now())
                    && ($0.article.verifiedNativeBody?.utf8.count ?? Int.max) <= self.maximumBodyBytes
            }.prefix(maximumReaderEntries))
            if entries.count != decoded.count { try? saveReaderEntriesUnlocked(entries, forUserID: userID) }
            return entries
        } catch {
            defaults.removeObject(forKey: key)
            return []
        }
    }

    private func saveReaderEntriesUnlocked(
        _ entries: [ReaderEntry],
        forUserID userID: String
    ) throws {
        try writeData(try encodedReaderEntries(entries), key: readerKey(forUserID: userID))
    }

    private func encodedReaderEntries(_ entries: [ReaderEntry]) throws -> Data? {
        guard !entries.isEmpty else { return nil }
        let data = try Self.encoder.encode(entries)
        guard data.count <= 13_000_000 else { throw CocoaError(.fileWriteOutOfSpace) }
        return data
    }

    private func saveEncodedReaderEntries(_ data: Data?, forUserID userID: String) {
        let key = readerKey(forUserID: userID)
        try? writeData(data, key: key)
    }

    private func readData(_ key: String) throws -> Data? {
        guard let directory else { return defaults.data(forKey: key) }
        let file = directory.appendingPathComponent(key + ".json")
        do {
            let maximum = key.hasSuffix("readerArticles") ? 13_000_000 : 2_000_000
            guard let size = try file.resourceValues(forKeys: [.fileSizeKey]).fileSize,
                  size <= maximum else { throw CocoaError(.fileReadCorruptFile) }
            return try Data(contentsOf: file, options: .mappedIfSafe)
        }
        catch let error as CocoaError where error.code == .fileReadNoSuchFile { return nil }
    }

    private func writeData(_ data: Data?, key: String) throws {
        guard let directory else { defaults.set(data, forKey: key); return }
        let file = directory.appendingPathComponent(key + ".json")
        guard let data else {
            if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
            return
        }
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
            attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication])
        var protectedDirectory = directory
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try protectedDirectory.setResourceValues(values)
        try data.write(to: file, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }

    func loadEdition(forUserID userID: String) async -> CachedEditionLoad {
        let captured = withLock { generation }
        return await withCheckedContinuation { continuation in
            queue.async {
                continuation.resume(returning: self.withLock {
                    guard captured == self.generation else { return .missing }
                    return self.loadEditionUnlocked(forUserID: userID)
                })
            }
        }
    }

    func storeEdition(_ articles: [NewsArticle], delivery: DeliveryMetadata?, forUserID userID: String,
                      expectedLease: UInt64? = nil) async throws -> ArticleCacheMutationDisposition {
        let captured = expectedLease ?? withLock { generation }
        return try await withCheckedThrowingContinuation { continuation in
            queue.async {
                do {
                    let result: ArticleCacheMutationDisposition = try self.withLock {
                        guard captured == self.generation else { return .rejectedStale }
                        let safe = articles.map { $0.safeForReaderCache() }
                        guard DeliveryValidation.accepts(delivery, articles: safe, requestID: delivery?.editionID) else { return .ignoredInvalid }
                        var receivedAt = self.now()
                        if case .saved(let previous) = self.loadEditionUnlocked(forUserID: userID),
                           let old = previous.delivery {
                            guard let delivery, delivery.canReplace(old) else { return .rejectedStale }
                            if delivery.sequence == old.sequence {
                                guard delivery.editionID == old.editionID,
                                      delivery.publishedAt == old.publishedAt,
                                      delivery.validUntil == old.validUntil,
                                      DeliveryValidation.immutableArticlesEqual(previous.articles, safe) else { return .rejectedStale }
                                receivedAt = previous.receivedAt
                            }
                        }
                        let edition = CachedEdition(version: 1, ownerNamespace: Self.namespace(for: userID),
                            articles: safe, delivery: delivery, receivedAt: receivedAt)
                        let data = try Self.encoder.encode(edition)
                        guard safe.count <= 100, data.count <= 2_000_000 else { return .ignoredInvalid }
                        // Persist membership first: any subsequent body read/write
                        // is reconciled against this exact authoritative snapshot.
                        try self.writeData(data, key: self.feedKey(forUserID: userID))
                        var entries = self.loadReaderEntriesUnlocked(forUserID: userID)
                        entries.removeAll { entry in
                            guard let contract = safe.first(where: { $0.id == entry.article.id }) else { return true }
                            return contract.mergingCompatibleCachedDetail(entry.article) == nil
                        }
                        try self.saveReaderEntriesUnlocked(entries, forUserID: userID)
                        return .stored
                    }
                    continuation.resume(returning: result)
                } catch { continuation.resume(throwing: error) }
            }
        }
    }

    func loadDetail(articleID: String, forUserID userID: String) async -> NewsArticle? {
        let captured = withLock { generation }
        return await withCheckedContinuation { continuation in
            queue.async {
                continuation.resume(returning: self.withLock {
                    guard captured == self.generation else { return nil }
                    return self.loadVerifiedDetail(articleID: articleID, forUserID: userID)
                })
            }
        }
    }

    func storeDetail(_ article: NewsArticle, forUserID userID: String,
                     expectedLease: UInt64? = nil) async throws -> ArticleCacheMutationDisposition {
        let captured = expectedLease ?? withLock { generation }
        return try await withCheckedThrowingContinuation { continuation in
            queue.async {
                do {
                    continuation.resume(returning: try self.withLock {
                        guard captured == self.generation else { return .rejectedStale }
                        return try self.storeVerifiedDetail(article, forUserID: userID)
                    })
                } catch { continuation.resume(throwing: error) }
            }
        }
    }

    func removeDetail(articleID: String, forUserID userID: String,
                      expectedLease: UInt64) async throws -> ArticleCacheMutationDisposition {
        try await withCheckedThrowingContinuation { continuation in
            queue.async {
                do {
                    continuation.resume(returning: try self.withLock {
                        guard expectedLease == self.generation else { return .rejectedStale }
                        return try self.removeVerifiedDetail(articleID: articleID, forUserID: userID)
                    })
                } catch { continuation.resume(throwing: error) }
            }
        }
    }

    private func hasUsableOfflineGrant(_ article: NewsArticle, at date: Date) -> Bool {
        guard let validated = article.presentation?.validatedAt,
              let expiry = article.presentation?.offlineValidUntil,
              validated <= date.addingTimeInterval(60), expiry > date,
              expiry > validated, expiry.timeIntervalSince(validated) <= 24 * 60 * 60 else { return false }
        // Within the process, a clock rollback must not lengthen a grant.
        // Injected clocks are intentionally independent for deterministic tests.
        if defaults === UserDefaults.standard {
            let elapsed = ProcessInfo.processInfo.systemUptime - launchedUptime
            guard date >= launchedAt.addingTimeInterval(elapsed - 60) else { return false }
        }
        let clockKey = Self.prefix + ".nativeClockHighWater"
        if let highWater = defaults.object(forKey: clockKey) as? Date,
           date < highWater.addingTimeInterval(-60) { return false }
        let previous = defaults.object(forKey: clockKey) as? Date ?? .distantPast
        defaults.set(max(date, previous), forKey: clockKey)
        return true
    }

    private func feedKey(forUserID userID: String) -> String {
        "\(Self.prefix).\(Self.namespace(for: userID)).articles"
    }

    private func lastFetchKey(forUserID userID: String) -> String {
        "\(Self.prefix).\(Self.namespace(for: userID)).lastFetchDate"
    }

    private func readerKey(forUserID userID: String) -> String {
        "\(Self.prefix).\(Self.namespace(for: userID)).readerArticles"
    }

    private static var encoder: JSONEncoder {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        return encoder
    }

    private func withLock<T>(_ operation: () throws -> T) rethrows -> T {
        lock.lock()
        defer { lock.unlock() }
        return try operation()
    }
}

/// Account-scoped cache facade. Retains the legacy URLSession identifier only
/// to drain OS-restored transfers; all new delivery is foreground coordinated.
final class BackgroundNewsFetcher: NSObject, ObservableObject {
    static let shared = BackgroundNewsFetcher()

    // MARK: - Published state

    @Published private(set) var lastFeedArticles: [NewsArticle] = []
    @Published private(set) var isFetching: Bool = false
    @Published private(set) var lastErrorMessage: String?

    // MARK: - Private

    private let sessionIdentifier = "com.daily.news.feed.background"
    private lazy var backgroundSession: URLSession = {
        let config = URLSessionConfiguration.background(withIdentifier: sessionIdentifier)
        config.sessionSendsLaunchEvents = true
        config.isDiscretionary = false
        config.waitsForConnectivity = true
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()

    private var backgroundCompletionHandler: (() -> Void)?
    private let cacheStore = ArticleCacheStore()

    // MARK: - Initialization

    private override init() {
        super.init()
        // The old cache was global and could cross account boundaries. It is
        // intentionally not migrated because it has no owner identity.
        cacheStore.removeUnownedLegacyCache()
    }

    // MARK: - Public API

    func registerBackgroundCompletionHandler(_ handler: @escaping () -> Void) {
        backgroundCompletionHandler = handler
        // Reattach the restored session so the OS can deliver its final drain
        // callback even though S9 never starts background feed requests.
        backgroundSession.getAllTasks { tasks in tasks.forEach { $0.cancel() } }
    }

    func invalidatePendingWrites() { cacheStore.invalidatePendingWrites() }

    @MainActor
    func loadCachedEdition(forUserID userID: String) async -> CachedEditionLoad {
        await cacheStore.loadEdition(forUserID: userID)
    }

    @MainActor
    func storeEdition(_ articles: [NewsArticle], delivery: DeliveryMetadata?, forUserID userID: String,
                      sessionGeneration: UInt64) async throws -> ArticleCacheMutationDisposition {
        guard AuthService.shared.isAuthenticated, AuthService.shared.currentUser?.id == userID,
              AuthService.shared.sessionGeneration == sessionGeneration else { return .rejectedStale }
        let lease = cacheStore.lease()
        let result = try await cacheStore.storeEdition(articles, delivery: delivery, forUserID: userID, expectedLease: lease)
        guard AuthService.shared.currentUser?.id == userID,
              AuthService.shared.sessionGeneration == sessionGeneration else { return .rejectedStale }
        if result == .stored { lastFeedArticles = articles.map { $0.safeForReaderCache() } }
        return result
    }

    @MainActor
    func loadVerifiedArticleDetailAsync(articleID: String, forUserID userID: String) async -> NewsArticle? {
        await cacheStore.loadDetail(articleID: articleID, forUserID: userID)
    }

    @MainActor
    func storeVerifiedArticleDetailAsync(_ article: NewsArticle, forUserID userID: String,
                                        sessionGeneration: UInt64) async throws -> ArticleCacheMutationDisposition {
        guard AuthService.shared.isAuthenticated, AuthService.shared.currentUser?.id == userID,
              AuthService.shared.sessionGeneration == sessionGeneration else { return .rejectedStale }
        let lease = cacheStore.lease()
        return try await cacheStore.storeDetail(article, forUserID: userID, expectedLease: lease)
    }

    @MainActor
    func removeVerifiedArticleDetailAsync(articleID: String, forUserID userID: String,
                                         sessionGeneration: UInt64) async throws -> ArticleCacheMutationDisposition {
        guard AuthService.shared.currentUser?.id == userID,
              AuthService.shared.sessionGeneration == sessionGeneration else { return .rejectedStale }
        let lease = cacheStore.lease()
        return try await cacheStore.removeDetail(articleID: articleID, forUserID: userID, expectedLease: lease)
    }


    /// Wipe locally cached background-fetched articles. Called from
    /// AuthService on sign-out so a new user doesn't see stale headlines.
    func clearCache() {
        cacheStore.clearAll()
        lastFeedArticles = []
        isFetching = false
        lastErrorMessage = nil
        backgroundSession.getAllTasks { tasks in
            tasks.forEach { $0.cancel() }
        }
    }

}

// MARK: - URLSessionDelegate & URLSessionDownloadDelegate

extension BackgroundNewsFetcher: URLSessionDelegate, URLSessionDownloadDelegate {
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        // Pre-S9 transfers have no publication/session envelope and cannot
        // safely publish into an account's current edition.
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        // Obsolete transfers are drained only; not even their error may mutate
        // the current account's foreground delivery state.
    }

    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        DispatchQueue.main.async {
            self.backgroundCompletionHandler?()
            self.backgroundCompletionHandler = nil
        }
    }
}

// MARK: - Notifications

extension Notification.Name {
    static let feedReady = Notification.Name("BackgroundNewsFetcher.feedReady")
    // Keep old name for backward compatibility during transition
    static let curatedNewsReady = Notification.Name("BackgroundNewsFetcher.feedReady")
}
