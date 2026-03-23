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
    private var isRequestInFlight = false
    private var queuedForceRefresh = false

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

        if isRequestInFlight {
            queuedForceRefresh = queuedForceRefresh || forceRefresh
            return
        }

        isRequestInFlight = true
        if forceRefresh {
            isRefreshing = true
        } else if articles.isEmpty {
            isLoading = true
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
        } catch is CancellationError {
            // Ignore task cancellation so the UI keeps the last successful feed.
        } catch {
            let errorMsg = error.localizedDescription.lowercased()
            if errorMsg.contains("cancelled") || errorMsg.contains("canceled") {
                // Ignore transient cancellation errors from overlapping refreshes.
            } else if !errorMsg.contains("not found") && !errorMsg.contains("404") {
                errorMessage = error.localizedDescription
            }
        }

        let shouldRunQueuedRefresh = queuedForceRefresh
        queuedForceRefresh = false
        isRequestInFlight = false
        isLoading = false

        if shouldRunQueuedRefresh {
            await loadFeed(forceRefresh: true)
        } else {
            isRefreshing = false
        }
    }

    func refreshFeed() async {
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
