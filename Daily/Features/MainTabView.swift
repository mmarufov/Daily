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
    @StateObject private var tuneViewModel = TuneViewModel()
    @StateObject private var newsViewModel = NewsViewModel()

    enum AppTab: Hashable {
        case news, saved, tune, search
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            Tab("News", systemImage: "newspaper", value: .news) {
                NewsView(viewModel: newsViewModel)
            }

            Tab("Saved", systemImage: "bookmark", value: .saved) {
                BookmarksView()
            }

            Tab("Tune", systemImage: "slider.horizontal.3", value: .tune) {
                TuneView(viewModel: tuneViewModel, selectedTab: $selectedTab)
            }

            Tab("Search", systemImage: "magnifyingglass", value: .search, role: .search) {
                SearchView(newsViewModel: newsViewModel)
            }
        }
        .tint(BrandColors.primary)
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
                Task {
                    await tuneViewModel.startArticleDiscussion(article)
                    withAnimation {
                        selectedTab = .tune
                    }
                }
            }
        }
    }

    private func checkOnboarding() async {
        guard let token = AuthService.shared.getAccessToken() else {
            return
        }

        // Only force onboarding when the server explicitly says preferences
        // aren't complete. Treating any error (network blip, 5xx) as
        // "not onboarded" can re-onboard a user who's already set up and
        // overwrite their existing preferences. Better: stay on the feed
        // and let the next attempt resolve.
        do {
            let prefs = try await BackendService.shared.fetchUserPreferences(accessToken: token)
            if !prefs.completed {
                showOnboarding = true
            }
        } catch {
            // Silent retry on next launch — do not flip into onboarding.
        }
    }
}

extension Notification.Name {
    static let discussArticle = Notification.Name("discussArticle")
}

#Preview {
    MainTabView()
}
