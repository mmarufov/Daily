//
//  ArticleContextHeader.swift
//  Daily
//
//  Replaces LiveFeedPeek when Tune is in article-discussion mode (the user
//  tapped Discuss on an article). Shows the focused article and frames the
//  tuning prompt around it.
//

import SwiftUI

struct ArticleContextHeader: View {
    let article: NewsArticle

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm) {
            Text("Tuning for this story")
                .font(AppTypography.metaCaps)
                .tracking(0.8)
                .textCase(.uppercase)
                .foregroundStyle(EditionPalette.inkBlue)
                .padding(.horizontal, AppSpacing.md)

            StoryRow(article: article)

            Rectangle()
                .fill(EditionPalette.sepia)
                .frame(height: EditionPalette.hairlineWidth)

            Text("Try: \"less like this\", \"more deep dives\", \"why was this picked\"")
                .font(AppTypography.dek)
                .italic()
                .foregroundStyle(EditionPalette.ink60)
                .padding(.horizontal, AppSpacing.md)
                .padding(.top, AppSpacing.sm)
        }
        .padding(.top, AppSpacing.md)
    }
}

#if DEBUG
private extension NewsArticle {
    static let contextPreview = NewsArticle(
        id: "ctx-preview",
        title: "Sample focused article for context header",
        summary: nil,
        content: nil,
        author: nil,
        source: "Bloomberg",
        imageURL: nil,
        publishedAt: Date().addingTimeInterval(-7200),
        category: "tech",
        url: nil
    )
}

#Preview {
    ArticleContextHeader(article: .contextPreview)
        .background(EditionPalette.paper)
}
#endif
