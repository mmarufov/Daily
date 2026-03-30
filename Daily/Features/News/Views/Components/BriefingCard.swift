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
                line.trimmingCharacters(in: .whitespaces)
                    .replacingOccurrences(of: "^[•\\-\\*\\d+\\.]+\\s*", with: "", options: .regularExpression)
            }
            .filter { !$0.isEmpty }
    }

    var body: some View {
        Button {
            withAnimation(.spring(response: 0.35, dampingFraction: 0.85)) {
                isExpanded.toggle()
            }
        } label: {
            VStack(alignment: .leading, spacing: 0) {
                collapsedHeader

                if isExpanded {
                    expandedContent
                        .transition(.opacity.combined(with: .move(edge: .top)))
                }
            }
            .padding(AppSpacing.md)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(BrandColors.cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.card, style: .continuous))
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Subviews

private extension BriefingCard {
    var collapsedHeader: some View {
        HStack(spacing: AppSpacing.smLg) {
            // Icon
            Image(systemName: "newspaper.fill")
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(BrandColors.primary)
                .frame(width: 30, height: 30)
                .background(BrandColors.primary.opacity(0.10))
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(alignment: .leading, spacing: 2) {
                Text("Your Briefing")
                    .font(AppTypography.headline)
                    .foregroundColor(BrandColors.textPrimary)

                if !isExpanded {
                    Text(previewText)
                        .font(AppTypography.subheadline)
                        .foregroundColor(BrandColors.textSecondary)
                        .lineLimit(1)
                }
            }

            Spacer()

            Image(systemName: "chevron.right")
                .font(.system(size: 12, weight: .semibold))
                .foregroundColor(BrandColors.textTertiary)
                .rotationEffect(.degrees(isExpanded ? 90 : 0))
        }
    }

    var expandedContent: some View {
        VStack(alignment: .leading, spacing: AppSpacing.smLg) {
            HairlineDivider()
                .padding(.top, AppSpacing.smLg)

            ForEach(Array(bulletPoints.enumerated()), id: \.offset) { index, point in
                HStack(alignment: .top, spacing: AppSpacing.smLg) {
                    Text("\(index + 1)")
                        .font(.system(size: 13, weight: .bold, design: .rounded))
                        .foregroundStyle(BrandColors.primary)
                        .frame(width: 22, height: 22)
                        .background(BrandColors.primary.opacity(0.10))
                        .clipShape(Circle())

                    Text(point)
                        .font(AppTypography.subheadline)
                        .foregroundColor(BrandColors.textSecondary)
                        .lineSpacing(3)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    var previewText: String {
        let first = bulletPoints.first ?? content.prefix(60).description
        if first.count > 55 {
            return String(first.prefix(55)) + "..."
        }
        return first
    }
}
