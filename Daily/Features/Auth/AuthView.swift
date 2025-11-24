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
        ZStack {
            AppleBackgroundView()
            
            VStack(spacing: AppSpacing.xl) {
                Spacer(minLength: 20)
                
                heroSection
                
                signInSection
                
                footerSection
            }
            .padding(.horizontal, AppSpacing.lg)
            .padding(.bottom, AppSpacing.xl)
            .padding(.top, AppSpacing.xl)
        }
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
            
            // Convert JWT token Data to string
            // JWT tokens are ASCII strings, so UTF-8 encoding should work
            guard let tokenString = String(data: identityToken, encoding: .utf8) else {
                errorMessage = "Failed to convert Apple token to string"
                return
            }
            
            do {
                try await auth.authenticateWithApple(identityToken: tokenString)
            } catch {
                // Log error for debugging
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
            // User canceled - don't show error
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
            ZStack {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [BrandColors.primary, BrandColors.primaryDark],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 120, height: 120)
                    .shadow(color: BrandColors.primary.opacity(0.25), radius: 30, x: 0, y: 20)
                
                Image(systemName: "newspaper.columns")
                    .font(.system(size: 46, weight: .medium))
                    .foregroundColor(.white)
            }
            
            Text("Daily")
                .font(AppTypography.largeTitle)
                .foregroundColor(BrandColors.textPrimary)
                .padding(.top, AppSpacing.sm)
            
            Text("Stay effortlessly informed with a personalized briefing inspired by Apple’s calm, elegant interfaces.")
                .font(AppTypography.subheadline)
                .foregroundColor(BrandColors.textSecondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, AppSpacing.xl)
        }
        .frame(maxWidth: .infinity)
    }
    
    var signInSection: some View {
        VStack(alignment: .leading, spacing: AppSpacing.lg) {
            VStack(alignment: .leading, spacing: AppSpacing.xs) {
                Text("Welcome back")
                    .font(AppTypography.title3)
                    .foregroundColor(BrandColors.textPrimary)
                Text("Choose a sign in method to continue")
                    .font(AppTypography.bodyMedium)
                    .foregroundColor(BrandColors.textSecondary)
            }
            
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
                .frame(height: 54)
                .cornerRadius(AppCornerRadius.button)
                .overlay(
                    RoundedRectangle(cornerRadius: AppCornerRadius.button)
                        .stroke(Color.white.opacity(0.2), lineWidth: 0.5)
                )
                .shadow(color: Color.black.opacity(0.08), radius: 14, x: 0, y: 8)
                .disabled(isAppleLoading || isGoogleLoading)
                .overlay {
                    if isAppleLoading {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: .white))
                    }
                }
                
                Button(action: {
                    let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                    impactFeedback.impactOccurred()
                    Task { await signInWithGoogle() }
                }) {
                    HStack(spacing: AppSpacing.sm) {
                        if isGoogleLoading {
                            ProgressView()
                                .progressViewStyle(CircularProgressViewStyle(tint: .white))
                        } else {
                            Image(systemName: "globe")
                                .font(.system(size: 18, weight: .medium))
                        }
                        Text("Continue with Google")
                            .font(AppTypography.labelLarge)
                    }
                    .foregroundColor(.white)
                    .frame(maxWidth: .infinity)
                    .frame(height: 54)
                    .background(
                        LinearGradient(
                            colors: [BrandColors.primaryLight, BrandColors.primaryDark],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .cornerRadius(AppCornerRadius.button)
                    .shadow(color: BrandColors.primary.opacity(0.2), radius: 12, x: 0, y: 8)
                }
                .disabled(isGoogleLoading || isAppleLoading)
                .opacity(isGoogleLoading || isAppleLoading ? 0.6 : 1)
            }
            
            if let errorMessage {
                HStack(spacing: AppSpacing.sm) {
                    Image(systemName: "exclamationmark.circle.fill")
                        .foregroundColor(BrandColors.error)
                    Text(errorMessage)
                        .font(AppTypography.bodySmall)
                        .foregroundColor(BrandColors.error)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(AppSpacing.md)
                .background(BrandColors.error.opacity(0.08))
                .cornerRadius(AppCornerRadius.medium)
            }
        }
        .padding(AppSpacing.lg)
        .glassCard()
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
                .foregroundColor(BrandColors.textSecondary)
        }
        .padding(.horizontal, AppSpacing.xl)
    }
}

#Preview {
    AuthView()
}


