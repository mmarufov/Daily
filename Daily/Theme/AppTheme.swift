//
//  AppTheme.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI

// MARK: - Brand Colors (Editorial palette)
struct BrandColors {
    // Primary brand color - Editorial red/vermilion
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
    static let cardBackground = Color(.secondarySystemGroupedBackground)
    static let tertiaryBackground = Color(.tertiarySystemBackground)

    // Text colors - System labels
    static let textPrimary = Color(.label)
    static let textSecondary = Color(.secondaryLabel)
    static let textTertiary = Color(.tertiaryLabel)
    static let textQuaternary = Color(.quaternaryLabel)

    // Semantic accent roles — red discipline
    // Primary actions + urgent states only (send button, BREAKING badge, CTAs)
    static let actionPrimary = primary
    // Editorial metadata — neutral tones (source labels, section headers)
    static let sourceText = Color(.secondaryLabel)
    static let sectionHeader = Color(.secondaryLabel)
}

// MARK: - Typography (Dynamic Type — all sizes scale with accessibility settings)
struct AppTypography {
    // Titles — map to system text styles for automatic scaling
    static let largeTitle = Font.system(.largeTitle, design: .default, weight: .bold)
    static let title1 = Font.system(.title, design: .default, weight: .bold)
    static let title2 = Font.system(.title2, design: .default, weight: .bold)
    static let title3 = Font.system(.title3, design: .default, weight: .semibold)

    // Headline fonts
    static let headline = Font.system(.headline, design: .default, weight: .semibold)
    static let headlineMedium = Font.system(.subheadline, design: .default, weight: .semibold)
    static let headlineSmall = Font.system(.subheadline, design: .default, weight: .semibold)

    // Body fonts
    static let body = Font.system(.body, design: .default, weight: .regular)
    static let bodyMedium = Font.system(.callout, design: .default, weight: .regular)
    static let bodySmall = Font.system(.footnote, design: .default, weight: .regular)

    // Callout
    static let callout = Font.system(.callout, design: .default, weight: .regular)

    // Subheadline
    static let subheadline = Font.system(.subheadline, design: .default, weight: .regular)

    // Footnote
    static let footnote = Font.system(.footnote, design: .default, weight: .regular)

    // Caption
    static let caption1 = Font.system(.caption, design: .default, weight: .regular)
    static let caption2 = Font.system(.caption2, design: .default, weight: .regular)

    // Label fonts
    static let labelLarge = Font.system(.body, design: .default, weight: .medium)
    static let labelMedium = Font.system(.callout, design: .default, weight: .medium)
    static let labelSmall = Font.system(.footnote, design: .default, weight: .medium)

    // Editorial typography — serif for headlines and reading
    static let brandSubtitle = Font.system(.title2, design: .serif, weight: .bold)
    static let feedHeroTitle = Font.system(.title2, design: .serif, weight: .bold)
    static let heroHeadline = Font.system(.largeTitle, design: .serif, weight: .bold)
    static let feedCardTitle = Font.system(.subheadline, design: .serif, weight: .semibold)
    static let sectionHeroTitle = Font.system(.title3, design: .serif, weight: .bold)
    static let sectionTitle = Font.system(.footnote, design: .default, weight: .bold)
    static let sourceLabel = Font.system(.caption, design: .default, weight: .bold)
    static let dateLabel = Font.system(.caption, design: .default, weight: .regular)

    // Article-specific typography (New York-style serif for long-form reading)
    static let articleTitle = Font.system(.title, design: .serif, weight: .bold)
    static let articleBody = Font.system(.body, design: .serif, weight: .regular)

    // Brand
    static let brandTitle = Font.system(.largeTitle, design: .serif, weight: .bold)

    // Icons — use fixed sizes (icons don't scale with Dynamic Type)
    static let iconLarge = Font.system(size: 36, weight: .light)
    static let iconMedium = Font.system(size: 28, weight: .light)
    static let iconXL = Font.system(size: 40, weight: .light)
    static let iconHeroXL = Font.system(size: 48, weight: .light)
    static let emptyStateIcon = Font.system(size: 36, weight: .ultraLight)

    // UI Chrome — small fixed-size elements that scale via ScaledMetric where used
    static let badgeLabel = Font.system(.caption2, design: .default, weight: .bold)
    static let chipIcon = Font.system(.caption2, design: .default, weight: .medium)
    static let chipLabel = Font.system(.footnote, design: .default, weight: .semibold)
    static let metaLabel = Font.system(.caption2, design: .default, weight: .semibold)
    static let metaLabelRegular = Font.system(.caption2, design: .default, weight: .regular)
    static let microLabel = Font.system(.caption2, design: .default, weight: .semibold)
    static let navIcon = Font.system(.footnote, design: .default, weight: .semibold)
    static let toolbarIcon = Font.system(.footnote, design: .default, weight: .medium)
    static let iconButton = Font.system(.callout, design: .default, weight: .medium)
    static let closeIcon = Font.system(.title3, design: .default, weight: .regular)
    static let profileIcon = Font.system(.title2, design: .default, weight: .regular)
    static let actionLabel = Font.system(.subheadline, design: .default, weight: .semibold)
    static let actionIcon = Font.system(.subheadline, design: .default, weight: .medium)
    static let articleAuthor = Font.system(.footnote, design: .default, weight: .medium)
    static let articleLeadIn = Font.system(.body, design: .serif, weight: .medium)

    // Legacy support — mapped to Dynamic Type equivalents
    static let displayLarge = Font.system(.largeTitle, design: .default, weight: .bold)
    static let displayMedium = Font.system(.title, design: .default, weight: .bold)
    static let displaySmall = Font.system(.title2, design: .default, weight: .bold)
    static let headlineLarge = Font.system(.title3, design: .default, weight: .semibold)
    static let bodyLarge = Font.system(.body, design: .default, weight: .regular)
}

// MARK: - Spacing
struct AppSpacing {
    static let xs: CGFloat = 4
    static let sm: CGFloat = 8
    static let smPlus: CGFloat = 10
    static let smLg: CGFloat = 12
    static let md: CGFloat = 16
    static let lg: CGFloat = 24
    static let xl: CGFloat = 32
    static let xxl: CGFloat = 48
}

// MARK: - Corner Radius
struct AppCornerRadius {
    static let small: CGFloat = 8
    static let image: CGFloat = 10
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

    func body(content: Content) -> some View {
        content
            .glassEffect(.regular, in: RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
    }
}

extension View {
    func glassCard(cornerRadius: CGFloat = AppCornerRadius.xlarge) -> some View {
        modifier(GlassCardModifier(cornerRadius: cornerRadius))
    }
}

// MARK: - Chat Background

struct ChatBackgroundView: View {
    var body: some View {
        ZStack {
            Color(.systemBackground).ignoresSafeArea()
            LinearGradient(
                colors: [
                    BrandColors.primary.opacity(0.03),
                    Color(.systemBackground),
                    BrandColors.primary.opacity(0.02)
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )
            .ignoresSafeArea()
        }
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
