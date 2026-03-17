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
                .font(.system(size: 36, weight: .ultraLight))
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
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundColor(.white)
                        .padding(.horizontal, AppSpacing.xl)
                        .padding(.vertical, AppSpacing.sm + 2)
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
