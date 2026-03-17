//
//  BookmarkService.swift
//  Daily
//

import Foundation
import Combine

struct BookmarkedArticle: Codable, Identifiable {
    let article: NewsArticle
    let bookmarkedAt: Date

    var id: String { article.id }
}

@MainActor
final class BookmarkService: ObservableObject {
    static let shared = BookmarkService()

    @Published private(set) var bookmarkedArticles: [BookmarkedArticle] = []
    @Published private(set) var readArticleIDs: Set<String> = []

    private let bookmarksURL: URL
    private let readIDsURL: URL

    private init() {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        bookmarksURL = docs.appendingPathComponent("bookmarks.json")
        readIDsURL = docs.appendingPathComponent("read_articles.json")
        load()
    }

    // MARK: - Bookmarks

    func toggleBookmark(_ article: NewsArticle) {
        if let index = bookmarkedArticles.firstIndex(where: { $0.article.id == article.id }) {
            bookmarkedArticles.remove(at: index)
        } else {
            let entry = BookmarkedArticle(article: article, bookmarkedAt: Date())
            bookmarkedArticles.insert(entry, at: 0)
        }
        saveBookmarks()
    }

    func isBookmarked(_ articleID: String) -> Bool {
        bookmarkedArticles.contains { $0.article.id == articleID }
    }

    // MARK: - Read Tracking

    func markAsRead(_ articleID: String) {
        guard !readArticleIDs.contains(articleID) else { return }
        readArticleIDs.insert(articleID)
        saveReadIDs()
    }

    func isRead(_ articleID: String) -> Bool {
        readArticleIDs.contains(articleID)
    }

    // MARK: - Persistence

    private func load() {
        if let data = try? Data(contentsOf: bookmarksURL),
           let decoded = try? JSONDecoder.withISO8601.decode([BookmarkedArticle].self, from: data) {
            bookmarkedArticles = decoded
        }
        if let data = try? Data(contentsOf: readIDsURL),
           let decoded = try? JSONDecoder().decode(Set<String>.self, from: data) {
            readArticleIDs = decoded
        }
    }

    private func saveBookmarks() {
        Task.detached(priority: .utility) { [bookmarkedArticles, bookmarksURL] in
            let encoder = JSONEncoder()
            encoder.dateEncodingStrategy = .iso8601
            if let data = try? encoder.encode(bookmarkedArticles) {
                try? data.write(to: bookmarksURL, options: .atomic)
            }
        }
    }

    private func saveReadIDs() {
        Task.detached(priority: .utility) { [readArticleIDs, readIDsURL] in
            if let data = try? JSONEncoder().encode(readArticleIDs) {
                try? data.write(to: readIDsURL, options: .atomic)
            }
        }
    }
}

private extension JSONDecoder {
    static let withISO8601: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return decoder
    }()
}
