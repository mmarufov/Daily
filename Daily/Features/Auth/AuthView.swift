//
//  AuthView.swift
//  Daily
//
//  Created by Assistant on 11/4/25.
//

import SwiftUI
import AuthenticationServices

struct AuthView: View {
    @ObservedObject private var auth = AuthService.shared
    @State private var isAppleLoading: Bool = false
    @State private var isGoogleLoading: Bool = false
    @State private var errorMessage: String?

    var body: some View {
        VStack(spacing: 24) {
            Text("Sign in to continue")
                .font(.title2)
                .padding(.top, 40)

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
            .cornerRadius(8)

            // Google Sign In Button
            Button(action: { Task { await signInWithGoogle() } }) {
                HStack {
                    if isGoogleLoading {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: .white))
                    } else {
                        Image(systemName: "globe")
                    }
                    Text("Continue with Google")
                        .fontWeight(.semibold)
                }
                .frame(maxWidth: .infinity)
                .frame(height: 50)
                .foregroundColor(.white)
                .background(Color(red: 0.26, green: 0.52, blue: 0.96))
                .cornerRadius(8)
            }
            .disabled(isGoogleLoading || isAppleLoading)

            if let errorMessage {
                Text(errorMessage)
                    .foregroundColor(.red)
                    .font(.footnote)
                    .padding(.top, 8)
            }
        }
        .padding(.horizontal, 32)
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


