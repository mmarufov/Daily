//
//  WhyThisStorySheet.swift
//  Daily
//
//  Long-press sheet from any story row. Per DESIGN.md: "Per-row reasoning lives
//  in a long-press sheet."
//

import SwiftUI

/// Sheet shown on long-press of any story row. Displays the paraphrased reason
/// (already-sanitized — see ProvenanceLine) and three corrective actions:
/// Less of this · Wrong reason · Hide this story.
///
/// Action handlers are caller-owned closures; this view does not wire to the
/// taste model directly.
struct WhyThisStorySheet: View {
    let reason: String
    var onLessOfThis: () -> Void = {}
    var onWrongReason: () -> Void = {}
    var onHide: () -> Void = {}

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.lg) {
            VStack(alignment: .leading, spacing: AppSpacing.sm) {
                Text("Why this story")
                    .font(AppTypography.metaCaps)
                    .tracking(0.8)
                    .textCase(.uppercase)
                    .foregroundStyle(EditionPalette.inkBlue)

                Text(reason)
                    .font(AppTypography.dek)
                    .italic()
                    .foregroundStyle(EditionPalette.ink60)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
            }

            VStack(spacing: 0) {
                actionRow("Less of this") { onLessOfThis(); dismiss() }
                hairline
                actionRow("Wrong reason") { onWrongReason(); dismiss() }
                hairline
                actionRow("Hide this story") { onHide(); dismiss() }
            }
            .overlay(
                RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous)
                    .stroke(EditionPalette.sepia, lineWidth: EditionPalette.hairlineWidth)
            )

            Spacer(minLength: 0)
        }
        .padding(AppSpacing.lg)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(EditionPalette.paper)
        .presentationDetents([.medium])
        .presentationDragIndicator(.visible)
    }

    private func actionRow(_ title: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack {
                Text(title)
                    .font(AppTypography.bodyReading)
                    .foregroundStyle(EditionPalette.ink)
                Spacer()
            }
            .padding(.horizontal, AppSpacing.md)
            .padding(.vertical, AppSpacing.smLg)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private var hairline: some View {
        Rectangle()
            .fill(EditionPalette.sepia)
            .frame(height: EditionPalette.hairlineWidth)
    }
}

#Preview("Cold start") {
    Color.gray.ignoresSafeArea()
        .sheet(isPresented: .constant(true)) {
            WhyThisStorySheet(
                reason: "You told me you wanted more tech and startups in your daily edition."
            )
        }
}

#Preview("Earned") {
    Color.gray.ignoresSafeArea()
        .sheet(isPresented: .constant(true)) {
            WhyThisStorySheet(
                reason: "You've been reading distributed-systems pieces this week and tuned for Erlang on Tuesday."
            )
        }
}

#Preview("Dark") {
    Color.gray.ignoresSafeArea()
        .sheet(isPresented: .constant(true)) {
            WhyThisStorySheet(
                reason: "You told me you wanted more tech and startups in your daily edition."
            )
        }
        .preferredColorScheme(.dark)
}
