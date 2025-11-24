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
        ZStack {
            AppleBackgroundView()
            
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
            .accentColor(BrandColors.primary)
        }
        .task {
            await checkOnboarding()
        }
        .fullScreenCover(isPresented: $showOnboarding) {
            OnboardingChatView {
                showOnboarding = false
            }
        }
        .onAppear {
            // Customize tab bar appearance - Apple style
            let appearance = UITabBarAppearance()
            appearance.configureWithDefaultBackground()
            appearance.backgroundEffect = UIBlurEffect(style: .systemChromeMaterial)
            appearance.backgroundColor = UIColor.clear
            appearance.shadowImage = UIImage()
            appearance.shadowColor = UIColor.clear
            
            // Add subtle separator
            let separator = UIImage()
            appearance.shadowImage = separator
            
            // Selected item - Apple style
            appearance.stackedLayoutAppearance.selected.iconColor = UIColor(BrandColors.primary)
            appearance.stackedLayoutAppearance.selected.titleTextAttributes = [
                .foregroundColor: UIColor(BrandColors.primary),
                .font: UIFont.systemFont(ofSize: 11, weight: .semibold)
            ]
            
            // Normal item - Apple style
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
                // User already completed setup – trigger auto refresh of personalized news
                NotificationCenter.default.post(name: .onboardingCompleted, object: nil)
            }
        } catch {
            // If we can't load preferences, assume onboarding is needed
            showOnboarding = true
        }
    }
}

#Preview {
    MainTabView()
}

