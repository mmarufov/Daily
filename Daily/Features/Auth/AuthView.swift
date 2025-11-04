//
//  AuthView.swift
//  Daily
//
//  Created by Assistant on 11/4/25.
//

import SwiftUI

struct AuthView: View {
    @ObservedObject private var auth = AuthService.shared
    @State private var googleIdToken: String = ""
    @State private var appleIdentityToken: String = ""
    @State private var isLoading: Bool = false
    @State private var errorMessage: String?

    var body: some View {
        VStack(spacing: 16) {
            Text("Sign in to continue")
                .font(.title2)

            GroupBox("Google ID Token (for now)") {
                VStack(alignment: .leading, spacing: 8) {
                    TextField("Paste Google ID token", text: $googleIdToken)
                        .textFieldStyle(.roundedBorder)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button(action: { Task { await signInWithGoogle() } }) {
                        HStack { if isLoading { ProgressView() } ; Text("Continue with Google") }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isLoading || googleIdToken.isEmpty)
                }
            }

            GroupBox("Apple Identity Token (for now)") {
                VStack(alignment: .leading, spacing: 8) {
                    TextField("Paste Apple identity token", text: $appleIdentityToken)
                        .textFieldStyle(.roundedBorder)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button(action: { Task { await signInWithApple() } }) {
                        HStack { if isLoading { ProgressView() } ; Text("Continue with Apple") }
                    }
                    .buttonStyle(.bordered)
                    .disabled(isLoading || appleIdentityToken.isEmpty)
                }
            }

            if let errorMessage {
                Text(errorMessage)
                    .foregroundColor(.red)
                    .font(.footnote)
            }
        }
        .padding()
    }

    private func signInWithGoogle() async {
        errorMessage = nil
        isLoading = true
        defer { isLoading = false }
        do {
            try await auth.authenticateWithGoogle(idToken: googleIdToken)
        } catch {
            errorMessage = "Google sign-in failed"
        }
    }

    private func signInWithApple() async {
        errorMessage = nil
        isLoading = true
        defer { isLoading = false }
        do {
            try await auth.authenticateWithApple(identityToken: appleIdentityToken)
        } catch {
            errorMessage = "Apple sign-in failed"
        }
    }
}

#Preview {
    AuthView()
}


