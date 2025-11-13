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
            // Background gradient
            AppGradients.background
                .ignoresSafeArea()
            
            VStack(spacing: 0) {
                Spacer()
                
                // Brand Logo/Icon Section - Apple style
                VStack(spacing: AppSpacing.xl) {
                    ZStack {
                        Circle()
                            .fill(BrandColors.primary)
                            .frame(width: 100, height: 100)
                            .shadow(color: BrandColors.primary.opacity(0.2), radius: 16, x: 0, y: 6)
                        
                        Image(systemName: "newspaper.fill")
                            .font(.system(size: 44, weight: .medium))
                            .foregroundColor(.white)
                    }
                    
                    VStack(spacing: AppSpacing.xs) {
                        Text("Daily")
                            .font(AppTypography.largeTitle)
                            .foregroundColor(BrandColors.textPrimary)
                        
                        Text("Your personalized news companion")
                            .font(AppTypography.subheadline)
                            .foregroundColor(BrandColors.textSecondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, AppSpacing.xl)
                    }
                }
                .padding(.bottom, AppSpacing.xxl)
                
                // Sign In Buttons - Apple style
                VStack(spacing: AppSpacing.md) {
                    // Apple Sign In Button
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
                    .frame(height: 50)
                    .cornerRadius(AppCornerRadius.button)
                    .shadow(
                        color: AppShadows.small.color,
                        radius: AppShadows.small.radius,
                        x: AppShadows.small.x,
                        y: AppShadows.small.y
                    )

                    // Google Sign In Button - Apple style
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
                                    .font(.system(size: 16, weight: .medium))
                            }
                            Text("Continue with Google")
                                .font(AppTypography.labelLarge)
                                .fontWeight(.medium)
                        }
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity)
                        .frame(height: 50)
                        .background(
                            LinearGradient(
                                colors: [Color(red: 0.26, green: 0.52, blue: 0.96), Color(red: 0.20, green: 0.45, blue: 0.90)],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .cornerRadius(AppCornerRadius.button)
                        .shadow(
                            color: AppShadows.small.color,
                            radius: AppShadows.small.radius,
                            x: AppShadows.small.x,
                            y: AppShadows.small.y
                        )
                    }
                    .disabled(isGoogleLoading || isAppleLoading)
                    .opacity(isGoogleLoading || isAppleLoading ? 0.6 : 1.0)

                    if let errorMessage {
                        HStack(spacing: AppSpacing.sm) {
                            Image(systemName: "exclamationmark.circle.fill")
                                .foregroundColor(BrandColors.error)
                            Text(errorMessage)
                                .font(AppTypography.bodySmall)
                                .foregroundColor(BrandColors.error)
                        }
                        .padding(AppSpacing.md)
                        .background(BrandColors.error.opacity(0.1))
                        .cornerRadius(AppCornerRadius.small)
                        .padding(.top, AppSpacing.sm)
                    }
                }
                .padding(.horizontal, AppSpacing.xl)
                
                Spacer()
                
                // Footer - Apple style
                Text("By continuing, you agree to our Terms of Service")
                    .font(AppTypography.caption1)
                    .foregroundColor(BrandColors.textTertiary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, AppSpacing.xl)
                    .padding(.bottom, AppSpacing.xl)
            }
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

#Preview {
    AuthView()
}


