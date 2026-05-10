//
//  HeroStory.swift
//  Daily
//
//  The single hero story at the top of the Feed.
//  Full-bleed image (no card border, no rounded corners), source row,
//  serif bold headline, italic dek, optional ochre provenance line.
//  See DESIGN.md "Per-Surface Specifications → Feed → Hero Story".
//

import SwiftUI

/// Full-bleed editorial hero. Provenance line appears ONLY here (hero only,
/// high-confidence only). Earlier-today rows show no provenance.
struct HeroStory: View {
    let article: NewsArticle
    /// Pass `nil` to hide the provenance line. Pass an already-sanitized
    /// canonical-topic string when confidence is high. See `ProvenanceLine` for
    /// sanitization rules.
    var provenance: String? = nil
    var isRead: Bool = false

    private static let imageHeight: CGFloat = 240

    private var sourceLine: String {
        var parts: [String] = []
        if !article.displaySource.isEmpty {
            parts.append(article.displaySource)
        }
        if !article.formattedDate.isEmpty {
            parts.append(article.formattedDate)
        }
        parts.append("\(article.estimatedReadingTime) min")
        return parts.joined(separator: " · ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.smLg) {
            heroImage
                .frame(maxWidth: .infinity)
                .frame(height: Self.imageHeight)
                .clipped()
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: AppSpacing.sm) {
                HStack(spacing: AppSpacing.xs) {
                    if !isRead {
                        Circle()
                            .fill(EditionPalette.inkBlue)
                            .frame(width: 6, height: 6)
                    }
                    Text(sourceLine)
                        .font(AppTypography.metaCaps)
                        .tracking(0.8)
                        .textCase(.uppercase)
                        .foregroundStyle(EditionPalette.inkBlue)
                        .lineLimit(1)
                }

                Text(article.title)
                    .font(AppTypography.heroHeadline)
                    .tracking(-0.5)
                    .foregroundStyle(EditionPalette.ink)
                    .lineLimit(3)
                    .lineSpacing(4)
                    .multilineTextAlignment(.leading)

                if let summary = article.summary, !summary.isEmpty {
                    Text(summary)
                        .font(AppTypography.dek)
                        .italic()
                        .foregroundStyle(EditionPalette.ink60)
                        .lineLimit(2)
                        .lineSpacing(3)
                        .multilineTextAlignment(.leading)
                }

                if let provenance, !provenance.isEmpty {
                    ProvenanceLine(text: provenance)
                        .padding(.top, AppSpacing.xs)
                }
            }
            .padding(.horizontal, AppSpacing.md)
        }
        .padding(.bottom, AppSpacing.md)
        .background(EditionPalette.paper)
        .accessibilityElement(children: .combine)
        .accessibilityAddTraits(isRead ? [.isButton, .isSelected] : .isButton)
    }

    @ViewBuilder
    private var heroImage: some View {
        if let urlString = article.imageURL, let url = URL(string: urlString) {
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image.resizable().aspectRatio(contentMode: .fill)
                default:
                    EditionPalette.paperSecondary
                }
            }
        } else {
            EditionPalette.paperSecondary
        }
    }
}

#if DEBUG
private extension NewsArticle {
    static let heroStoryPreview = NewsArticle(
        id: "preview-hero",
        title: "Erlang creators receive ACM SIGPLAN award for distributed systems contributions",
        summary: "The team behind Erlang/OTP earns lifetime recognition for two decades of work on fault tolerance and concurrent computation.",
        content: nil,
        author: "Joe Armstrong",
        source: "Bloomberg",
        imageURL: nil,
        publishedAt: Date().addingTimeInterval(-7200),
        category: "tech",
        url: nil
    )
}

#Preview("With provenance — light") {
    HeroStory(
        article: .heroStoryPreview,
        provenance: "FROM YOUR INTRO: TECH"
    )
}

#Preview("Without provenance — light") {
    HeroStory(article: .heroStoryPreview)
}

#Preview("Earned state — dark") {
    HeroStory(
        article: .heroStoryPreview,
        provenance: "BECAUSE YOU TUNED FOR ERLANG TUE"
    )
    .preferredColorScheme(.dark)
}
#endif
