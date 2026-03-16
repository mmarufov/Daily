//
//  AppTheme.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI

// MARK: - Brand Colors (Editorial palette)
struct BrandColors {
    // Primary brand color - Editorial red/vermilion for source labels and accents
    static let primary = Color(red: 0.85, green: 0.18, blue: 0.15)
    static let primaryDark = Color(red: 0.72, green: 0.14, blue: 0.12)
    static let primaryLight = Color(red: 0.92, green: 0.30, blue: 0.25)

    // Accent colors
    static let accent = Color(red: 1.0, green: 0.58, blue: 0.0)
    static let accentLight = Color(red: 1.0, green: 0.65, blue: 0.20)

    // Semantic colors - System colors
    static let success = Color(red: 0.20, green: 0.78, blue: 0.35)
    static let warning = Color(red: 1.0, green: 0.58, blue: 0.0)
    static let error = Color(red: 1.0, green: 0.23, blue: 0.19)

    // Background colors - System backgrounds
    static let background = Color(.systemBackground)
    static let secondaryBackground = Color(.secondarySystemGroupedBackground)
    static let cardBackground = Color(.systemBackground)
    static let tertiaryBackground = Color(.tertiarySystemBackground)

    // Text colors - System labels
    static let textPrimary = Color(.label)
    static let textSecondary = Color(.secondaryLabel)
    static let textTertiary = Color(.tertiaryLabel)
    static let textQuaternary = Color(.quaternaryLabel)
}

// MARK: - Typography (Editorial style)
struct AppTypography {
    // Large Title
    static let largeTitle = Font.system(size: 34, weight: .bold, design: .default)
    static let title1 = Font.system(size: 28, weight: .bold, design: .default)
    static let title2 = Font.system(size: 22, weight: .bold, design: .default)
    static let title3 = Font.system(size: 20, weight: .semibold, design: .default)

    // Headline fonts
    static let headline = Font.system(size: 17, weight: .semibold, design: .default)
    static let headlineMedium = Font.system(size: 16, weight: .semibold, design: .default)
    static let headlineSmall = Font.system(size: 15, weight: .semibold, design: .default)

    // Body fonts
    static let body = Font.system(size: 17, weight: .regular, design: .default)
    static let bodyMedium = Font.system(size: 15, weight: .regular, design: .default)
    static let bodySmall = Font.system(size: 13, weight: .regular, design: .default)

    // Callout
    static let callout = Font.system(size: 16, weight: .regular, design: .default)

    // Subheadline
    static let subheadline = Font.system(size: 15, weight: .regular, design: .default)

    // Footnote
    static let footnote = Font.system(size: 13, weight: .regular, design: .default)

    // Caption
    static let caption1 = Font.system(size: 12, weight: .regular, design: .default)
    static let caption2 = Font.system(size: 11, weight: .regular, design: .default)

    // Label fonts
    static let labelLarge = Font.system(size: 17, weight: .medium, design: .default)
    static let labelMedium = Font.system(size: 15, weight: .medium, design: .default)
    static let labelSmall = Font.system(size: 13, weight: .medium, design: .default)

    // Editorial typography — serif for headlines and reading
    static let feedHeroTitle = Font.system(size: 24, weight: .bold, design: .serif)
    static let feedCardTitle = Font.system(size: 16, weight: .semibold, design: .serif)
    static let sectionTitle = Font.system(size: 13, weight: .bold, design: .default)
    static let sourceLabel = Font.system(size: 12, weight: .bold, design: .default)
    static let dateLabel = Font.system(size: 12, weight: .regular, design: .default)

    // Article-specific typography (New York-style serif for long-form reading)
    static let articleTitle = Font.system(size: 28, weight: .bold, design: .serif)
    static let articleBody = Font.system(size: 19, weight: .regular, design: .serif)

    // Legacy support
    static let displayLarge = Font.system(size: 34, weight: .bold, design: .default)
    static let displayMedium = Font.system(size: 28, weight: .bold, design: .default)
    static let displaySmall = Font.system(size: 22, weight: .bold, design: .default)
    static let headlineLarge = Font.system(size: 20, weight: .semibold, design: .default)
    static let bodyLarge = Font.system(size: 17, weight: .regular, design: .default)
}

