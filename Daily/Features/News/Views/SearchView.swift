//
//  SearchView.swift
//  Daily
//
//  Full-screen search experience for finding articles.
//

import SwiftUI

struct SearchView: View {
    @ObservedObject var newsViewModel: NewsViewModel
    @ObservedObject private var bookmarks = BookmarkService.shared
    @State private var searchText = ""
    @State private var categoryCounts: [String: Int] = [:]
    @State private var semanticResults: [NewsArticle] = []
    @State private var isSearching = false

    private static let defaultCategories: [(name: String, icon: String, color: Color)] = [
        ("technology", "cpu.fill", .blue),
        ("business", "chart.line.uptrend.xyaxis", .green),
        ("politics", "building.columns.fill", .indigo),
        ("sports", "sportscourt.fill", .orange),
        ("entertainment", "film.fill", .red),
        ("science", "atom", .purple),
        ("health", "heart.fill", .pink),
        ("world", "globe.americas.fill", .teal),
    ]

    private var localResults: [NewsArticle] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return [] }

        return newsViewModel.articles.filter { article in
            article.title.localizedCaseInsensitiveContains(query)
            || (article.summary?.localizedCaseInsensitiveContains(query) == true)
            || (article.source?.localizedCaseInsensitiveContains(query) == true)
            || (article.author?.localizedCaseInsensitiveContains(query) == true)
            || (article.category?.localizedCaseInsensitiveContains(query) == true)
        }
    }

    private var displayResults: [NewsArticle] {
        // Merge semantic + local, dedup by ID, prefer semantic ordering
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return [] }

        var seen = Set<String>()
        var merged: [NewsArticle] = []
        for article in semanticResults + localResults {
            if seen.insert(article.id).inserted {
                merged.append(article)
            }
        }
        return merged
    }

    var body: some View {
        NavigationStack {
            Group {
                if searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    categoryGridView
                } else if isSearching {
                    ProgressView("Searching...")
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if displayResults.isEmpty {
                    noResultsState
                } else {
                    resultsList
                }
            }
            .background(Color(.systemBackground))
            .navigationTitle("Search")
            .navigationBarTitleDisplayMode(.large)
            .searchable(
                text: $searchText,
                placement: .navigationBarDrawer(displayMode: .always),
                prompt: "Search articles"
            )
            .onChange(of: searchText) { _, newValue in
                let query = newValue.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !query.isEmpty else {
                    semanticResults = []
                    return
                }
                Task {
                    try? await Task.sleep(for: .milliseconds(400))
                    guard searchText.trimmingCharacters(in: .whitespacesAndNewlines) == query else { return }
                    await performSemanticSearch(query: query)
                }
            }
            .task {
                await loadCategories()
            }
        }
    }

    private func performSemanticSearch(query: String) async {
        guard let token = AuthService.shared.getAccessToken() else { return }
        isSearching = true
        do {
            semanticResults = try await BackendService.shared.semanticSearch(
                query: query, limit: 10, accessToken: token
            )
        } catch {
            semanticResults = []
        }
        isSearching = false
    }

    private func loadCategories() async {
        guard let token = AuthService.shared.getAccessToken() else { return }
        if let counts = try? await BackendService.shared.fetchCategories(accessToken: token) {
            categoryCounts = Dictionary(uniqueKeysWithValues: counts.map { ($0.name, $0.count) })
        }
    }
}

// MARK: - Category Grid

private extension SearchView {
    var categoryGridView: some View {
        ScrollView(.vertical, showsIndicators: false) {
            VStack(alignment: .leading, spacing: AppSpacing.lg) {
                Text("Browse")
                    .font(AppTypography.title2)
                    .foregroundColor(BrandColors.textPrimary)
                    .padding(.horizontal, AppSpacing.lg)

                LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: AppSpacing.md) {
                    ForEach(Self.defaultCategories, id: \.name) { category in
                        Button {
                            searchText = category.name.capitalized
                        } label: {
                            VStack(alignment: .leading, spacing: AppSpacing.sm) {
                                Image(systemName: category.icon)
                                    .font(.title2)
                                    .foregroundColor(.white)
                                Spacer()
                                HStack {
                                    Text(category.name.capitalized)
                                        .font(AppTypography.headline)
                                        .foregroundColor(.white)
                                    if let count = categoryCounts[category.name] {
                                        Text("(\(count))")
                                            .font(AppTypography.caption1)
                                            .foregroundColor(.white.opacity(0.7))
                                    }
                                }
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(AppSpacing.md)
                            .frame(height: 120)
                            .background(category.color.gradient)
                            .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.large, style: .continuous))
                        }
                        .buttonStyle(PressableButtonStyle())
                    }
                }
                .padding(.horizontal, AppSpacing.lg)
            }
            .padding(.top, AppSpacing.md)
            .padding(.bottom, AppSpacing.xxl)
        }
    }
}

// MARK: - Results Views

private extension SearchView {
    var noResultsState: some View {
        VStack(spacing: AppSpacing.lg) {
            Spacer()

            EmptyStateView(
                icon: "doc.text.magnifyingglass",
                title: "No results",
                subtitle: "Try a different search term."
            )

            Spacer()
        }
        .frame(maxWidth: .infinity)
    }

    var resultsList: some View {
        ScrollView(.vertical, showsIndicators: false) {
            LazyVStack(spacing: 0) {
                ForEach(Array(displayResults.enumerated()), id: \.element.id) { index, article in
                    NavigationLink(destination: ArticleDetailView(article: article)) {
                        FeaturedArticleCard(article: article, isRead: bookmarks.isRead(article.id), style: .feed)
                    }
                    .buttonStyle(PressableButtonStyle())

                    if index < displayResults.count - 1 {
                        HairlineDivider()
                            .padding(.vertical, AppSpacing.md)
                    }
                }
            }
            .padding(.horizontal, AppSpacing.lg)
            .padding(.bottom, AppSpacing.xxl)
        }
    }
}

#Preview {
    SearchView(newsViewModel: NewsViewModel())
}
