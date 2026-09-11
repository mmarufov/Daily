//
//  ArticleDetailView.swift
//  Daily
//

import SwiftUI

struct ArticleDetailView: View {
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var auth = AuthService.shared
    typealias FetchRelatedArticles = (
        _ query: String,
        _ limit: Int,
        _ accessToken: String
    ) async throws -> [NewsArticle]

    @StateObject private var reader: ArticleReaderModel
    @State private var sourceDestination: ArticleSourceDestination?
    @State private var showingChat = false
    @State private var relatedArticles: [NewsArticle] = []
    @State private var relatedDestination: ArticleReaderDestination?
    @State private var articleOpenTime = Date()
    @State private var activeReadStart: Date?
    @State private var activeReadArticle: NewsArticle?
    @State private var nativeBodyVisible = false
    @State private var viewportHeight: CGFloat = 0
    @State private var readerTask: Task<Void, Never>?
    @State private var relatedTask: Task<Void, Never>?
    @State private var requestedRelated = false
    @State private var hasTrackedOpen = false
    @State private var hasLoggedQualifyingRead = false
    @AppStorage("articleFontSize") private var fontSizeIndex = 2

    @ObservedObject private var bookmarks = BookmarkService.shared
    @StateObject private var tuneViewModel = TuneViewModel()

    private let accessTokenProvider: @MainActor () -> String?
    private let userIDProvider: @MainActor () -> String?
    private let fetchRelatedArticles: FetchRelatedArticles
    private let tracksOpenAutomatically: Bool

    init(
        article: NewsArticle,
        tracksOpenAutomatically: Bool = true,
        fetchArticle: @escaping ArticleReaderModel.FetchArticle = { articleID, accessToken in
            try await BackendService.shared.fetchFeedArticle(id: articleID, accessToken: accessToken)
        },
        accessTokenProvider: @escaping @MainActor () -> String? = {
            AuthService.shared.getAccessToken()
        },
        userIDProvider: @escaping @MainActor () -> String? = {
            AuthService.shared.currentUser?.id
        },
        fetchRelatedArticles: @escaping FetchRelatedArticles = { query, limit, accessToken in
            try await BackendService.shared.semanticSearch(
                query: query,
                limit: limit,
                accessToken: accessToken
            )
        }
    ) {
        _reader = StateObject(
            wrappedValue: ArticleReaderModel(article: article, fetchArticle: fetchArticle)
        )
        self.accessTokenProvider = accessTokenProvider
        self.userIDProvider = userIDProvider
        self.fetchRelatedArticles = fetchRelatedArticles
        self.tracksOpenAutomatically = tracksOpenAutomatically
    }

    private var article: NewsArticle { reader.state.article }
    private var fontSizeMultiplier: CGFloat {
        let sizes: [CGFloat] = [0.8, 0.9, 1.0, 1.15, 1.3]
        return sizes.indices.contains(fontSizeIndex) ? sizes[fontSizeIndex] : 1
    }
    private let fontSizeLabels = ["XS", "S", "M", "L", "XL"]