// MARK: - Spacing
struct AppSpacing {
    static let xs: CGFloat = 4
    static let sm: CGFloat = 8
    static let md: CGFloat = 16
    static let lg: CGFloat = 24
    static let xl: CGFloat = 32
    static let xxl: CGFloat = 48
}

// MARK: - Corner Radius
struct AppCornerRadius {
    static let small: CGFloat = 8
    static let medium: CGFloat = 12
    static let large: CGFloat = 16
    static let xlarge: CGFloat = 20
    static let round: CGFloat = 999

    static let card: CGFloat = 16
    static let button: CGFloat = 12
    static let sheet: CGFloat = 20
}

// MARK: - Shadows
struct AppShadows {
    static let small = Shadow(color: .black.opacity(0.04), radius: 2, x: 0, y: 1)
    static let medium = Shadow(color: .black.opacity(0.06), radius: 6, x: 0, y: 2)
    static let large = Shadow(color: .black.opacity(0.08), radius: 12, x: 0, y: 4)
    static let card = Shadow(color: .black.opacity(0.03), radius: 4, x: 0, y: 1)

    struct Shadow {
        let color: Color
        let radius: CGFloat
        let x: CGFloat
        let y: CGFloat
    }
}

// MARK: - Gradients (minimal — kept for backward compatibility)
struct AppGradients {
    static let primary = LinearGradient(
        colors: [BrandColors.primary, BrandColors.primaryDark],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )

    static let card = LinearGradient(
        colors: [BrandColors.cardBackground, BrandColors.cardBackground],
        startPoint: .top,
        endPoint: .bottom
    )

    static let background = LinearGradient(
        colors: [BrandColors.background, BrandColors.background],
        startPoint: .top,
        endPoint: .bottom
    )

    static let subtle = LinearGradient(
        colors: [
            Color(.tertiarySystemFill),
            Color(.quaternarySystemFill)
        ],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
}

// MARK: - View Modifiers
struct BrandedCardModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background(BrandColors.cardBackground)
            .cornerRadius(AppCornerRadius.card)
    }
}

struct BrandedButtonModifier: ViewModifier {
    var isPrimary: Bool = true
    var isDisabled: Bool = false

    func body(content: Content) -> some View {
        content
            .font(AppTypography.labelLarge)
            .foregroundColor(isPrimary ? .white : BrandColors.primary)
            .frame(height: 50)
            .frame(maxWidth: .infinity)
            .background(
                Group {
                    if isDisabled {
                        Color.gray.opacity(0.2)
                    } else if isPrimary {
                        BrandColors.primary
                    } else {
                        Color.clear
                    }
                }
            )
            .cornerRadius(AppCornerRadius.button)
            .overlay(
                RoundedRectangle(cornerRadius: AppCornerRadius.button)
                    .stroke(isPrimary ? Color.clear : BrandColors.primary.opacity(0.3), lineWidth: 1.5)
            )
    }
}

extension View {
    func brandedCard() -> some View {
        modifier(BrandedCardModifier())
    }

    func brandedButton(isPrimary: Bool = true, isDisabled: Bool = false) -> some View {
        modifier(BrandedButtonModifier(isPrimary: isPrimary, isDisabled: isDisabled))
    }
}

// MARK: - Reusable Elements

struct AppleBackgroundView: View {
    var body: some View {
        Color(.systemBackground)
            .ignoresSafeArea()
    }
}

struct GlassCardModifier: ViewModifier {
    var cornerRadius: CGFloat = AppCornerRadius.xlarge
    var shadowOpacity: Double = 0.15

    func body(content: Content) -> some View {
        content
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(Color(.secondarySystemGroupedBackground))
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(Color(.separator).opacity(0.3), lineWidth: 0.5)
            )
    }
}

extension View {
    func glassCard(cornerRadius: CGFloat = AppCornerRadius.xlarge, shadowOpacity: Double = 0.12) -> some View {
        modifier(GlassCardModifier(cornerRadius: cornerRadius, shadowOpacity: shadowOpacity))
    }
}

// MARK: - Hairline Divider

struct HairlineDivider: View {
    var body: some View {
        Rectangle()
            .fill(Color(.separator))
            .frame(height: 1 / UIScreen.main.scale)
    }
}
