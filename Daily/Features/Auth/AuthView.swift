//
//  AuthView.swift
//  Daily
//
//  Created by Muhammadjon on 11/4/25.
//

import SwiftUI
import UIKit
import AuthenticationServices

struct AuthView: View {
    @ObservedObject private var auth = AuthService.shared
    @State private var isAppleLoading: Bool = false
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

    private func handleAppleSignIn(_ result: Result<ASAuthorization, Error>) async {
        errorMessage = nil
        isAppleLoading = true
        defer { isAppleLoading = false }

        switch result {
        case .success(let authorization):
            guard let appleIDCredential = authorization.credential as? ASAuthorizationAppleIDCredential,
                  let identityToken = appleIDCredential.identityToken else {
                errorMessage = "Failed to get Apple token"
                return
            }

            guard let tokenString = String(data: identityToken, encoding: .utf8) else {
                errorMessage = "Failed to convert Apple token to string"
                return
            }

            do {
                try await auth.authenticateWithApple(identityToken: tokenString)
            } catch {
                print("Apple sign-in error: \(error)")
                if let nsError = error as NSError? {
                    print("Error domain: \(nsError.domain), code: \(nsError.code)")
                    print("Error userInfo: \(nsError.userInfo)")
                }
                errorMessage = "Apple sign-in failed: \(error.localizedDescription)"
            }

        case .failure(let error):
            if let authError = error as? ASAuthorizationError, authError.code != .canceled {
                errorMessage = "Apple sign-in failed: \(error.localizedDescription)"
            }
        }
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
                .font(.system(size: 42, weight: .bold, design: .serif))
                .foregroundColor(BrandColors.textPrimary)

            Text("Your AI-curated news briefing")
                .font(AppTypography.subheadline)
                .foregroundColor(BrandColors.textSecondary)
        }
        .frame(maxWidth: .infinity)
    }

    var signInSection: some View {
        VStack(spacing: AppSpacing.md) {
            SignInWithAppleButton(
                onRequest: { request in
                    request.requestedScopes = [.fullName, .email]
                },
                onCompletion: { result in
                    Task {
                        await handleAppleSignIn(result)
                    }
                }
            )
            .signInWithAppleButtonStyle(.black)
            .frame(height: 52)
            .cornerRadius(AppCornerRadius.button)
            .disabled(isAppleLoading || isGoogleLoading)
            .overlay {
                if isAppleLoading {
                    ProgressView()
                        .progressViewStyle(CircularProgressViewStyle(tint: .white))
                }
            }

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
                            .font(.system(size: 18, weight: .medium))
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
            .disabled(isGoogleLoading || isAppleLoading)
            .opacity(isGoogleLoading || isAppleLoading ? 0.6 : 1)

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
