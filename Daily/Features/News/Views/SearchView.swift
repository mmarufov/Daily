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

    private var searchResults: [NewsArticle] {
        let query = searchText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !query.isEmpty else { return [] }

        let articles = newsViewModel.articles

        return articles.filter { article in
            article.title.localizedCaseInsensitiveContains(query)
            || (article.summary?.localizedCaseInsensitiveContains(query) == true)
            || (article.source?.localizedCaseInsensitiveContains(query) == true)
            || (article.author?.localizedCaseInsensitiveContains(query) == true)
            || (article.category?.localizedCaseInsensitiveContains(query) == true)
        }
    }

    var body: some View {
        NavigationStack {
            Group {
                if searchText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    emptyState
                } else if searchResults.isEmpty {
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
        }
    }
}

// MARK: - Private Views

private extension SearchView {
    var emptyState: some View {
        VStack(spacing: AppSpacing.lg) {
            Spacer()

            Image(systemName: "magnifyingglass")
                .font(AppTypography.iconHeroXL)
                .foregroundColor(BrandColors.textQuaternary)

            VStack(spacing: AppSpacing.sm) {
                Text("Search your feed")
                    .font(AppTypography.title3)
                    .foregroundColor(BrandColors.textPrimary)

                Text("Find articles by title, source, author, or topic.")
                    .font(AppTypography.subheadline)
                    .foregroundColor(BrandColors.textSecondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, AppSpacing.xl)
            }

            Spacer()
        }
        .frame(maxWidth: .infinity)
    }

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
                ForEach(Array(searchResults.enumerated()), id: \.element.id) { index, article in
                    NavigationLink(destination: ArticleDetailView(article: article)) {
                        EditorialRow(article: article, isRead: bookmarks.isRead(article.id))
                    }
                    .buttonStyle(PressableButtonStyle())

                    if index < searchResults.count - 1 {
                        HairlineDivider()
                            .padding(.leading, AppSpacing.lg)
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
