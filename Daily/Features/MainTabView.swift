//
//  MainTabView.swift
//  Daily
//
//  Created by Muhammadjon on 11/4/25.
//

import SwiftUI

struct MainTabView: View {
    @State private var selectedTab: AppTab = .news
    @State private var showOnboarding = false
    @StateObject private var chatViewModel = ChatViewModel()
    @StateObject private var newsViewModel = NewsViewModel()

    enum AppTab: Hashable {
        case news, saved, chat, search
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            Tab("News", systemImage: "newspaper", value: .news) {
                NewsView(viewModel: newsViewModel)
            }

            Tab("Saved", systemImage: "bookmark", value: .saved) {
                BookmarksView()
            }

            Tab("Chat", systemImage: "bubble.left.and.bubble.right", value: .chat) {
                ChatView(viewModel: chatViewModel, selectedTab: $selectedTab)
            }

            Tab("Search", systemImage: "magnifyingglass", value: .search) {
                SearchView(newsViewModel: newsViewModel)
            }
        }
        .tint(BrandColors.primary)
        .tabBarMinimizeBehavior(.onScrollDown)
        .onChange(of: selectedTab) { _, _ in
            HapticService.selection()
        }
        .task {
            await checkOnboarding()
        }
        .fullScreenCover(isPresented: $showOnboarding) {
            OnboardingChatView {
                showOnboarding = false
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .discussArticle)) { notification in
            if let article = notification.object as? NewsArticle {
                chatViewModel.startArticleDiscussion(article)
                withAnimation {
                    selectedTab = .chat
                }
            }
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

extension Notification.Name {
    static let discussArticle = Notification.Name("discussArticle")
}

#Preview {
    MainTabView()
}
