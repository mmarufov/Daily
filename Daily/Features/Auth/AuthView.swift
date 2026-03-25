//
//  AuthView.swift
//  Daily
//
//  Created by Muhammadjon on 11/4/25.
//

import SwiftUI
import UIKit

struct AuthView: View {
    @ObservedObject private var auth = AuthService.shared
    @State private var isGoogleLoading: Bool = false
    @State private var errorMessage: String?

    var body: some View {
        VStack(spacing: AppSpacing.xl) {
            Spacer(minLength: 20)

            heroSection

            signInSection

            footerSection
        }
        .padding(.horizontal, AppSpacing.lg)
        .padding(.bottom, AppSpacing.xl)
        .padding(.top, AppSpacing.xl)
        .background(Color(.systemBackground))
    }

    private func signInWithGoogle() async {
        errorMessage = nil
        isGoogleLoading = true
        defer { isGoogleLoading = false }

        do {
            let idToken = try await GoogleSignInHelper.signIn()
            try await auth.authenticateWithGoogle(idToken: idToken)
        } catch {
            print("Google sign-in error: \(error)")
            errorMessage = "Google sign-in failed: \(error.localizedDescription)"
        }
    }
}

// MARK: - Subviews

private extension AuthView {
    var heroSection: some View {
        VStack(spacing: AppSpacing.md) {
            Text("Daily")
                .font(AppTypography.brandTitle)
                .foregroundColor(BrandColors.textPrimary)

            Text("Your AI-curated news briefing")
                .font(AppTypography.subheadline)
                .foregroundColor(BrandColors.textSecondary)
        }
        .frame(maxWidth: .infinity)
    }

    var signInSection: some View {
        VStack(spacing: AppSpacing.md) {
            Button(action: {
                HapticService.impact(.light)
                Task { await signInWithGoogle() }
            }) {
                HStack(spacing: AppSpacing.sm) {
                    if isGoogleLoading {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: BrandColors.textPrimary))
                    } else {
                        Image(systemName: "globe")
                            .font(AppTypography.iconButton)
                    }
                    Text("Continue with Google")
                        .font(AppTypography.labelLarge)
                        .fontWeight(.semibold)
                }
                .foregroundColor(BrandColors.textPrimary)
                .frame(maxWidth: .infinity)
                .frame(height: 52)
                .background(Color(.systemBackground))
                .cornerRadius(AppCornerRadius.button)
                .overlay(
                    RoundedRectangle(cornerRadius: AppCornerRadius.button)
                        .stroke(Color(.separator), lineWidth: 1)
                )
            }
            .disabled(isGoogleLoading)
            .opacity(isGoogleLoading ? 0.6 : 1)
            .accessibilityLabel("Sign in with Google")

            if let errorMessage {
                Text(errorMessage)
                    .font(AppTypography.bodySmall)
                    .foregroundColor(BrandColors.error)
                    .multilineTextAlignment(.center)
                    .padding(.top, AppSpacing.sm)
            }
        }
        .padding(.horizontal, AppSpacing.sm)
    }

    var footerSection: some View {
        VStack(spacing: AppSpacing.xs) {
            Text("By continuing you agree to the Terms of Service and Privacy Policy.")
                .font(AppTypography.caption1)
                .foregroundColor(BrandColors.textTertiary)
                .multilineTextAlignment(.center)

            Text("Your data stays private and secure.")
                .font(AppTypography.caption2)
                .foregroundColor(BrandColors.textQuaternary)
        }
        .padding(.horizontal, AppSpacing.xl)
    }
}

#Preview {
    AuthView()
}
