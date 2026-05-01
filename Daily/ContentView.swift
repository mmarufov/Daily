//
//  ContentView.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI

struct ContentView: View {
    @ObservedObject private var auth = AuthService.shared

    var body: some View {
        Group {
            switch auth.state {
            case .unknown:
                // Brief splash while we verify the stored token. Avoids the
                // sign-in flicker that happens when an authenticated user
                // cold-launches the app and /me hasn't responded yet.
                SplashView()
                    .transition(.opacity)
            case .authenticated:
                MainTabView()
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            case .unauthenticated:
                AuthView()
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.28), value: auth.state)
    }
}

private struct SplashView: View {
    var body: some View {
        ZStack {
            BrandColors.background
                .ignoresSafeArea()
            VStack(spacing: 16) {
                Image(systemName: "newspaper.fill")
                    .font(.system(size: 44, weight: .semibold))
                    .foregroundStyle(BrandColors.primary)
                ProgressView()
                    .controlSize(.small)
            }
        }
        .accessibilityLabel("Loading")
    }
}

#Preview {
    ContentView()
}