    var body: some View {
        ScrollView(.vertical, showsIndicators: false) {
            VStack(spacing: 0) {
                ArticleHeaderImage(article: article)

                VStack(alignment: .leading, spacing: AppSpacing.lg) {
                    ArticleMetadataHeader(article: article)
                    sourceAction
                    HairlineDivider()

                    if let summary = article.summary?.trimmingCharacters(in: .whitespacesAndNewlines),
                       !summary.isEmpty {
                        Text(summary)
                            .font(AppTypography.articleLeadIn)
                            .foregroundStyle(EditionPalette.ink)
                            .lineSpacing(4)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    readerContent
                    if reader.isSavedBody {
                        Text(reader.isRevalidating ? "Saved article · checking for updates" : "Saved article")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    discussButton
                    if !requestedRelated {
                        Button("Find related stories") {
                            requestedRelated = true
                            relatedTask = Task { await loadRelatedArticles() }
                        }
                    }
                    relatedStories
                }
                .frame(maxWidth: 700, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .center)
                .padding(.horizontal, AppSpacing.lg)
                .padding(.top, AppSpacing.lg)
                .padding(.bottom, AppSpacing.xxl)
            }
        }
        .background(EditionPalette.paper)
        .coordinateSpace(name: "ReaderViewport")
        .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { viewportHeight = $0 }
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { articleToolbar }
        .sheet(item: $sourceDestination) { destination in
            SafariView(url: destination.url)
                .ignoresSafeArea()
                .accessibilityIdentifier("article-source-reader")
        }
        .sheet(isPresented: $showingChat) {
            TuneView(
                viewModel: tuneViewModel,
                selectedTab: .constant(.tune),
                presentedAsSheet: true
            )
        }
        .articleReaderDestination($relatedDestination)
        .task {
            // SwiftUI may begin a view task while it is still committing the
            // current update. Yield once before publishing reader/bookmark
            // state so startup never mutates observable state reentrantly.
            await Task.yield()
            guard !Task.isCancelled else { return }
            trackOpenIfNeeded()
            articleOpenTime = Date()
            hasLoggedQualifyingRead = false
            readerTask = Task { await loadReaderContent() }
            await readerTask?.value
        }
        .onChange(of: scenePhase) { _, phase in
            reconcileReadingInterval()
            if phase == .active { retry() }
            else { readerTask?.cancel(); relatedTask?.cancel() }
        }
        .onChange(of: sourceDestination) { _, _ in reconcileReadingInterval() }
        .onChange(of: showingChat) { _, _ in reconcileReadingInterval() }
        .onChange(of: reader.state) { _, _ in
            if activeReadArticle?.readContentHash != reader.state.article.readContentHash { finishReadingInterval() }
            reconcileReadingInterval()
        }
        .onChange(of: auth.sessionGeneration) { _, _ in
            activeReadStart = nil; readerTask?.cancel(); relatedTask?.cancel()
            reader.invalidate(); relatedArticles = []; dismiss()
        }
        .onReceive(NotificationCenter.default.publisher(for: .deliveryMembershipChanged)) { notification in
            guard let cards = notification.object as? [NewsArticle] else { return }
            guard let contract = cards.first(where: { $0.id == article.id }),
                  contract.readerRoute == .native,
                  contract.acceptsReaderDetail(reader.state.article) else {
                finishReadingInterval(); readerTask?.cancel(); reader.invalidate()
                return
            }
        }
        .onDisappear {
            finishReadingInterval()
            trackQuickBackIfNeeded()
            readerTask?.cancel(); relatedTask?.cancel()
        }
    }

    @ToolbarContentBuilder
    private var articleToolbar: some ToolbarContent {
        ToolbarItemGroup(placement: .navigationBarTrailing) {
            Button { discussArticle() } label: {
                Image(systemName: "slider.horizontal.3")
                    .font(AppTypography.toolbarIcon)
            }
            .tint(EditionPalette.inkBlue)
            .accessibilityLabel("Discuss with AI")

            Button {
                HapticService.impact(.medium)
                bookmarks.toggleBookmark(article.safeForReaderCache())
            } label: {
                Image(systemName: bookmarks.isBookmarked(article.id) ? "bookmark.fill" : "bookmark")
                    .font(AppTypography.toolbarIcon)
            }
            .tint(EditionPalette.inkBlue)
            .accessibilityLabel(bookmarks.isBookmarked(article.id) ? "Remove bookmark" : "Add bookmark")

            if let url = article.originalSourceURL {
                ShareLink(item: url) {
                    Image(systemName: "square.and.arrow.up")
                        .font(AppTypography.toolbarIcon)
                }
                .tint(EditionPalette.inkBlue)
                .accessibilityLabel("Share original article")
            }

            Menu {
                ForEach(0..<fontSizeLabels.count, id: \.self) { index in
                    Button {
                        fontSizeIndex = index
                        HapticService.selection()
                    } label: {
                        HStack {
                            Text(fontSizeLabels[index])
                            if index == fontSizeIndex { Image(systemName: "checkmark") }
                        }
                    }
                }
            } label: {
                Image(systemName: "textformat.size")
                    .font(AppTypography.toolbarIcon)
            }
            .tint(EditionPalette.inkBlue)
            .accessibilityLabel("Change text size")
        }
    }

    @ViewBuilder
    private var sourceAction: some View {
        if let url = article.originalSourceURL {
            Button {
                guard sourceDestination == nil else { return }
                HapticService.impact(.light)
                sourceDestination = ArticleSourceDestination(articleID: article.id, url: url)
            } label: {
                HStack(spacing: AppSpacing.sm) {
                    Image(systemName: "safari")
                    Text("Read at \(article.displaySource)")
                    Spacer()
                    Image(systemName: "arrow.up.right")
                }
                .font(AppTypography.actionLabel)
                .foregroundStyle(EditionPalette.inkBlue)
                .padding(.vertical, AppSpacing.sm)
                .contentShape(Rectangle())
            }
            .accessibilityIdentifier("article-source-button")
            .accessibilityHint("Opens the original publisher website")
        } else {
            Label("Original source link unavailable", systemImage: "link.badge.plus")
                .font(AppTypography.subheadline)
                .foregroundStyle(EditionPalette.ink60)
                .accessibilityIdentifier("article-source-unavailable")
        }
    }

    @ViewBuilder
    private var readerContent: some View {
        switch reader.state {
        case .ready(let readyArticle):
            nativeBody(for: readyArticle)
        case .loading(_):
            ArticleReaderStatusView(
                icon: nil,
                title: "Loading article",
                message: "Keeping the story information available while the full text loads.",
                showsProgress: true,
                retryAction: nil
            )
        case .sourceAvailable(_, let message):
            ArticleReaderStatusView(
                icon: "safari",
                title: "Continue at the publisher",
                message: message,
                showsProgress: false,
                retryAction: nil
            )
        case .authenticationRequired(_, let message):
            ArticleReaderStatusView(
                icon: "person.crop.circle.badge.exclamationmark",
                title: "Sign in required",
                message: message,
                showsProgress: false,
                retryAction: nil
            )
        case .offline(_, let message):
            ArticleReaderStatusView(
                icon: "wifi.exclamationmark",
                title: "You're offline",
                message: message,
                showsProgress: false,
                retryAction: retry
            )
        case .failed(_, let message):
            ArticleReaderStatusView(
                icon: "exclamationmark.triangle",
                title: "Article unavailable",
                message: message,
                showsProgress: false,
                retryAction: retry
            )
        case .unavailable(_, let message):
            ArticleReaderStatusView(
                icon: "doc.questionmark",
                title: "Article unavailable",
                message: message,
                showsProgress: false,
                retryAction: nil
            )
        case .preview(_):
            ArticleReaderStatusView(
                icon: "doc.text",
                title: "Preparing article",
                message: "The headline, summary, and original source remain available.",
                showsProgress: false,
                retryAction: nil
            )
        }
    }

    @ViewBuilder
    private func nativeBody(for readyArticle: NewsArticle) -> some View {
        if readyArticle.verifiedNativeBody != nil {
            let paragraphs = reader.paragraphs
            VStack(alignment: .leading, spacing: AppSpacing.md) {
                ForEach(Array(paragraphs.enumerated()), id: \.offset) { _, paragraph in
                    ArticleBodyTextView(
                        text: paragraph,
                        lineSpacing: 6,
                        fontSizeMultiplier: fontSizeMultiplier
                    )
                }
            }
            .accessibilityIdentifier("article-native-body")
            .onGeometryChange(for: Bool.self) { geometry in
                let viewport = CGRect(x: 0, y: 0, width: geometry.size.width, height: viewportHeight)
                return geometry.frame(in: .named("ReaderViewport")).intersection(viewport).height >= 20
            } action: { visible in
                nativeBodyVisible = visible
                reconcileReadingInterval()
            }
        }
    }

    private var discussButton: some View {
        Button { discussArticle() } label: {
            HStack(spacing: AppSpacing.sm) {
                Image(systemName: "slider.horizontal.3")
                    .font(AppTypography.actionIcon)
                Text("Discuss with Daily AI")
                    .font(AppTypography.actionLabel)
            }
            .foregroundStyle(EditionPalette.inkBlue)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 14)
            .overlay(
                RoundedRectangle(cornerRadius: AppCornerRadius.button)
                    .stroke(EditionPalette.inkBlue, lineWidth: 1)
            )
        }
        .padding(.top, AppSpacing.md)
    }

    @ViewBuilder
    private var relatedStories: some View {
        if !relatedArticles.isEmpty {
            HairlineDivider()
                .padding(.vertical, AppSpacing.lg)

            Text("MORE LIKE THIS")
                .font(AppTypography.sectionTitle)
                .foregroundStyle(EditionPalette.inkBlue)
                .tracking(0.8)

            VStack(spacing: 0) {
                let related = Array(relatedArticles.prefix(4))
                ForEach(Array(related.enumerated()), id: \.element.id) { index, item in
                    ArticleReaderButton(article: item, destination: $relatedDestination) {
                        StoryRow(article: item)
                    }
                    .buttonStyle(PressableButtonStyle())

                    if index < related.count - 1 {
                        Rectangle()
                            .fill(EditionPalette.sepia)
                            .frame(height: EditionPalette.hairlineWidth)
                    }
                }
            }
        }
    }

    private func retry() {
        readerTask?.cancel()
        finishReadingInterval()
        reader.invalidate() // Fence a transport that completes after cancellation.
        readerTask = Task { await loadReaderContent() }
    }

    private func loadReaderContent() async {
        let userID = userIDProvider()
        let session = auth.sessionGeneration
        var cachedDetail: NewsArticle?
        if let userID {
            cachedDetail = await BackgroundNewsFetcher.shared.loadVerifiedArticleDetailAsync(articleID: article.id, forUserID: userID)
        }
        guard !Task.isCancelled, session == auth.sessionGeneration, userID == userIDProvider() else { return }
        _ = await reader.load(
            accessToken: accessTokenProvider(),
            cachedDetail: cachedDetail,
            revalidate: true,
            isCurrent: { session == auth.sessionGeneration && userID == userIDProvider() },
            accept: { disposition in
                guard session == auth.sessionGeneration, userID == userIDProvider() else { return false }
                guard let userID else { return true } // Isolated injected UI-test reader.
                do {
                    switch disposition {
                    case .store(let detail):
                        let result = try await BackgroundNewsFetcher.shared.storeVerifiedArticleDetailAsync(
                            detail, forUserID: userID, sessionGeneration: session)
                        return result != .rejectedStale
                    case .evict(let id):
                        let result = try await BackgroundNewsFetcher.shared.removeVerifiedArticleDetailAsync(
                            articleID: id, forUserID: userID, sessionGeneration: session)
                        return result != .rejectedStale
                    case .none: return true
                    }
                } catch { return false }
            }
        )
    }

    private func reconcileReadingInterval() {
        let eligible = scenePhase == .active && nativeBodyVisible && reader.state.isDisplayingNativeBody
            && sourceDestination == nil && !showingChat
        if eligible && activeReadStart == nil {
            activeReadStart = Date(); activeReadArticle = reader.state.article
        }
        if !eligible { finishReadingInterval() }
    }
    private func finishReadingInterval() {
        guard let start = activeReadStart else { return }
        activeReadStart = nil
        let displayed = activeReadArticle ?? reader.state.article
        activeReadArticle = nil
        let duration = Int(Date().timeIntervalSince(start))
        if duration >= 5 { hasLoggedQualifyingRead = true }
        ReadingEventTracker.shared.logRead(article: displayed,
            durationSeconds: duration, nativeBodyWasDisplayed: true)
    }

    /// S10 B1: fires only on a genuine navigation-away from this article
    /// (.onDisappear -- the view leaving the navigation stack), never on
    /// backgrounding the app (scenePhase changes go through a separate path
    /// and never call this). Distinguishes "the reader didn't want this" from
    /// "the reader left the app", per tasks/s10-implementation-plan.md batch B.
    private func trackQuickBackIfNeeded() {
        guard !hasLoggedQualifyingRead,
              Date().timeIntervalSince(articleOpenTime) < 8 else { return }
        ReadingEventTracker.shared.logSkip(article: article)
    }

    private func trackOpenIfNeeded() {
        guard tracksOpenAutomatically, !hasTrackedOpen else { return }
        hasTrackedOpen = true
        bookmarks.markAsRead(article.id)
        ReadingEventTracker.shared.logTap(article: article)
    }

    private func discussArticle() {
        HapticService.impact(.medium)
        let session = auth.sessionGeneration
        Task {
            await tuneViewModel.startArticleDiscussion(article)
            guard !Task.isCancelled, session == auth.sessionGeneration else { return }
            showingChat = true
        }
    }

    private func loadRelatedArticles() async {
        let session = auth.sessionGeneration
        guard let token = accessTokenProvider(),
              let results = try? await fetchRelatedArticles(article.title, 5, token) else {
            return
        }
        guard !Task.isCancelled, session == auth.sessionGeneration else { return }
        relatedArticles = results
            .filter { $0.id != article.id }
            .map { $0.safeForReaderCache().normalizedForDisplay() }
    }

    private func contentParagraphs(from content: String) -> [String] {
        ArticleTextNormalizer.normalizeBody(content)
            .components(separatedBy: "\n\n")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }
}

private struct ArticleHeaderImage: View {
    let article: NewsArticle

