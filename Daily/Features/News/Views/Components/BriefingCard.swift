//
//  BriefingCard.swift
//  Daily
//
//  Editorial briefing card shown at the top of the feed.
//  Displays a 3-point synthesized briefing personalized to the user.
//

import SwiftUI

struct BriefingCard: View {
    let content: String

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm) {
            Text("Your Briefing")
                .font(AppTypography.sectionTitle)
                .foregroundColor(BrandColors.textPrimary)

            Text(content)
                .font(AppTypography.body)
                .foregroundColor(BrandColors.textSecondary)
                .lineSpacing(4)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(AppSpacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(BrandColors.cardBackground)
        .cornerRadius(AppCornerRadius.card)
    }
}
