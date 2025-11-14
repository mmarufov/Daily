//
//  AppTheme.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI

// MARK: - Brand Colors (Apple-inspired)
struct BrandColors {
    // Primary brand colors - Apple blue
    static let primary = Color(red: 0.0, green: 0.48, blue: 1.0) // iOS Blue
    static let primaryDark = Color(red: 0.0, green: 0.40, blue: 0.85)
    static let primaryLight = Color(red: 0.20, green: 0.60, blue: 1.0)
    
    // Accent colors - Subtle and refined
    static let accent = Color(red: 1.0, green: 0.58, blue: 0.0) // iOS Orange
    static let accentLight = Color(red: 1.0, green: 0.65, blue: 0.20)
    
    // Gradient colors - Subtle gradients
    static let gradientStart = Color(red: 0.0, green: 0.48, blue: 1.0)
    static let gradientEnd = Color(red: 0.35, green: 0.35, blue: 0.85)
    
    // Semantic colors - System colors
    static let success = Color(red: 0.20, green: 0.78, blue: 0.35) // iOS Green
    static let warning = Color(red: 1.0, green: 0.58, blue: 0.0) // iOS Orange
    static let error = Color(red: 1.0, green: 0.23, blue: 0.19) // iOS Red
    
    // Background colors - System backgrounds
    static let background = Color(.systemGroupedBackground)
    static let secondaryBackground = Color(.secondarySystemGroupedBackground)
    static let cardBackground = Color(.systemBackground)
    static let tertiaryBackground = Color(.tertiarySystemBackground)
    
    // Text colors - System labels
    static let textPrimary = Color(.label)
    static let textSecondary = Color(.secondaryLabel)
    static let textTertiary = Color(.tertiaryLabel)
    static let textQuaternary = Color(.quaternaryLabel)
}

// MARK: - Typography (Apple SF Pro style)
struct AppTypography {
    // Large Title - For main headings
    static let largeTitle = Font.system(size: 34, weight: .bold, design: .default)
    static let title1 = Font.system(size: 28, weight: .bold, design: .default)
    static let title2 = Font.system(size: 22, weight: .bold, design: .default)
    static let title3 = Font.system(size: 20, weight: .semibold, design: .default)
    
    // Headline fonts - For section headers
    static let headline = Font.system(size: 17, weight: .semibold, design: .default)
    static let headlineMedium = Font.system(size: 16, weight: .semibold, design: .default)
    static let headlineSmall = Font.system(size: 15, weight: .semibold, design: .default)
    
    // Body fonts - For main content
    static let body = Font.system(size: 17, weight: .regular, design: .default)
    static let bodyMedium = Font.system(size: 15, weight: .regular, design: .default)
    static let bodySmall = Font.system(size: 13, weight: .regular, design: .default)
    
    // Callout - For emphasized text
    static let callout = Font.system(size: 16, weight: .regular, design: .default)
    
    // Subheadline - For secondary text
    static let subheadline = Font.system(size: 15, weight: .regular, design: .default)
    
    // Footnote - For small text
    static let footnote = Font.system(size: 13, weight: .regular, design: .default)
    
    // Caption - For smallest text
    static let caption1 = Font.system(size: 12, weight: .regular, design: .default)
    static let caption2 = Font.system(size: 11, weight: .regular, design: .default)
    
    // Label fonts - For buttons and labels
    static let labelLarge = Font.system(size: 17, weight: .medium, design: .default)
    static let labelMedium = Font.system(size: 15, weight: .medium, design: .default)
    static let labelSmall = Font.system(size: 13, weight: .medium, design: .default)
    
    // Article-specific typography (New York-style serif for long-form reading)
    static let articleTitle = Font.system(size: 26, weight: .bold, design: .serif)
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

// MARK: - Corner Radius (Apple style)
struct AppCornerRadius {
    static let small: CGFloat = 8
    static let medium: CGFloat = 12
    static let large: CGFloat = 16
    static let xlarge: CGFloat = 20
    static let round: CGFloat = 999
    
    // Apple-specific corner radius
    static let card: CGFloat = 16
    static let button: CGFloat = 12
    static let sheet: CGFloat = 20
}

// MARK: - Shadows (Apple style - subtle and refined)
struct AppShadows {
    static let small = Shadow(color: .black.opacity(0.06), radius: 3, x: 0, y: 1)
    static let medium = Shadow(color: .black.opacity(0.08), radius: 8, x: 0, y: 2)
    static let large = Shadow(color: .black.opacity(0.12), radius: 16, x: 0, y: 4)
    static let card = Shadow(color: .black.opacity(0.05), radius: 10, x: 0, y: 2)
    
    struct Shadow {
        let color: Color
        let radius: CGFloat
        let x: CGFloat
        let y: CGFloat
    }
}

// MARK: - Gradients (Apple style - subtle)
struct AppGradients {
    static let primary = LinearGradient(
        colors: [BrandColors.primary, BrandColors.primaryDark],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
    
    static let card = LinearGradient(
        colors: [
            BrandColors.cardBackground,
            BrandColors.cardBackground.opacity(0.95)
        ],
        startPoint: .top,
        endPoint: .bottom
    )
    
    static let background = LinearGradient(
        colors: [
            BrandColors.background,
            BrandColors.secondaryBackground
        ],
        startPoint: .top,
        endPoint: .bottom
    )
    
    static let subtle = LinearGradient(
        colors: [
            BrandColors.primary.opacity(0.08),
            BrandColors.primary.opacity(0.04)
        ],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
}

// MARK: - View Modifiers (Apple style)
struct BrandedCardModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background(BrandColors.cardBackground)
            .cornerRadius(AppCornerRadius.card)
            .shadow(
                color: AppShadows.card.color,
                radius: AppShadows.card.radius,
                x: AppShadows.card.x,
                y: AppShadows.card.y
            )
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

// Apple-style blur material
struct AppleBlurModifier: ViewModifier {
    var style: UIBlurEffect.Style = .systemMaterial
    
    func body(content: Content) -> some View {
        content
            .background(.ultraThinMaterial)
    }
}

extension View {
    func brandedCard() -> some View {
        modifier(BrandedCardModifier())
    }
    
    func brandedButton(isPrimary: Bool = true, isDisabled: Bool = false) -> some View {
        modifier(BrandedButtonModifier(isPrimary: isPrimary, isDisabled: isDisabled))
    }
    
    func appleBlur(style: UIBlurEffect.Style = .systemMaterial) -> some View {
        modifier(AppleBlurModifier(style: style))
    }
}

