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
        .accentColor(BrandColors.primary)
        .onAppear {
            // Customize tab bar appearance - Apple style
            let appearance = UITabBarAppearance()
            appearance.configureWithOpaqueBackground()
            appearance.backgroundColor = UIColor.systemBackground
            
            // Add subtle separator
            appearance.shadowColor = UIColor.separator.withAlphaComponent(0.3)
            
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
            if #available(iOS 15.0, *) {
                UITabBar.appearance().scrollEdgeAppearance = appearance
            }
        }
    }
}

#Preview {
    MainTabView()
}

