//
//  MainTabView.swift
//  Daily
//
//  Created by Muhammadjon on 11/4/25.
//

import SwiftUI
import UIKit

struct MainTabView: View {
    @State private var selectedTab = 0
    @State private var showOnboarding = false

    var body: some View {
        TabView(selection: $selectedTab) {
            NewsView()
                .tabItem {
                    Label("News", systemImage: selectedTab == 0 ? "newspaper.fill" : "newspaper")
                }
                .tag(0)

            ChatView()
                .tabItem {
                    Label("Chat", systemImage: selectedTab == 1 ? "bubble.left.and.bubble.right.fill" : "bubble.left.and.bubble.right")
                }
                .tag(1)
        }
        .tint(BrandColors.primary)
        .task {
            await checkOnboarding()
        }
        .fullScreenCover(isPresented: $showOnboarding) {
            OnboardingChatView {
                showOnboarding = false
            }
        }
        .onAppear {
            let appearance = UITabBarAppearance()
            appearance.configureWithDefaultBackground()
            appearance.backgroundEffect = UIBlurEffect(style: .systemChromeMaterial)
            appearance.backgroundColor = UIColor.clear
            appearance.shadowImage = UIImage()
            appearance.shadowColor = UIColor.clear

            appearance.stackedLayoutAppearance.selected.iconColor = UIColor(BrandColors.primary)
            appearance.stackedLayoutAppearance.selected.titleTextAttributes = [
                .foregroundColor: UIColor(BrandColors.primary),
                .font: UIFont.systemFont(ofSize: 11, weight: .semibold)
            ]

            appearance.stackedLayoutAppearance.normal.iconColor = UIColor(BrandColors.textSecondary)
            appearance.stackedLayoutAppearance.normal.titleTextAttributes = [
                .foregroundColor: UIColor(BrandColors.textSecondary),
                .font: UIFont.systemFont(ofSize: 11, weight: .regular)
            ]

            UITabBar.appearance().standardAppearance = appearance
            UITabBar.appearance().scrollEdgeAppearance = appearance
            UITabBar.appearance().isTranslucent = true
            UITabBar.appearance().backgroundColor = UIColor.clear
        }
    }

    private func checkOnboarding() async {
        guard let token = AuthService.shared.getAccessToken() else {
            return
        }

        do {
            let prefs = try await BackendService.shared.fetchUserPreferences(accessToken: token)
            if !prefs.completed {
                showOnboarding = true
            } else {
                NotificationCenter.default.post(name: .onboardingCompleted, object: nil)
            }
        } catch {
            showOnboarding = true
        }
    }
}

#Preview {
    MainTabView()
}
