//
//  EditionPalette.swift
//  Daily
//
//  Ink + Ochre on warm paper. Single source of truth for the redesign palette.
//  See DESIGN.md "Color Tokens" — hex values mirror that table exactly.
//

import SwiftUI
import UIKit

// MARK: - Hex helpers (file-scoped)

private extension UIColor {
    convenience init(hex: UInt32, alpha: CGFloat = 1.0) {
        let r = CGFloat((hex >> 16) & 0xFF) / 255.0
        let g = CGFloat((hex >> 8) & 0xFF) / 255.0
        let b = CGFloat(hex & 0xFF) / 255.0
        self.init(red: r, green: g, blue: b, alpha: alpha)
    }
}

private func editionDynamic(light: UIColor, dark: UIColor) -> Color {
    Color(uiColor: UIColor { traits in
        traits.userInterfaceStyle == .dark ? dark : light
    })
}

// MARK: - EditionPalette

/// Ink + Ochre on warm paper. Two-color signature with one accent (ink-blue) for chrome
/// and one signature (ochre) reserved for the edition stamp + hero provenance line.
///
/// Invariants (from DESIGN.md):
/// - Ochre is used ONLY on the edition stamp and hero provenance. Nowhere else.
/// - No purple, indigo, teal, pink, neon. No gradients except photo vignettes.
/// - Dark mode is warm-near-black (`#15120E`), never pure black.
enum EditionPalette {
    /// Primary background.
    static let paper: Color = editionDynamic(
        light: UIColor(hex: 0xFCFAF7),
        dark: UIColor(hex: 0x15120E)
    )

    /// Subtle surface — sheets, cards where unavoidable.
    static let paperSecondary: Color = editionDynamic(
        light: UIColor(hex: 0xF4EFE6),
        dark: UIColor(hex: 0x1C1916)
    )

    /// Headlines, body, primary text.
    static let ink: Color = editionDynamic(
        light: UIColor(hex: 0x1F1B17),
        dark: UIColor(hex: 0xF0EDE6)
    )

    /// Secondary text, dek/lead-in.
    static let ink60: Color = editionDynamic(
        light: UIColor(hex: 0x1F1B17, alpha: 0.60),
        dark: UIColor(hex: 0xF0EDE6, alpha: 0.65)
    )

    /// Source labels, brand wordmark, tab-bar tint. The chrome accent.
    static let inkBlue: Color = editionDynamic(
        light: UIColor(hex: 0x2D3F5F),
        dark: UIColor(hex: 0x7E92B5)
    )

    /// Signature only: hero provenance line + "MAY 6 · SARAH EDITION" stamp.
    /// Never used on body type. Never used outside these two surfaces.
    static let ochre: Color = editionDynamic(
        light: UIColor(hex: 0xC97D2E),
        dark: UIColor(hex: 0xE0985A)
    )

    /// Hairline rules and subtle dividers.
    static let sepia: Color = editionDynamic(
        light: UIColor(hex: 0xD9CFBF),
        dark: UIColor(hex: 0x2A2520)
    )

    /// Errors only. Calmer than the system bright red.
    static let error: Color = editionDynamic(
        light: UIColor(hex: 0xB23B2E),
        dark: UIColor(hex: 0xD6614F)
    )

    /// On-palette moss for save toasts.
    static let success: Color = editionDynamic(
        light: UIColor(hex: 0x6E8B5F),
        dark: UIColor(hex: 0x88A57A)
    )

    /// 1px hairline rendered at the device's pixel scale (DESIGN.md "Spacing & Radius").
    static var hairlineWidth: CGFloat { 1.0 / UIScreen.main.scale }
}
