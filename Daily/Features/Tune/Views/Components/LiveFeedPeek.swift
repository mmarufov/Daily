//
//  LiveFeedPeek.swift
//  Daily
//
//  The user's current feed shown beneath the Tune composer. Mutates as
//  tuning turns complete. Per DESIGN.md "Feed mutation: rows slide out
//  250ms, new rows slide in 350ms, ease-out".
//

import SwiftUI

struct LiveFeedPeek: View {
    let articles: [NewsArticle]
    var onTapArticle: (NewsArticle) -> Void = { _ in }

    var body: some View {
        VStack(spacing: 0) {
            if articles.isEmpty {
                emptyState
            } else {
                ForEach(Array(articles.enumerated()), id: \.element.id) { index, article in
                    Button {
                        onTapArticle(article)
                    } label: {
                        StoryRow(article: article)
                    }
                    .buttonStyle(PressableButtonStyle())
                    .transition(.opacity.combined(with: .move(edge: .leading)))

                    if index < articles.count - 1 {
                        Rectangle()
                            .fill(EditionPalette.sepia)
                            .frame(height: EditionPalette.hairlineWidth)
                    }
                }
            }
        }
        .animation(.easeOut(duration: 0.35), value: articles.map(\.id))
    }

    private var emptyState: some View {
        VStack(spacing: AppSpacing.sm) {
            Text("No stories yet.")
                .font(AppTypography.dek)
                .italic()
                .foregroundStyle(EditionPalette.ink60)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, AppSpacing.xxl)
    }
}

#Preview("Empty") {
    LiveFeedPeek(articles: [])
        .background(EditionPalette.paper)
}
