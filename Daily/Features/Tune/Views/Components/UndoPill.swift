//
//  UndoPill.swift
//  Daily
//
//  Small pill shown at the top corner of the Tune surface for 10 minutes
//  after a diff toast clears. Tapping invokes the Undo closure.
//
//  TODO(backend): real Undo requires an endpoint that reverses the last
//  weight-diff. Until then, tapping this pill is a no-op + clear.
//

import SwiftUI

struct UndoPill: View {
    let label: String
    let onTap: () -> Void

    var body: some View {
        Button(action: {
            HapticService.impact(.light)
            onTap()
        }) {
            HStack(spacing: AppSpacing.xs) {
                Image(systemName: "arrow.uturn.backward")
                    .font(.system(size: 11, weight: .semibold))
                Text(label)
                    .font(AppTypography.metaCaps)
                    .tracking(0.8)
                    .textCase(.uppercase)
            }
            .foregroundStyle(EditionPalette.inkBlue)
            .padding(.horizontal, AppSpacing.smLg)
            .padding(.vertical, AppSpacing.sm)
            .background(
                RoundedRectangle(cornerRadius: AppCornerRadius.button, style: .continuous)
                    .fill(EditionPalette.paperSecondary)
                    .overlay(
                        RoundedRectangle(cornerRadius: AppCornerRadius.button, style: .continuous)
                            .stroke(EditionPalette.sepia, lineWidth: 1)
                    )
            )
        }
        .buttonStyle(.plain)
    }
}

#Preview {
    UndoPill(label: "Undo") {}
        .padding()
        .background(EditionPalette.paper)
}
