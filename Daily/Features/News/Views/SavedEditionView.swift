import SwiftUI

/// Deliberately separate from the authenticated tabs and detail view: presenting
/// a secure local owner marker authorizes no server call or attributed event.
struct SavedEditionView: View {
    let userID: String
    @ObservedObject var auth: AuthService
    @State private var edition: CachedEdition?
    @State private var loading = true
    @State private var unavailable = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Text("Saved edition · read-only").font(.headline)
                    Text("Reconnect to verify your account and get current news.")
                        .font(.subheadline).foregroundStyle(.secondary)
                    if let edition {
                        Text((edition.delivery?.publishedAt ?? edition.receivedAt), style: .date)
                            .font(.caption)
                    }
                    Button("Reconnect") { auth.restoreSession() }
                    Button("Sign out", role: .destructive) { auth.signOut() }
                }
                if loading {
                    ProgressView("Loading saved edition")
                } else if let edition {
                    if edition.articles.isEmpty {
                        Text("This saved edition has no stories.")
                    }
                    ForEach(edition.articles) { article in
                        NavigationLink {
                            SavedArticleView(article: article.withoutFeedReceipt(), userID: userID)
                        } label: {
                            VStack(alignment: .leading, spacing: 8) {
                                Text(article.title).font(.headline)
                                if let source = article.source { Text(source).font(.caption).foregroundStyle(.secondary) }
                                if let summary = article.summary { Text(summary).font(.body) }
                            }.padding(.vertical, 6)
                        }
                    }
                } else {
                    Text(unavailable ? "Saved storage is unavailable. Unlock your device and reconnect to try again."
                        : "No saved edition is available on this device.")
                }
            }
            .navigationTitle("Daily")
        }
        .task(id: userID) {
            let result = await BackgroundNewsFetcher.shared.loadCachedEdition(forUserID: userID)
            guard !Task.isCancelled, auth.state == .savedAccount(userID: userID) else { return }
            if case .saved(let saved) = result { edition = saved }
            if case .unavailable = result { unavailable = true }
            loading = false
        }
    }
}

private struct SavedArticleView: View {
    let article: NewsArticle
    let userID: String
    @State private var detail: NewsArticle?
    @State private var nativeDeadlineUptime: TimeInterval = 0

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { context in
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    Text(article.title).font(.largeTitle).bold()
                    Text("Saved copy · not currently verified").font(.caption).foregroundStyle(.secondary)
                    if let detail, let deadline = detail.presentation?.offlineValidUntil,
                       let validated = detail.presentation?.validatedAt,
                       validated <= context.date.addingTimeInterval(60), deadline > context.date,
                       ProcessInfo.processInfo.systemUptime < nativeDeadlineUptime,
                       let text = detail.verifiedNativeBody {
                        Text(text).font(.body).textSelection(.enabled)
                    } else if let summary = article.summary {
                        Text(summary).font(.body).textSelection(.enabled)
                        Text("The full story is not available offline.").foregroundStyle(.secondary)
                    }
                    if let url = article.originalSourceURL {
                        Link("Open original source", destination: url)
                    }
                }.padding()
            }
        }
        .task(id: article.id) {
            let cached = await BackgroundNewsFetcher.shared.loadVerifiedArticleDetailAsync(articleID: article.id, forUserID: userID)
            guard !Task.isCancelled, AuthService.shared.state == .savedAccount(userID: userID) else { return }
            detail = cached.flatMap { article.mergingCompatibleCachedDetail($0) }
            nativeDeadlineUptime = ProcessInfo.processInfo.systemUptime
                + max(0, detail?.presentation?.offlineValidUntil?.timeIntervalSinceNow ?? 0)
        }
    }
}
