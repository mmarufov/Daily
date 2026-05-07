//
//  EditionHeader.swift
//  Daily
//
//  Wordmark + edition signature at the top of the Feed (and any surface
//  that carries the edition identity). See DESIGN.md "Per-Surface Specifications → Feed".
//

import SwiftUI

/// "Daily" wordmark in serif bold ink + "MAY 7 · SARAH EDITION" signature line in
/// small-caps ochre. 44pt avatar slot trailing (touch-target a11y fix per DESIGN.md).
/// Sepia hairline below.
struct EditionHeader<Avatar: View>: View {
    /// e.g. "MAY 7"
    let dateLabel: String
    /// e.g. "SARAH" — first name or display name; rendered uppercased.
    let editionName: String
    /// 44×44 avatar — caller decides Image, initials, or placeholder.
    @ViewBuilder var avatar: () -> Avatar

    private var signature: String {
        "\(dateLabel) · \(editionName) EDITION"
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .center, spacing: AppSpacing.md) {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Daily")
                        .font(AppTypography.brandWordmark)
                        .tracking(-0.5)
                        .foregroundStyle(EditionPalette.ink)
                    Text(signature)
                        .font(AppTypography.signatureCaps)
                        .tracking(1.0)
                        .textCase(.uppercase)
                        .foregroundStyle(EditionPalette.ochre)
                }
                Spacer(minLength: AppSpacing.md)
                avatar()
                    .frame(width: 44, height: 44)
                    .clipShape(Circle())
                    .accessibilityAddTraits(.isButton)
            }
            .padding(.horizontal, AppSpacing.md)
            .padding(.vertical, AppSpacing.smLg)

            Rectangle()
                .fill(EditionPalette.sepia)
                .frame(height: EditionPalette.hairlineWidth)
        }
        .background(EditionPalette.paper)
    }
}

#Preview("Light") {
    EditionHeader(dateLabel: "MAY 7", editionName: "SARAH") {
        Circle().fill(EditionPalette.inkBlue)
    }
    .background(EditionPalette.paper)
}

#Preview("Long name") {
    EditionHeader(dateLabel: "MAY 7", editionName: "ALEXANDRA") {
        Circle().fill(EditionPalette.inkBlue)
    }
    .background(EditionPalette.paper)
}

#Preview("Dark") {
    EditionHeader(dateLabel: "MAY 7", editionName: "SARAH") {
        Circle().fill(EditionPalette.inkBlue)
    }
    .background(EditionPalette.paper)
    .preferredColorScheme(.dark)
}
