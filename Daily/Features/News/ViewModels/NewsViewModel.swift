//
//  NewsViewModel.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import Foundation
import Combine
import UIKit

@MainActor
final class NewsViewModel: ObservableObject {
    @Published var articles: [NewsArticle] = []
    @Published var isLoading: Bool = false
    @Published var isRefreshing: Bool = false
    @Published var errorMessage: String?
    @Published var lastFetchDate: Date?
    @Published var selectedCategory: String?
    @Published var searchText: String = ""

    private let backendService = BackendService.shared
    private let authService = AuthService.shared

    var availableCategories: [String] {
        let cats = Set(articles.compactMap { $0.category?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty })
        return cats.sorted()
    }

    var filteredArticles: [NewsArticle] {
        var result = articles

        if let category = selectedCategory {
            result = result.filter {
                $0.category?.localizedCaseInsensitiveCompare(category) == .orderedSame
            }
        }

        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        if !query.isEmpty {
            result = result.filter { article in
                article.title.localizedCaseInsensitiveContains(query)
                || (article.summary?.localizedCaseInsensitiveContains(query) == true)
                || (article.source?.localizedCaseInsensitiveContains(query) == true)
                || (article.author?.localizedCaseInsensitiveContains(query) == true)
            }
        }

        return result
    }

    // MARK: - Init

    init() {
        Task {
            await loadFeed()
        }
    }

    // MARK: - Public Methods

    func loadFeed() async {
        guard !isLoading else { return }

        isLoading = true
        errorMessage = nil

        guard let token = authService.getAccessToken() else {
            isLoading = false
            return
        }

        do {
            let fetched = try await backendService.fetchFeed(accessToken: token, limit: 20)
            articles = fetched.map { $0.normalizedForDisplay() }
            lastFetchDate = Date()

            if !articles.isEmpty {
                ImageCacheService.shared.preloadImages(for: articles)
            }
        } catch {
            let errorMsg = error.localizedDescription.lowercased()
            if !errorMsg.contains("not found") && !errorMsg.contains("404") {
                errorMessage = error.localizedDescription
            }
        }

        isLoading = false
    }

    func refreshFeed() async {
        guard !isRefreshing else { return }

        isRefreshing = true
        errorMessage = nil

        guard let token = authService.getAccessToken() else {
            isRefreshing = false
            return
        }

        do {
            let fetched = try await backendService.refreshFeed(accessToken: token, limit: 20)
            articles = fetched.map { $0.normalizedForDisplay() }
            lastFetchDate = Date()

            if !articles.isEmpty {
                ImageCacheService.shared.preloadImages(for: articles)
            }
            HapticService.notification(.success)
        } catch {
            errorMessage = error.localizedDescription
            HapticService.notification(.error)
        }

        isRefreshing = false
    }
}
