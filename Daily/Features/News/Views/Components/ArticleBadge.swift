//
//  ArticleBadge.swift
//  Daily
//

import SwiftUI

struct ArticleBadge: View {
    let publishedAt: Date?

    var body: some View {
        if let date = publishedAt {
            let hours = Date().timeIntervalSince(date) / 3600
            if hours < 2 {
                badgeLabel("BREAKING", color: BrandColors.error)
            } else if hours < 6 {
                badgeLabel("NEW", color: BrandColors.primary)
            }
        }
    }

    private func badgeLabel(_ text: String, color: Color) -> some View {
        Text(text)
            .font(.system(size: 9, weight: .bold))
            .tracking(0.5)
            .foregroundColor(.white)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Capsule().fill(color))
    }
}
