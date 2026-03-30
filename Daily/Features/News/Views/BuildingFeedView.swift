//
//  BuildingFeedView.swift
//  Daily
//
//  Progress UI during source discovery + feed build.
//

import SwiftUI

struct BuildingFeedView: View {
    let phase: NewsViewModel.SetupPhase
    let detailText: String?

    @State private var animateIcon = false

    var body: some View {
        VStack(spacing: AppSpacing.xl) {
            Spacer()

            // Animated icon
            Image(systemName: phase == .discovering ? "antenna.radiowaves.left.and.right" : "newspaper.fill")
                .font(.system(size: 48, weight: .light))
                .foregroundStyle(BrandColors.primary)
                .symbolEffect(.pulse, options: .repeating)
                .scaleEffect(animateIcon ? 1.05 : 0.95)
                .animation(.easeInOut(duration: 1.5).repeatForever(autoreverses: true), value: animateIcon)

            VStack(spacing: AppSpacing.md) {
                Text(phase.title)
                    .font(AppTypography.title3)
                    .foregroundColor(BrandColors.textPrimary)

                Text(phase.subtitle)
                    .font(AppTypography.subheadline)
                    .foregroundColor(BrandColors.textSecondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, AppSpacing.xxl)
            }

            if let detail = detailText, !detail.isEmpty {
                HStack(spacing: AppSpacing.sm) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(BrandColors.success)
                        .font(AppTypography.body)
                    Text(detail)
                        .font(AppTypography.bodySmall)
                        .foregroundColor(BrandColors.textTertiary)
                }
                .transition(.move(edge: .bottom).combined(with: .opacity))
            }

            ProgressView()
                .scaleEffect(1.1)
                .tint(BrandColors.primary)
                .padding(.top, AppSpacing.sm)

            Text("This takes about 30–60 seconds.\nWe're finding the best sources for you.")
                .font(AppTypography.caption1)
                .foregroundColor(BrandColors.textQuaternary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, AppSpacing.xxl)

            Spacer()
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color(.systemBackground))
        .onAppear { animateIcon = true }
    }
}

#Preview {
    BuildingFeedView(
        phase: .discovering,
        detailText: "12 sources selected"
    )
}
