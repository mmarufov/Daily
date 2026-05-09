//
//  SuggestedPromptChip.swift
//  Daily
//
//  Single hairline-bordered chip used for first-open suggestions on Tune.
//  Three of these appear below the composer until the user sends their first
//  turn. Per DESIGN.md "No full pills" — chips use a 12pt button radius.
//

import SwiftUI

struct SuggestedPromptChip: View {
    let title: String
    let onTap: () -> Void

    var body: some View {
        Button(action: {
            HapticService.impact(.light)
            onTap()
        }) {
            Text(title)
                .font(AppTypography.composer)
                .foregroundStyle(EditionPalette.ink60)
                .padding(.horizontal, AppSpacing.smLg)
                .padding(.vertical, AppSpacing.sm)
                .overlay(
                    RoundedRectangle(cornerRadius: AppCornerRadius.button, style: .continuous)
                        .stroke(EditionPalette.sepia, lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
    }
}

#Preview {
    HStack(spacing: AppSpacing.sm) {
        SuggestedPromptChip(title: "Less national news") {}
        SuggestedPromptChip(title: "More startups") {}
    }
    .padding()
    .background(EditionPalette.paper)
}
