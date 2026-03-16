//
//  NewsViewModel.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import Foundation
import Combine

@MainActor
final class NewsViewModel: ObservableObject {
    @Published var articles: [NewsArticle] = []
    @Published var isLoading: Bool = false
    @Published var isRefreshing: Bool = false
    @Published var errorMessage: String?
    @Published var lastFetchDate: Date?

    private let backendService = BackendService.shared
    private let authService = AuthService.shared

    // MARK: - Init

    init() {
        // Auto-load feed on creation
        Task {
            await loadFeed()
        }
    }

    // MARK: - Public Methods

    /// Load personalized feed from the backend (uses cache if fresh).
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

    /// Force refresh — re-scores articles ignoring cache.
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
        } catch {
            errorMessage = error.localizedDescription
        }

        isRefreshing = false
    }
}