    var body: some View {
        if let url = article.displayImageURL {
            ZStack(alignment: .bottomTrailing) {
                ArticleRemoteImage(url: url, pixelSize: 1200)
                    .frame(maxWidth: .infinity).frame(height: 220).clipped()
                if article.imageIsIllustrative {
                    Text("Illustration")
                        .font(AppTypography.chipIcon)
                        .textCase(.uppercase)
                        .padding(.horizontal, AppSpacing.sm)
                        .padding(.vertical, AppSpacing.xs)
                        .foregroundStyle(Color.white)
                        .background(Color.black.opacity(0.72))
                        .padding(AppSpacing.sm)
                }
            }
        }
    }

    private var placeholder: some View {
        Rectangle()
            .fill(EditionPalette.paperSecondary)
            .frame(height: 220)
    }
}

private struct ArticleMetadataHeader: View {
    let article: NewsArticle

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.lg) {
            HStack(spacing: AppSpacing.sm) {
                Text(article.displaySource)
                    .textCase(.uppercase)
                    .accessibilityLabel(article.displaySource)
                    .font(AppTypography.sourceLabel)
                    .tracking(0.8)
                    .foregroundStyle(EditionPalette.inkBlue)

                if let category = article.category, !category.isEmpty {
                    Circle()
                        .fill(EditionPalette.ink60)
                        .frame(width: 3, height: 3)
                    Text(category)
                        .textCase(.uppercase)
                        .accessibilityLabel(category)
                        .font(AppTypography.chipIcon)
                        .tracking(0.6)
                        .foregroundStyle(EditionPalette.ink60)
                }
            }

            Text(article.title)
                .font(AppTypography.articleTitle)
                .foregroundStyle(EditionPalette.ink)
                .fixedSize(horizontal: false, vertical: true)
                .lineSpacing(4)
                .accessibilityIdentifier("article-title")

            VStack(alignment: .leading, spacing: AppSpacing.xs) {
                if let author = article.author, !author.isEmpty {
                    Text("By \(author)")
                        .font(AppTypography.articleAuthor)
                        .foregroundStyle(EditionPalette.ink60)
                }
                HStack(spacing: AppSpacing.xs) {
                    if let publishedAt = article.publishedAt {
                        Text(publishedAt.formatted(date: .long, time: .omitted))
                            .font(AppTypography.caption1)
                            .foregroundStyle(EditionPalette.ink60)
                    }
                    Text("\(article.estimatedReadingTime) min read")
                        .font(AppTypography.caption1)
                        .foregroundStyle(EditionPalette.ink60)
                }
            }
        }
    }
}

