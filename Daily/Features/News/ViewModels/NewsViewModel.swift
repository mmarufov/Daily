//
//  NewsViewModel.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import Foundation
import Combine
import UIKit

// MARK: - Feed Section

enum FeedSection: Hashable {
    case general
    case all
    case category(String)

    var displayName: String {
        switch self {
        case .general: return "General"
        case .all: return "All"
        case .category(let name): return name.capitalized
        }
    }
}

// MARK: - ViewModel

@MainActor
final class NewsViewModel: ObservableObject {
    @Published var selectedSection: FeedSection = .general
    @Published var userTopics: [String] = []
    @Published var isLoading: Bool = false
    @Published var isRefreshing: Bool = false
    @Published var errorMessage: String?
    @Published var lastFetchDate: Date?

    // Per-section article caches
    @Published private(set) var generalArticles: [NewsArticle] = []
    @Published private(set) var allArticles: [NewsArticle] = []
    @Published private(set) var categoryArticles: [String: [NewsArticle]] = [:]

    @Published var loadingSections: Set<FeedSection> = []

    private let backendService = BackendService.shared
    private let authService = AuthService.shared
    private var cancellables = Set<AnyCancellable>()

    var currentArticles: [NewsArticle] {
        switch selectedSection {
        case .general: return generalArticles
        case .all: return allArticles
        case .category(let topic): return categoryArticles[topic] ?? []
        }
    }

    var isCurrentSectionLoading: Bool {
        loadingSections.contains(selectedSection)
    }

    // MARK: - Init

    init() {
        // Listen for onboarding completion to reload topics & feed
        NotificationCenter.default.publisher(for: .onboardingCompleted)
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in
                Task { [weak self] in
                    await self?.loadUserTopics()
                    await self?.loadSection(.general, forceRefresh: true)
                }
            }
            .store(in: &cancellables)

        Task {
            await loadUserTopics()
            await loadSection(.general)
        }
    }

    // MARK: - Public Methods

    func loadUserTopics() async {
        guard let token = authService.getAccessToken() else { return }

        do {
            let prefs = try await backendService.fetchUserPreferences(accessToken: token)
            userTopics = prefs.topicsList
        } catch {
            // Silent failure — tabs just won't show
        }
    }

    func selectSection(_ section: FeedSection) {
        selectedSection = section
        HapticService.selection()

        // Load if not yet cached
        let hasCachedData: Bool
        switch section {
        case .general: hasCachedData = !generalArticles.isEmpty
        case .all: hasCachedData = !allArticles.isEmpty
        case .category(let topic): hasCachedData = categoryArticles[topic] != nil
        }

        if !hasCachedData && !loadingSections.contains(section) {
            Task { await loadSection(section) }
        }
    }

    func loadSection(_ section: FeedSection, forceRefresh: Bool = false) async {
        guard !loadingSections.contains(section) else { return }

        guard let token = authService.getAccessToken() else { return }

        loadingSections.insert(section)
        if section == selectedSection {
            isLoading = currentArticles.isEmpty
        }
        errorMessage = nil

        do {
            let params = sectionParams(for: section)
            let fetched: [NewsArticle]

            if forceRefresh {
                fetched = try await backendService.refreshFeed(
                    accessToken: token,
                    limit: params.limit,
                    category: params.category,
                    section: params.section
                )
            } else {
                fetched = try await backendService.fetchFeed(
                    accessToken: token,
                    limit: params.limit,
                    category: params.category,
                    section: params.section
                )
            }

            let normalized = fetched.map { $0.normalizedForDisplay() }

            switch section {
            case .general: generalArticles = normalized
            case .all: allArticles = normalized
            case .category(let topic): categoryArticles[topic] = normalized
            }

            lastFetchDate = Date()

            if !normalized.isEmpty {
                ImageCacheService.shared.preloadImages(for: normalized)
            }
        } catch {
            let errorMsg = error.localizedDescription.lowercased()
            if !errorMsg.contains("not found") && !errorMsg.contains("404") {
                errorMessage = error.localizedDescription
            }
        }

        loadingSections.remove(section)
        if section == selectedSection {
            isLoading = false
        }
    }

    func refreshFeed() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        errorMessage = nil

        // Clear cache for current section and reload
        await loadSection(selectedSection, forceRefresh: true)

        if errorMessage == nil {
            HapticService.notification(.success)
        } else {
            HapticService.notification(.error)
        }
        isRefreshing = false
    }

    // MARK: - Private

    private struct SectionParams {
        let limit: Int
        let category: String?
        let section: String?
    }

    private func sectionParams(for section: FeedSection) -> SectionParams {
        switch section {
        case .general:
            return SectionParams(limit: 10, category: nil, section: "general")
        case .all:
            return SectionParams(limit: 30, category: nil, section: "all")
        case .category(let topic):
            return SectionParams(limit: 20, category: topic, section: nil)
        }
    }
}
