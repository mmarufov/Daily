//
//  StoryRow.swift
//  Daily
//
//  Uniform row used on Feed (Earlier-today), Saved, and Search results.
//  See DESIGN.md "Layout Doctrine — Hero + Rows".
//

import SwiftUI

/// Image-right 80×80pt thumbnail with 6pt corners, headline-left
/// (rowHeadline 2-line max), source row (metaCaps inkBlue 10pt).
/// **No provenance line** — provenance is rare and lives only on the hero or in
/// the long-press sheet.
///
/// Caller is responsible for hairline dividers between rows (use a List with
/// `.listRowSeparator` or wrap in a VStack with explicit hairlines).
struct StoryRow: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.displayScale) private var displayScale
    let article: NewsArticle
    var isRead: Bool = false

    private var sourceLine: String {
        var parts: [String] = []
        if !article.displaySource.isEmpty {
            parts.append(article.displaySource)
        }
        if !article.formattedDate.isEmpty {
            parts.append(article.formattedDate)
        }
        return parts.joined(separator: " · ")
    }

    var body: some View {
        HStack(alignment: .top, spacing: AppSpacing.smLg) {
            VStack(alignment: .leading, spacing: AppSpacing.xs) {
                if !sourceLine.isEmpty {
                    Text(sourceLine)
                        .font(AppTypography.metaCaps)
                        .tracking(0.8)
                        .textCase(.uppercase)
                        .foregroundStyle(EditionPalette.inkBlue)
                        .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 1)
                }
                Text(article.title)
                    .font(AppTypography.rowHeadline)
                    .foregroundStyle(EditionPalette.ink)
                    .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 2)
                    .lineSpacing(2)
                    .multilineTextAlignment(.leading)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            if article.displayImageURL != nil && !dynamicTypeSize.isAccessibilitySize {
                thumbnail
                .frame(width: 80, height: 80)
                .clipShape(RoundedRectangle(cornerRadius: 6, style: .continuous))
                .accessibilityHidden(true)
            }
        }
        .padding(.vertical, AppSpacing.smLg)
        .padding(.horizontal, AppSpacing.md)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityValue(isRead ? "Opened" : "Not opened")
    }

    @ViewBuilder
    private var thumbnail: some View {
        if let url = article.displayImageURL {
            ArticleRemoteImage(url: url, pixelSize: Int(80 * displayScale))
        } else {
            EditionPalette.paperSecondary
        }
    }
}

#if DEBUG
private extension NewsArticle {
    static let storyRowPreview = NewsArticle(
        id: "preview-row",
        title: "Erlang creators receive ACM SIGPLAN award for distributed systems contributions",
        summary: "The team behind Erlang/OTP earns lifetime recognition for two decades of work on fault tolerance.",
        content: nil,
        author: "Joe Armstrong",
        source: "Bloomberg",
        imageURL: nil,
        publishedAt: Date().addingTimeInterval(-7200),
        category: "tech",
        url: nil
    )
}

#Preview("Unread — light") {
    StoryRow(article: .storyRowPreview)
        .background(EditionPalette.paper)
}

#Preview("Read — light") {
    StoryRow(article: .storyRowPreview, isRead: true)
        .background(EditionPalette.paper)
}

#Preview("Stack of rows") {
    VStack(spacing: 0) {
        ForEach(0..<3, id: \.self) { _ in
            StoryRow(article: .storyRowPreview)
            Rectangle()
                .fill(EditionPalette.sepia)
                .frame(height: EditionPalette.hairlineWidth)
        }
    }
    .background(EditionPalette.paper)
}

#Preview("Dark") {
    StoryRow(article: .storyRowPreview)
        .background(EditionPalette.paper)
        .preferredColorScheme(.dark)
}
#endif
