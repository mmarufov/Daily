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
    private static let generalDisplayLimit = 25
    private static let generalRelevanceThreshold = 0.4

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
        if section == .general || section == .all {
            await loadPrimaryFeed(forceRefresh: forceRefresh)
            return
        }

        if case .category(let topic) = section {
            await loadTopicSection(topic, forceRefresh: forceRefresh)
            return
        }
    }

    func refreshFeed() async {
        guard !isRefreshing else { return }
        isRefreshing = true
        errorMessage = nil

        await loadUserTopics()
        await loadPrimaryFeed(forceRefresh: true)
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
        await loadPrimaryFeed(forceRefresh: forceRefresh)
    }

    private func loadPrimaryFeed(forceRefresh: Bool) async {
        guard !loadingSections.contains(.all) && !loadingSections.contains(.general) else { return }
        guard let token = authService.getAccessToken() else { return }

        loadingSections.formUnion([.general, .all])
        if selectedSection == .general || selectedSection == .all {
            isLoading = currentArticles.isEmpty
        }
        errorMessage = nil

        do {
            let params = sectionParams(for: .all)
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

            applyPrimaryFeed(fetched.map { $0.normalizedForDisplay() })
        } catch {
            let errorMsg = error.localizedDescription.lowercased()
            if !errorMsg.contains("not found") && !errorMsg.contains("404") {
                errorMessage = error.localizedDescription
            }
        }

        loadingSections.subtract([.general, .all])
        if selectedSection == .general || selectedSection == .all {
            isLoading = false
        }
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
            await loadPrimaryFeed(forceRefresh: forceRefresh)
        }

        categoryArticles[topic] = filteredArticles(for: topic, in: allArticles)
        loadingSections.remove(section)

        if section == selectedSection {
            isLoading = false
        }
    }

    private func refreshTopicArticleCache() {
        guard !allArticles.isEmpty else {
            generalArticles = []
            categoryArticles = [:]
            return
        }

        var updated: [String: [NewsArticle]] = [:]
        for topic in userTopics {
            updated[topic] = filteredArticles(for: topic, in: allArticles)
        }
        categoryArticles = updated
    }

    private func applyPrimaryFeed(_ articles: [NewsArticle]) {
        allArticles = articles
        let scored = articles.filter { ($0.relevanceScore ?? 0.0) >= Self.generalRelevanceThreshold }
        generalArticles = scored.isEmpty
            ? Array(articles.prefix(Self.generalDisplayLimit))
            : Array(scored.prefix(Self.generalDisplayLimit))
        refreshTopicArticleCache()
        lastFetchDate = Date()

        if !articles.isEmpty {
            ImageCacheService.shared.preloadImages(for: articles)
        }
    }

    private func filteredArticles(for topic: String, in articles: [NewsArticle]) -> [NewsArticle] {
        let matched = articles.filter { articleMatchesTopic($0, topic: topic) }
        if !matched.isEmpty { return matched }

        // Fallback: match on article category field
        let normalizedTopic = normalizedSearchText(topic)
        let categoryMatched = articles.filter {
            guard let cat = $0.category else { return false }
            return normalizedSearchText(cat).contains(normalizedTopic)
                || normalizedTopic.contains(normalizedSearchText(cat))
        }
        if !categoryMatched.isEmpty { return categoryMatched }

        // Final fallback: show top-scored articles so the tab is never empty
        return Array(
            articles
                .sorted { ($0.relevanceScore ?? 0) > ($1.relevanceScore ?? 0) }
                .prefix(10)
        )
    }

    private static let stopWords: Set<String> = [
        "and", "or", "the", "for", "in", "of", "to", "a", "an", "with", "about"
    ]

    private static let topicExpansions: [String: [String]] = [
        "ai": ["artificial intelligence", "machine learning", "deep learning", "neural network", "llm", "chatgpt", "openai", "gpt", "gemini", "claude"],
        "artificial intelligence": ["ai", "machine learning", "deep learning", "neural network", "llm", "chatgpt", "openai", "gpt", "gemini", "claude"],
        "ml": ["machine learning", "deep learning", "neural network"],
        "tech": ["technology", "software", "startup", "app", "digital"],
        "technology": ["tech", "software", "startup", "app", "digital"],
        "crypto": ["cryptocurrency", "bitcoin", "blockchain", "ethereum"],
        "ev": ["electric vehicle", "tesla"],
        "vr": ["virtual reality", "metaverse"],
        "ar": ["augmented reality"],
        "science": ["research", "study", "scientific", "discovery"],
        "business": ["startup", "enterprise", "corporate", "economy", "market"],
        "finance": ["stock", "market", "investment", "banking", "economy"],
        "health": ["medical", "healthcare", "wellness", "disease", "treatment"],
        "sports": ["football", "basketball", "soccer", "tennis", "athlete"],
    ]

    private func articleMatchesTopic(_ article: NewsArticle, topic: String, isSubTopic: Bool = false) -> Bool {
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

        // Direct substring match (works for longer topics)
        if searchableText.contains(normalizedTopic) {
            return true
        }

        let topicTokens = normalizedTopic
            .split(separator: " ")
            .map(String.init)
            .filter { !Self.stopWords.contains($0) }

        // Word-boundary matching for short tokens (e.g., "ai" shouldn't match "said")
        for token in topicTokens where token.count <= 3 {
            let pattern = "\\b\(NSRegularExpression.escapedPattern(for: token))\\b"
            if let regex = try? NSRegularExpression(pattern: pattern),
               regex.firstMatch(in: searchableText, range: NSRange(searchableText.startIndex..., in: searchableText)) != nil {
                return true
            }
        }

        // Check expanded synonyms for full topic and each token
        let keysToCheck = [normalizedTopic] + topicTokens
        for key in keysToCheck {
            if let expansions = Self.topicExpansions[key] {
                for expansion in expansions {
                    if searchableText.contains(expansion) {
                        return true
                    }
                }
            }
        }

        // Split compound topics ("AI and tech" → ["ai", "tech"]) and match sub-topics
        if !isSubTopic && topicTokens.count > 1 {
            for token in topicTokens where token.count > 1 {
                if articleMatchesTopic(article, topic: token, isSubTopic: true) {
                    return true
                }
            }
        }

        // Multi-token: all significant tokens must appear
        let significantTokens = topicTokens.filter { $0.count > 2 }
        return significantTokens.count > 1 && significantTokens.allSatisfy(searchableText.contains)
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
            return SectionParams(limit: Self.generalDisplayLimit, category: nil, section: "general")
        case .all:
            return SectionParams(limit: 120, category: nil, section: "all")
        case .category(let topic):
            return SectionParams(limit: 30, category: topic, section: nil)
        }
    }
}
