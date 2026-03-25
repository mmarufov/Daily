//
//  EmptyStateView.swift
//  Daily
//

import SwiftUI

struct EmptyStateView: View {
    let icon: String
    let title: String
    let subtitle: String
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil

    var body: some View {
        VStack(spacing: AppSpacing.md) {
            Image(systemName: icon)
                .font(AppTypography.emptyStateIcon)
                .foregroundColor(BrandColors.textTertiary)

            VStack(spacing: AppSpacing.xs) {
                Text(title)
                    .font(AppTypography.headline)
                    .foregroundColor(BrandColors.textPrimary)

                Text(subtitle)
                    .font(AppTypography.subheadline)
                    .foregroundColor(BrandColors.textSecondary)
                    .multilineTextAlignment(.center)
            }

            if let actionTitle, let action {
                Button(action: action) {
                    Text(actionTitle)
                        .font(AppTypography.actionLabel)
                        .foregroundColor(.white)
                        .padding(.horizontal, AppSpacing.xl)
                        .padding(.vertical, AppSpacing.smPlus)
                        .background(
                            Capsule().fill(BrandColors.primary)
                        )
                }
                .padding(.top, AppSpacing.sm)
            }
        }
        .frame(maxWidth: .infinity)
    }
}
