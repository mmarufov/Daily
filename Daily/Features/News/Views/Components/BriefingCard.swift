//
//  BriefingCard.swift
//  Daily
//
//  Editorial briefing card shown at the top of the feed.
//  Compact by default — tap to expand and read the full briefing.
//

import SwiftUI

struct BriefingCard: View {
    let content: String
    @State private var isExpanded = false

    private var bulletPoints: [String] {
        content
            .components(separatedBy: "\n")
            .map { line in
                line.trimmingCharacters(in: .whitespacesAndNewlines)
                    .replacingOccurrences(of: "^[•\\-\\*\\d+\\.]+\\s*", with: "", options: .regularExpression)
            }
            .filter { !$0.isEmpty }
    }

    private var teaserLine: String {
        switch bulletPoints.count {
        case 3:
            return "Three signals worth your attention today."
        case 2:
            return "Two shifts worth tracking right now."
        default:
            return "The few stories actually worth your attention."
        }
    }

    var body: some View {
        Button {
            withAnimation(.snappy(duration: 0.38, extraBounce: 0.08)) {
                isExpanded.toggle()
            }
        } label: {
            VStack(alignment: .leading, spacing: 0) {
                collapsedHeader

                if isExpanded {
                    expandedContent
                        .transition(
                            .opacity.combined(with: .scale(scale: 0.98, anchor: .top))
                        )
                }
            }
            .padding(.vertical, AppSpacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
            .contentShape(Rectangle())
            .clipped()
        }
        .buttonStyle(BriefingCardButtonStyle())
    }
}

// MARK: - Subviews

private extension BriefingCard {
    var collapsedHeader: some View {
        VStack(alignment: .leading, spacing: AppSpacing.md) {
            VStack(alignment: .leading, spacing: AppSpacing.xs) {
                Text("MORNING BRIEFING")
                    .font(AppTypography.sectionTitle)
                    .foregroundColor(BrandColors.sectionHeader)
                    .tracking(0.8)

                Text("What matters today")
                    .font(AppTypography.headline)
                    .foregroundColor(BrandColors.textPrimary)

                Text(teaserLine)
                    .font(AppTypography.articleLeadIn)
                    .foregroundColor(BrandColors.textPrimary)
                    .lineSpacing(2)
                    .multilineTextAlignment(.leading)
            }

            HStack(spacing: AppSpacing.sm) {
                Circle()
                    .fill(BrandColors.primary.opacity(0.85))
                    .frame(width: 6, height: 6)

                Text("\(bulletPoints.count) key updates")
                    .font(AppTypography.caption1)
                    .foregroundColor(BrandColors.textSecondary)

                Spacer()

                HStack(spacing: 4) {
                    Text(isExpanded ? "Hide" : "Open")
                        .font(AppTypography.caption2)
                    Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                        .font(.system(size: 8, weight: .semibold))
                }
                .foregroundColor(BrandColors.textTertiary)
            }

            HairlineDivider()
        }
    }

    var expandedContent: some View {
        VStack(alignment: .leading, spacing: AppSpacing.md) {
            ForEach(Array(bulletPoints.enumerated()), id: \.offset) { index, point in
                HStack(alignment: .top, spacing: AppSpacing.smLg) {
                    Text("\(index + 1)")
                        .font(AppTypography.metaLabel)
                        .foregroundStyle(BrandColors.primary)
                        .frame(width: 18, alignment: .leading)
                        .padding(.top, 2)

                    Text(markdownAttributed(point))
                        .font(AppTypography.bodyMedium)
                        .foregroundColor(BrandColors.textPrimary)
                        .lineSpacing(3)
                        .multilineTextAlignment(.leading)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
        .padding(.top, AppSpacing.md)
    }

    func markdownAttributed(_ text: String) -> AttributedString {
        if let attributed = try? AttributedString(
            markdown: text,
            options: AttributedString.MarkdownParsingOptions(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        ) {
            return attributed
        }

        return AttributedString(text)
    }
}

private struct BriefingCardButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.985 : 1)
            .opacity(configuration.isPressed ? 0.92 : 1)
            .animation(.easeOut(duration: 0.16), value: configuration.isPressed)
    }
}
