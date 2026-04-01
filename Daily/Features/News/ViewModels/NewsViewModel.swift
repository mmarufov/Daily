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
    enum SetupPhase {
        case discovering
        case building
        case rebuilding

        var title: String {
            switch self {
            case .discovering:
                return "Finding the right sources"
            case .building:
                return "Building your feed"
            case .rebuilding:
                return "Updating your feed"
            }
        }

        var subtitle: String {
            switch self {
            case .discovering:
                return "Scanning for feeds that actually match what you asked for."
            case .building:
                return "Fetching fresh articles and filtering them against your profile."
            case .rebuilding:
                return "Re-discovering sources for your updated interests."
            }
        }
    }

    @Published var articles: [NewsArticle] = []
    @Published var isLoading: Bool = false
    @Published var isRefreshing: Bool = false
    @Published var isSettingUp: Bool = false
    @Published var setupPhase: SetupPhase?
    @Published var setupDetailText: String?
    @Published var errorMessage: String?
    @Published var lastFetchDate: Date?

    private let backendService = BackendService.shared
    private let authService = AuthService.shared
    private var cancellables = Set<AnyCancellable>()
    private var isRequestInFlight = false
    private var queuedForceRefresh = false
    private var activeBuildTask: Task<Void, Never>?

    init() {
        // After onboarding completes, check feed state (will trigger discovery if needed)
        NotificationCenter.default.publisher(for: .onboardingCompleted)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                guard let self else { return }
                self.errorMessage = nil
                Task { [weak self] in
                    await self?.loadFeed(forceRefresh: false)
                }
            }
            .store(in: &cancellables)

        // After preferences change, re-discover sources + rebuild feed
        NotificationCenter.default.publisher(for: .preferencesChanged)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                guard let self else { return }
                Task { [weak self] in
                    await self?.rebuildAfterPreferenceChange()
                }
            }
            .store(in: &cancellables)

        Task {
            await loadFeed()
        }
    }

    func loadFeed(forceRefresh: Bool = false) async {
        guard let token = authService.getAccessToken() else { return }

        if isRequestInFlight {
            queuedForceRefresh = queuedForceRefresh || forceRefresh
            return
        }

        let existingArticles = articles
        isRequestInFlight = true

        if forceRefresh {
            isRefreshing = true
        } else if articles.isEmpty && !isSettingUp {
            isLoading = true
        }

        errorMessage = nil

        do {
            let response: BackendService.FeedResponse
            if forceRefresh {
                response = try await backendService.refreshFeedStatus(accessToken: token, limit: 50)
            } else {
                response = try await backendService.fetchFeedState(accessToken: token, limit: 50)
            }

            try await handleFeedResponse(response, accessToken: token, fallbackArticles: existingArticles)
        } catch is CancellationError {
            // Keep the last good feed.
        } catch {
            if forceRefresh && !existingArticles.isEmpty {
                articles = existingArticles
            }
            let errorMsg = error.localizedDescription.lowercased()
            if !errorMsg.contains("cancelled") && !errorMsg.contains("canceled") {
                errorMessage = error.localizedDescription
            }
        }

        let shouldRunQueuedRefresh = queuedForceRefresh
        queuedForceRefresh = false
        isRequestInFlight = false
        isLoading = false
        isRefreshing = false

        if shouldRunQueuedRefresh {
            await loadFeed(forceRefresh: true)
        }
    }

    func refreshFeed() async {
        await loadFeed(forceRefresh: true)
        if errorMessage == nil {
            HapticService.notification(.success)
        } else {
            HapticService.notification(.error)
        }
    }

    /// Re-discover sources and rebuild feed after user changes preferences.
    func rebuildAfterPreferenceChange() async {
        guard let token = authService.getAccessToken() else { return }

        // Cancel any in-flight build
        activeBuildTask?.cancel()

        let fallback = articles

        activeBuildTask = Task { @MainActor [weak self] in
            guard let self else { return }
            await self.runSetupFlow(
                accessToken: token,
                needsDiscovery: true,
                fallbackArticles: fallback,
                phaseOverride: .rebuilding
            )
        }

        await activeBuildTask?.value
    }

    func submitFeedback(for article: NewsArticle, action: String, position: Int? = nil) async {
        guard let token = authService.getAccessToken() else { return }

        do {
            try await backendService.submitFeedFeedback(
                articleID: article.id,
                action: action,
                accessToken: token,
                feedRequestID: ReadingEventTracker.shared.feedRequestId,
                position: position
            )

            if action == "not_relevant" || action == "hide_source" || action == "less_like_this" {
                articles.removeAll { $0.id == article.id }
            }
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private extension NewsViewModel {
    func handleFeedResponse(
        _ response: BackendService.FeedResponse,
        accessToken: String,
        fallbackArticles: [NewsArticle]
    ) async throws {
        switch response.status {
        case .ready:
            applyReadyFeed(response.articles)
        case .needsDiscovery:
            try await runSetupFlow(accessToken: accessToken, needsDiscovery: true, fallbackArticles: fallbackArticles)
        case .needsBuild:
            try await runSetupFlow(accessToken: accessToken, needsDiscovery: false, fallbackArticles: fallbackArticles)
        }
    }

    @discardableResult
    func runSetupFlow(
        accessToken: String,
        needsDiscovery: Bool,
        fallbackArticles: [NewsArticle],
        phaseOverride: SetupPhase? = nil
    ) async -> Bool {
        isSettingUp = true
        setupDetailText = nil

        // Safety timeout: dismiss overlay after 90s even if network is still in flight
        let timeoutTask = Task { @MainActor [weak self] in
            try await Task.sleep(for: .seconds(90))
            guard let self, self.isSettingUp else { return }
            self.isSettingUp = false
            self.setupPhase = nil
            self.setupDetailText = nil
            if self.articles.isEmpty {
                self.errorMessage = "Feed setup is taking too long. Pull down to retry."
            }
        }

        defer {
            timeoutTask.cancel()
            isSettingUp = false
            setupPhase = nil
            setupDetailText = nil
        }

        do {
            if needsDiscovery {
                setupPhase = phaseOverride ?? .discovering
                let discovery = try await backendService.discoverSources(accessToken: accessToken)
                if discovery.sourcesFound > 0 {
                    setupDetailText = "\(discovery.sourcesFound) sources selected"
                } else {
                    setupDetailText = "No strong sources found yet"
                }
            }

            setupPhase = .building
            let build = try await backendService.buildFeed(accessToken: accessToken, limit: 50)

            switch build.status {
            case .ready:
                applyReadyFeed(build.articles)
                if build.qualityMet == false && !build.articles.isEmpty {
                    errorMessage = "Your feed is small right now, but it's staying tightly on-topic."
                }
                return true
            case .needsDiscovery:
                if !fallbackArticles.isEmpty {
                    articles = fallbackArticles
                }
                errorMessage = "We couldn't find a stable source graph for this profile yet."
            case .needsBuild:
                if !fallbackArticles.isEmpty {
                    articles = fallbackArticles
                }
                errorMessage = "Your feed still needs another build pass."
            }
        } catch is CancellationError {
            if !fallbackArticles.isEmpty {
                articles = fallbackArticles
            }
        } catch {
            if !fallbackArticles.isEmpty {
                articles = fallbackArticles
            }
            let errorMsg = error.localizedDescription.lowercased()
            if !errorMsg.contains("cancelled") && !errorMsg.contains("canceled") {
                errorMessage = "Couldn't build your feed. Pull down to retry."
            }
        }
        return false
    }

    func applyReadyFeed(_ fetchedArticles: [NewsArticle]) {
        articles = fetchedArticles.map { $0.normalizedForDisplay() }
        lastFetchDate = Date()

        if !articles.isEmpty {
            ImageCacheService.shared.preloadImages(for: articles)
        }
    }
}
