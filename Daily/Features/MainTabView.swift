//
//  MainTabView.swift
//  Daily
//
//  Created by Muhammadjon on 11/4/25.
//

import SwiftUI

struct MainTabView: View {
    @State private var selectedTab = 0
    
    var body: some View {
        TabView(selection: $selectedTab) {
            NewsView()
                .tabItem {
                    Label("News", systemImage: "newspaper")
                }
                .tag(0)
            
            ChatView()
                .tabItem {
                    Label("Chat", systemImage: "bubble.left.and.bubble.right")
                }
                .tag(1)
        }
    }
}

#Preview {
    MainTabView()
}

