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
                    await self?.reloadPersonalizedSections(forceRefresh: true)
                }
            }
            .store(in: &cancellables)

        Task {
            await reloadPersonalizedSections()
        }
    }

    // MARK: - Public Methods

    func loadUserTopics() async {
        guard let token = authService.getAccessToken() else { return }

        do {
            let prefs = try await backendService.fetchUserPreferences(accessToken: token)
            userTopics = sanitizedTopics(from: prefs.topicsList)
            validateSelectedSection()
            refreshTopicArticleCache()
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
        if case .category(let topic) = section {
            await loadTopicSection(topic, forceRefresh: forceRefresh)
            return
        }

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
            case .all:
                allArticles = normalized
                refreshTopicArticleCache()
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

        await loadUserTopics()
        await loadSection(.general, forceRefresh: true)
        await loadSection(.all, forceRefresh: true)
        if case .category(let topic) = selectedSection {
            categoryArticles[topic] = filteredArticles(for: topic, in: allArticles)
        }

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

    private func reloadPersonalizedSections(forceRefresh: Bool = false) async {
        await loadUserTopics()
        await loadSection(.general, forceRefresh: forceRefresh)
        await loadSection(.all, forceRefresh: forceRefresh)
    }

    private func loadTopicSection(_ topic: String, forceRefresh: Bool) async {
        let section = FeedSection.category(topic)
        guard !loadingSections.contains(section) else { return }

        loadingSections.insert(section)
        if section == selectedSection {
            isLoading = (categoryArticles[topic] ?? []).isEmpty
        }
        errorMessage = nil

        if forceRefresh || allArticles.isEmpty {
            await loadSection(.all, forceRefresh: forceRefresh)
        }

        categoryArticles[topic] = filteredArticles(for: topic, in: allArticles)
        loadingSections.remove(section)

        if section == selectedSection {
            isLoading = false
        }
    }

    private func refreshTopicArticleCache() {
        guard !allArticles.isEmpty else {
            categoryArticles = [:]
            return
        }

        var updated: [String: [NewsArticle]] = [:]
        for topic in userTopics {
            updated[topic] = filteredArticles(for: topic, in: allArticles)
        }
        categoryArticles = updated
    }

    private func filteredArticles(for topic: String, in articles: [NewsArticle]) -> [NewsArticle] {
        articles.filter { article in
            articleMatchesTopic(article, topic: topic)
        }
    }

    private func articleMatchesTopic(_ article: NewsArticle, topic: String) -> Bool {
        let normalizedTopic = normalizedSearchText(topic)
        guard !normalizedTopic.isEmpty else { return false }

        let searchableText = normalizedSearchText([
            article.title,
            article.summary,
            article.content,
            article.author,
            article.source,
            article.category
        ]
        .compactMap { $0 }
        .joined(separator: " "))

        guard !searchableText.isEmpty else { return false }

        if searchableText.contains(normalizedTopic) {
            return true
        }

        let topicTokens = normalizedTopic
            .split(separator: " ")
            .map(String.init)
            .filter { $0.count > 2 }

        return topicTokens.count > 1 && topicTokens.allSatisfy(searchableText.contains)
    }

    private func normalizedSearchText(_ text: String) -> String {
        text
            .folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
            .lowercased()
            .replacingOccurrences(of: "[^a-z0-9]+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func sanitizedTopics(from topics: [String]) -> [String] {
        var seen = Set<String>()

        return topics.compactMap { rawTopic in
            let trimmed = rawTopic.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { return nil }

            let normalized = normalizedSearchText(trimmed)
            guard !normalized.isEmpty, seen.insert(normalized).inserted else { return nil }
            return trimmed
        }
    }

    private func validateSelectedSection() {
        guard case .category(let topic) = selectedSection else { return }

        let hasTopic = userTopics.contains { existingTopic in
            normalizedSearchText(existingTopic) == normalizedSearchText(topic)
        }

        if !hasTopic {
            selectedSection = .general
        }
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
