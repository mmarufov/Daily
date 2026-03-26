//
//  BookmarksView.swift
//  Daily
//

import SwiftUI

struct BookmarksView: View {
    @ObservedObject private var bookmarks = BookmarkService.shared

    var body: some View {
        NavigationStack {
            Group {
                if bookmarks.bookmarkedArticles.isEmpty {
                    EmptyStateView(
                        icon: "bookmark",
                        title: "No saved articles",
                        subtitle: "Bookmark articles while reading to find them here later."
                    )
                } else {
                    ScrollView(.vertical, showsIndicators: false) {
                        LazyVStack(spacing: 0) {
                            ForEach(bookmarks.bookmarkedArticles) { entry in
                                NavigationLink(destination: ArticleDetailView(article: entry.article)) {
                                    EditorialRow(article: entry.article)
                                }
                                .buttonStyle(PressableButtonStyle())
                                .swipeActions(edge: .trailing) {
                                    Button(role: .destructive) {
                                        HapticService.impact(.medium)
                                        bookmarks.toggleBookmark(entry.article)
                                    } label: {
                                        Label("Remove", systemImage: "bookmark.slash")
                                    }
                                }

                                HairlineDivider()
                                    .padding(.leading, AppSpacing.lg)
                            }
                        }
                        .padding(.horizontal, AppSpacing.lg)
                    }
                }
            }
            .background(Color(.systemBackground))
            .navigationTitle("Saved")
            .navigationBarTitleDisplayMode(.large)
        }
    }
}

#Preview {
    BookmarksView()
}
