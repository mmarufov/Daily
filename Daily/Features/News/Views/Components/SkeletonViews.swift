//
//  SkeletonViews.swift
//  Daily
//

import SwiftUI

// MARK: - Shimmer Modifier

struct ShimmerModifier: ViewModifier {
    @State private var phase: CGFloat = -1
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    func body(content: Content) -> some View {
        content
            .overlay(
                LinearGradient(
                    colors: [
                        Color.clear,
                        Color(UIColor.label).opacity(0.15),
                        Color.clear
                    ],
                    startPoint: .leading,
                    endPoint: .trailing
                )
                .offset(x: phase * 300)
            )
            .clipped()
            .onAppear {
                guard !reduceMotion else { return }
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
        VStack(alignment: .leading, spacing: AppSpacing.smPlus) {
            SkeletonRect(height: 200, cornerRadius: AppCornerRadius.image)

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

// MARK: - Feed Card Skeleton (matches FeaturedArticleCard .feed style)

struct SkeletonFeedCard: View {
    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.smPlus) {
            SkeletonRect(height: 180, cornerRadius: AppCornerRadius.image)

            HStack(spacing: AppSpacing.xs) {
                SkeletonRect(width: 60, height: 10)
                SkeletonRect(width: 40, height: 10)
            }

            SkeletonRect(height: 18)
            SkeletonRect(width: 200, height: 18)

            SkeletonRect(height: 14)
        }
    }
}
