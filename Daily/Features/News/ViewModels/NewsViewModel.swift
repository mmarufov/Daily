//
//  NewsViewModel.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import Foundation
import Combine
import UIKit

// MARK: - ViewModel

@MainActor
final class NewsViewModel: ObservableObject {
    @Published var articles: [NewsArticle] = []
    @Published var isLoading: Bool = false
    @Published var isRefreshing: Bool = false
    @Published var errorMessage: String?
    @Published var lastFetchDate: Date?

    private let backendService = BackendService.shared
    private let authService = AuthService.shared
    private var cancellables = Set<AnyCancellable>()

    // MARK: - Init

    init() {
        // Listen for onboarding completion to reload feed
        NotificationCenter.default.publisher(for: .onboardingCompleted)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                Task { [weak self] in
                    await self?.loadFeed(forceRefresh: true)
                }
            }
            .store(in: &cancellables)

        Task {
            await loadFeed()
        }
    }

    // MARK: - Public Methods

    func loadFeed(forceRefresh: Bool = false) async {
        guard let token = authService.getAccessToken() else { return }

        if !forceRefresh {
            isLoading = articles.isEmpty
        }
        errorMessage = nil

        do {
            let fetched: [NewsArticle]

            if forceRefresh {
                fetched = try await backendService.refreshFeed(
                    accessToken: token,
                    limit: 50
                )
            } else {
                fetched = try await backendService.fetchFeed(
                    accessToken: token,
                    limit: 50
                )
            }

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

        await loadFeed(forceRefresh: true)

        if errorMessage == nil {
            HapticService.notification(.success)
        } else {
            HapticService.notification(.error)
        }
        isRefreshing = false
    }
}
