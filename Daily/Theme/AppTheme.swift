//
//  AppTheme.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI

// MARK: - Brand Colors
struct BrandColors {
    // Primary brand colors
    static let primary = Color(red: 0.20, green: 0.40, blue: 0.95) // Vibrant blue
    static let primaryDark = Color(red: 0.15, green: 0.30, blue: 0.85)
    static let primaryLight = Color(red: 0.30, green: 0.50, blue: 1.0)
    
    // Accent colors
    static let accent = Color(red: 0.95, green: 0.40, blue: 0.20) // Vibrant orange
    static let accentLight = Color(red: 1.0, green: 0.50, blue: 0.30)
    
    // Gradient colors
    static let gradientStart = Color(red: 0.20, green: 0.40, blue: 0.95)
    static let gradientEnd = Color(red: 0.60, green: 0.30, blue: 0.90)
    
    // Semantic colors
    static let success = Color(red: 0.20, green: 0.75, blue: 0.40)
    static let warning = Color(red: 1.0, green: 0.65, blue: 0.0)
    static let error = Color(red: 0.95, green: 0.30, blue: 0.30)
    
    // Background colors
    static let background = Color(.systemBackground)
    static let secondaryBackground = Color(.secondarySystemBackground)
    static let cardBackground = Color(.systemBackground)
    
    // Text colors
    static let textPrimary = Color(.label)
    static let textSecondary = Color(.secondaryLabel)
    static let textTertiary = Color(.tertiaryLabel)
}

// MARK: - Typography
struct AppTypography {
    // Display fonts
    static let displayLarge = Font.system(size: 34, weight: .bold, design: .rounded)
    static let displayMedium = Font.system(size: 28, weight: .bold, design: .rounded)
    static let displaySmall = Font.system(size: 22, weight: .bold, design: .rounded)
    
    // Headline fonts
    static let headlineLarge = Font.system(size: 20, weight: .semibold, design: .default)
    static let headlineMedium = Font.system(size: 18, weight: .semibold, design: .default)
    static let headlineSmall = Font.system(size: 16, weight: .semibold, design: .default)
    
    // Body fonts
    static let bodyLarge = Font.system(size: 16, weight: .regular, design: .default)
    static let bodyMedium = Font.system(size: 14, weight: .regular, design: .default)
    static let bodySmall = Font.system(size: 12, weight: .regular, design: .default)
    
    // Label fonts
    static let labelLarge = Font.system(size: 14, weight: .medium, design: .default)
    static let labelMedium = Font.system(size: 12, weight: .medium, design: .default)
    static let labelSmall = Font.system(size: 10, weight: .medium, design: .default)
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
    static let xlarge: CGFloat = 24
    static let round: CGFloat = 999
}

// MARK: - Shadows
struct AppShadows {
    static let small = Shadow(color: .black.opacity(0.08), radius: 4, x: 0, y: 2)
    static let medium = Shadow(color: .black.opacity(0.12), radius: 8, x: 0, y: 4)
    static let large = Shadow(color: .black.opacity(0.16), radius: 16, x: 0, y: 8)
    
    struct Shadow {
        let color: Color
        let radius: CGFloat
        let x: CGFloat
        let y: CGFloat
    }
}

// MARK: - Gradients
struct AppGradients {
    static let primary = LinearGradient(
        colors: [BrandColors.gradientStart, BrandColors.gradientEnd],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
    
    static let card = LinearGradient(
        colors: [BrandColors.primary.opacity(0.1), BrandColors.accent.opacity(0.1)],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )
    
    static let background = LinearGradient(
        colors: [
            BrandColors.background,
            BrandColors.secondaryBackground.opacity(0.5)
        ],
        startPoint: .top,
        endPoint: .bottom
    )
}

// MARK: - View Modifiers
struct BrandedCardModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .background(BrandColors.cardBackground)
            .cornerRadius(AppCornerRadius.medium)
            .shadow(
                color: AppShadows.medium.color,
                radius: AppShadows.medium.radius,
                x: AppShadows.medium.x,
                y: AppShadows.medium.y
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
                        Color.gray.opacity(0.3)
                    } else if isPrimary {
                        AppGradients.primary
                    } else {
                        Color.clear
                    }
                }
            )
            .cornerRadius(AppCornerRadius.medium)
            .overlay(
                RoundedRectangle(cornerRadius: AppCornerRadius.medium)
                    .stroke(isPrimary ? Color.clear : BrandColors.primary, lineWidth: 2)
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

