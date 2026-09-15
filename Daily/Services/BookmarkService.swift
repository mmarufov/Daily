import Foundation
import Combine

nonisolated struct BookmarkedArticle: Codable, Identifiable, Sendable {
    let article: NewsArticle
    let bookmarkedAt: Date
    var id: String { article.id }
}

/// FIFO disk ownership plus a synchronous invalidation barrier. Old queued
/// saves cannot recreate cleared account data after sign-out.
nonisolated final class BookmarkDiskStore: @unchecked Sendable {
    struct Snapshot: Codable, Sendable {
        let owner: String
        let bookmarks: [BookmarkedArticle]
        let readIDs: Set<String>
    }
    private let directory: URL
    private let queue = DispatchQueue(label: "Daily.bookmark-storage", qos: .utility)
    private let lock = NSLock()
    private var generation: UInt64 = 0
    init(directory: URL) { self.directory = directory }
    func lease() -> UInt64 { lock.lock(); defer { lock.unlock() }; return generation }
    func invalidatePendingWrites() { lock.lock(); generation &+= 1; lock.unlock() }

    func load(owner: String, lease: UInt64) async -> Snapshot? {
        await withCheckedContinuation { continuation in
            queue.async {
                self.lock.lock(); defer { self.lock.unlock() }
                guard lease == self.generation else { continuation.resume(returning: nil); return }
                let file = self.directory.appendingPathComponent(owner + ".json")
                if !FileManager.default.fileExists(atPath: file.path) {
                    continuation.resume(returning: Snapshot(owner: owner, bookmarks: [], readIDs: [])); return
                }
                let decoder = JSONDecoder(); decoder.dateDecodingStrategy = .iso8601
                guard let size = try? file.resourceValues(forKeys: [.fileSizeKey]).fileSize,
                      size <= 4_000_000, let data = try? Data(contentsOf: file),
                      let value = try? decoder.decode(Snapshot.self, from: data), value.owner == owner,
                      value.bookmarks.count <= 1000, value.readIDs.count <= 10_000 else {
                    continuation.resume(returning: nil); return
                }
                continuation.resume(returning: value)
            }
        }
    }

    func save(_ snapshot: Snapshot, lease: UInt64) {
        lock.lock()
        defer { lock.unlock() }
        queue.async {
            self.lock.lock(); defer { self.lock.unlock() }
            guard lease == self.generation else { return }
            do {
                let encoder = JSONEncoder(); encoder.dateEncodingStrategy = .iso8601
                let data = try encoder.encode(snapshot)
                guard data.count <= 4_000_000 else { return }
                try FileManager.default.createDirectory(at: self.directory, withIntermediateDirectories: true,
                    attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication])
                // Durable metadata is device-local, matching the device-only
                // credential owner marker. OS protection is not E2E encryption.
                var directory = self.directory
                var values = URLResourceValues(); values.isExcludedFromBackup = true
                try directory.setResourceValues(values)
                try data.write(to: directory.appendingPathComponent(snapshot.owner + ".json"),
                    options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
            } catch { /* Unavailable storage never becomes an empty overwrite. */ }
        }
    }

    func clear() {
        lock.lock(); defer { lock.unlock() }
        generation &+= 1
        queue.async { try? FileManager.default.removeItem(at: self.directory) }
    }

    func drain() async {
        await withCheckedContinuation { continuation in queue.async { continuation.resume() } }
    }
}

@MainActor
final class BookmarkService: ObservableObject {
    static let shared = BookmarkService()
    @Published private(set) var bookmarkedArticles: [BookmarkedArticle] = []
    @Published private(set) var readArticleIDs: Set<String> = []
    private let disk: BookmarkDiskStore
    private var owner: String?
    private var session: UInt64 = 0
    private var lease: UInt64 = 0
    private var revision: UInt64 = 0
    private var loaded = false

    init(directory: URL? = nil) {
        let base = directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("DailyBookmarks", isDirectory: true)
        disk = BookmarkDiskStore(directory: base)
        // Legacy Documents/bookmarks.json and read_articles.json lack an owner.
        // Leave recoverable; never import them into an arbitrary login.
    }

    func activate(userID: String, sessionGeneration: UInt64) {
        let nextOwner = ArticleCacheStore.namespace(for: userID)
        guard nextOwner != owner || sessionGeneration != session else { return }
        owner = nextOwner; session = sessionGeneration; revision &+= 1
        let expectedRevision = revision
        disk.invalidatePendingWrites()
        lease = disk.lease()
        let expectedLease = lease
        bookmarkedArticles = []; readArticleIDs = []; loaded = false
        Task {
            let snapshot = await disk.load(owner: nextOwner, lease: expectedLease)
            guard owner == nextOwner, session == sessionGeneration, revision == expectedRevision else { return }
            bookmarkedArticles = snapshot?.bookmarks.map {
                BookmarkedArticle(article: $0.article.safeForReaderCache().withoutFeedReceipt(), bookmarkedAt: $0.bookmarkedAt)
            } ?? []
            readArticleIDs = snapshot?.readIDs ?? []
            // Corrupt or protected/unavailable files must not be replaced by
            // an accidental empty save. A fresh activation can retry loading.
            loaded = snapshot != nil
        }
    }

    func toggleBookmark(_ article: NewsArticle) {
        guard loaded, owner != nil else { return }
        if let index = bookmarkedArticles.firstIndex(where: { $0.id == article.id }) {
            bookmarkedArticles.remove(at: index)
        } else {
            guard bookmarkedArticles.count < 1000 else { return }
            bookmarkedArticles.insert(BookmarkedArticle(article: article.safeForReaderCache().withoutFeedReceipt(),
                bookmarkedAt: Date()), at: 0)
        }
        save()
    }
    func isBookmarked(_ articleID: String) -> Bool { bookmarkedArticles.contains { $0.id == articleID } }
    func markAsRead(_ articleID: String) {
        guard loaded, owner != nil, !readArticleIDs.contains(articleID) else { return }
        if readArticleIDs.count >= 10_000 { readArticleIDs.removeAll() }
        readArticleIDs.insert(articleID); save()
    }
    func isRead(_ articleID: String) -> Bool { readArticleIDs.contains(articleID) }
    private func save() {
        guard let owner else { return }
        disk.save(.init(owner: owner, bookmarks: bookmarkedArticles, readIDs: readArticleIDs), lease: lease)
    }
    func clearAll() {
        revision &+= 1; owner = nil; loaded = false
        bookmarkedArticles = []; readArticleIDs = []
        disk.clear()
    }
}
