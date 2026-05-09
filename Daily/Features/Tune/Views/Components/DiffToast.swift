//
//  DiffToast.swift
//  Daily
//
//  Ephemeral 2-second weight-diff toast on the Tune surface.
//  See DESIGN.md "Animation & Motion → Diff toast (Tune)".
//

import SwiftUI

/// Two-line toast: weight-deltas line + optional Undo affordance.
/// Pure presentation — caller owns visibility and the 2-second timer.
/// Phase 4 will own the timer + 10-min Undo persistence pill.
///
/// Per DESIGN.md motion spec: slide in 200ms, hold 2000ms, fade out 300ms.
/// Zero-diff turns produce no toast — caller decides whether to instantiate.
struct DiffToast: View {
    /// e.g. "National news ↓ · Startups ↑ · Erlang +"
    let summary: String
    /// Pass `nil` to hide the Undo link.
    var onUndo: (() -> Void)? = nil

    /// Animation timings, exposed as constants so the caller can keep them in sync.
    enum Timing {
        static let slideIn: Double = 0.20
        static let hold: Double = 2.00
        static let fadeOut: Double = 0.30
    }

    var body: some View {
        HStack(alignment: .center, spacing: AppSpacing.smLg) {
            Text(summary)
                .font(AppTypography.metaCaps)
                .tracking(0.8)
                .textCase(.uppercase)
                .foregroundStyle(EditionPalette.ink)
                .lineLimit(2)
                .multilineTextAlignment(.leading)
                .frame(maxWidth: .infinity, alignment: .leading)

            if let onUndo {
                Button(action: onUndo) {
                    Text("Undo")
                        .font(AppTypography.metaCaps)
                        .tracking(0.8)
                        .textCase(.uppercase)
                        .foregroundStyle(EditionPalette.inkBlue)
                }
                .buttonStyle(.plain)
                .accessibilityLabel("Undo last tuning change")
            }
        }
        .padding(.horizontal, AppSpacing.md)
        .padding(.vertical, AppSpacing.smLg)
        .background(
            RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous)
                .fill(EditionPalette.paperSecondary)
                .overlay(
                    RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous)
                        .stroke(EditionPalette.sepia, lineWidth: EditionPalette.hairlineWidth)
                )
        )
    }
}

#Preview("With Undo — light") {
    VStack {
        DiffToast(
            summary: "National news ↓ · Startups ↑ · Erlang +",
            onUndo: {}
        )
        Spacer()
    }
    .padding()
    .background(EditionPalette.paper)
}

#Preview("Without Undo — light") {
    VStack {
        DiffToast(summary: "Erlang +")
        Spacer()
    }
    .padding()
    .background(EditionPalette.paper)
}

#Preview("With Undo — dark") {
    VStack {
        DiffToast(
            summary: "National news ↓ · Startups ↑ · Erlang +",
            onUndo: {}
        )
        Spacer()
    }
    .padding()
    .background(EditionPalette.paper)
    .preferredColorScheme(.dark)
}
