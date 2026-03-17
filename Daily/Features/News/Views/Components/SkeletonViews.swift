//
//  SkeletonViews.swift
//  Daily
//

import SwiftUI

// MARK: - Shimmer Modifier

struct ShimmerModifier: ViewModifier {
    @State private var phase: CGFloat = -1

    func body(content: Content) -> some View {
        content
            .overlay(
                LinearGradient(
                    colors: [
                        Color.clear,
                        Color.white.opacity(0.3),
                        Color.clear
                    ],
                    startPoint: .leading,
                    endPoint: .trailing
                )
                .offset(x: phase * 300)
            )
            .clipped()
            .onAppear {
                withAnimation(.linear(duration: 1.5).repeatForever(autoreverses: false)) {
                    phase = 1
                }
            }
    }
}

extension View {
    func shimmer() -> some View {
        modifier(ShimmerModifier())
    }
}

// MARK: - Skeleton Shapes

private struct SkeletonRect: View {
    var width: CGFloat? = nil
    var height: CGFloat = 14
    var cornerRadius: CGFloat = 4

    var body: some View {
        RoundedRectangle(cornerRadius: cornerRadius)
            .fill(Color(.tertiarySystemFill))
            .frame(width: width, height: height)
            .shimmer()
    }
}

// MARK: - Featured Card Skeleton

struct SkeletonFeaturedCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm + 2) {
            SkeletonRect(height: 200, cornerRadius: 10)

            HStack(spacing: AppSpacing.xs) {
                SkeletonRect(width: 60, height: 10)
                SkeletonRect(width: 40, height: 10)
            }

            SkeletonRect(height: 20)
            SkeletonRect(width: 220, height: 20)

            SkeletonRect(height: 14)
        }
    }
}

// MARK: - Compact Row Skeleton

struct SkeletonCompactRow: View {
    var body: some View {
        HStack(alignment: .top, spacing: AppSpacing.md) {
            VStack(alignment: .leading, spacing: AppSpacing.xs + 2) {
                HStack(spacing: AppSpacing.xs) {
                    SkeletonRect(width: 50, height: 10)
                    SkeletonRect(width: 30, height: 10)
                }

                SkeletonRect(height: 16)
                SkeletonRect(width: 180, height: 16)
            }

            Spacer(minLength: 0)

            SkeletonRect(width: 75, height: 75, cornerRadius: AppCornerRadius.small)
        }
        .padding(.vertical, AppSpacing.md)
    }
}