private struct ArticleReaderStatusView: View {
    let icon: String?
    let title: String
    let message: String
    let showsProgress: Bool
    let retryAction: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm) {
            HStack(spacing: AppSpacing.sm) {
                if showsProgress {
                    ProgressView()
                } else if let icon {
                    Image(systemName: icon)
                        .foregroundStyle(EditionPalette.ink60)
                }
                Text(title)
                    .font(AppTypography.headline)
                    .foregroundStyle(EditionPalette.ink)
            }

            Text(message)
                .font(AppTypography.subheadline)
                .foregroundStyle(EditionPalette.ink60)
                .fixedSize(horizontal: false, vertical: true)

            if let retryAction {
                Button("Try again", action: retryAction)
                    .buttonStyle(.bordered)
                    .accessibilityIdentifier("article-retry-button")
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(AppSpacing.md)
        .background(EditionPalette.paperSecondary)
        .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("article-reader-status")
    }
}

#Preview {
    NavigationStack {
        ArticleDetailView(
            article: NewsArticle(
                id: "1",
                title: "Sample Article Title for Detail View",
                summary: "This is a concise summary of the article to give the reader context.",
                content: nil,
                author: "John Doe",
                source: "Tech News",
                imageURL: nil,
                publishedAt: Date(),
                category: "Technology",
                url: "https://example.com"
            )
        )
    }
}
