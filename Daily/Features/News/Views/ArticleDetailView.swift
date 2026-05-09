//
//  ArticleDetailView.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI
import SafariServices

struct ArticleDetailView: View {
    let article: NewsArticle

    @State private var fullArticle: NewsArticle?
    @State private var isLoadingFullContent = false
    @State private var loadErrorMessage: String?
    @State private var showingSafari = false
    @State private var showingTextSize = false
    @State private var showingChat = false
    @State private var relatedArticles: [NewsArticle] = []
    @AppStorage("articleFontSize") private var fontSizeIndex: Int = 2 // 0-4, default middle
    @State private var articleOpenTime = Date()

    @ObservedObject private var bookmarks = BookmarkService.shared
    @StateObject private var tuneViewModel = TuneViewModel()

    private var fontSizeMultiplier: CGFloat {
        [0.8, 0.9, 1.0, 1.15, 1.3][fontSizeIndex]
    }

    private let fontSizeLabels = ["XS", "S", "M", "L", "XL"]

    var body: some View {
        Group {
            if isLoadingFullContent && fullArticle == nil {
                VStack(spacing: AppSpacing.md) {
                    ProgressView()
                        .scaleEffect(1.1)
                    Text("Loading article...")
                        .font(AppTypography.subheadline)
                        .foregroundStyle(EditionPalette.ink60)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let error = loadErrorMessage, fullArticle == nil {
                VStack(spacing: AppSpacing.md) {
                    Image(systemName: "exclamationmark.triangle")
                        .font(AppTypography.iconMedium)
                        .foregroundStyle(EditionPalette.ink60)
                    Text(error)
                        .font(AppTypography.subheadline)
                        .foregroundStyle(EditionPalette.error)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, AppSpacing.xxl)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .onTapGesture {
                    loadErrorMessage = nil
                    Task { await loadFullArticleIfNeeded() }
                }
            } else {
                ScrollView(.vertical, showsIndicators: false) {
                    VStack(spacing: 0) {
                        if let full = fullArticle {
                            headerImage(for: full)

                            VStack(alignment: .leading, spacing: AppSpacing.lg) {
                                // Source + category
                                HStack(spacing: AppSpacing.sm) {
                                    Text(full.displaySource)
                                        .textCase(.uppercase)
                                        .accessibilityLabel(full.displaySource)
                                        .font(AppTypography.sourceLabel)
                                        .tracking(0.8)
                                        .foregroundStyle(EditionPalette.inkBlue)

                                    if let category = full.category, !category.isEmpty {
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

                                // Title
                                Text(full.title)
                                    .font(AppTypography.articleTitle)
                                    .foregroundStyle(EditionPalette.ink)
                                    .fixedSize(horizontal: false, vertical: true)
                                    .lineSpacing(4)

                                // Author + Date + Reading Time
                                VStack(alignment: .leading, spacing: AppSpacing.xs) {
                                    if let author = full.author, !author.isEmpty {
                                        Text("By \(author)")
                                            .font(AppTypography.articleAuthor)
                                            .foregroundStyle(EditionPalette.ink60)
                                    }
                                    HStack(spacing: AppSpacing.xs) {
                                        if let publishedAt = full.publishedAt {
                                            Text(formattedFullDate(publishedAt))
                                                .font(AppTypography.caption1)
                                                .foregroundStyle(EditionPalette.ink60)
                                        }
                                        Circle()
                                            .fill(EditionPalette.ink60)
                                            .frame(width: 3, height: 3)
                                        Text("\(full.estimatedReadingTime) min read")
                                            .font(AppTypography.caption1)
                                            .foregroundStyle(EditionPalette.ink60)
                                    }
                                }

                                // Divider
                                HairlineDivider()

                                // Summary / lede
                                if let summary = full.summary,
                                   !summary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                                    Text(summary.trimmingCharacters(in: .whitespacesAndNewlines))
                                        .font(AppTypography.articleLeadIn)
                                        .foregroundStyle(EditionPalette.ink)
                                        .lineSpacing(4)
                                        .fixedSize(horizontal: false, vertical: true)
                                }

                                // Content
                                contentSection(for: full)

                                // Discuss with AI
                                discussButton(for: full)

                                // External link
                                externalLinkButton(for: full)

                                // Related articles
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
                                            NavigationLink(destination: ArticleDetailView(article: item)) {
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
                            .frame(maxWidth: 700, alignment: .leading)
                            .frame(maxWidth: .infinity, alignment: .center)
                            .padding(.horizontal, AppSpacing.lg)
                            .padding(.top, AppSpacing.lg)
                            .padding(.bottom, AppSpacing.xxl)
                        }
                    }
                }
            }
        }
        .background(EditionPalette.paper)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .navigationBarTrailing) {
                // Discuss
                Button {
                    HapticService.impact(.medium)
                    if let full = fullArticle {
                        Task {
                            await tuneViewModel.startArticleDiscussion(full)
                            showingChat = true
                        }
                    }
                } label: {
                    Image(systemName: "slider.horizontal.3")
                        .font(AppTypography.toolbarIcon)
                }
                .tint(EditionPalette.inkBlue)
                .accessibilityLabel("Discuss with AI")

                // Bookmark
                Button {
                    HapticService.impact(.medium)
                    if let full = fullArticle ?? Optional(article) {
                        bookmarks.toggleBookmark(full)
                    }
                } label: {
                    Image(systemName: bookmarks.isBookmarked(article.id) ? "bookmark.fill" : "bookmark")
                        .font(AppTypography.toolbarIcon)
                }
                .tint(EditionPalette.inkBlue)
                .accessibilityLabel(bookmarks.isBookmarked(article.id) ? "Remove bookmark" : "Add bookmark")

                // Share
                if let urlString = (fullArticle ?? article).url, let url = URL(string: urlString) {
                    ShareLink(item: url) {
                        Image(systemName: "square.and.arrow.up")
                            .font(AppTypography.toolbarIcon)
                    }
                    .tint(EditionPalette.inkBlue)
                    .accessibilityLabel("Share article")
                }

                // Text size
                Menu {
                    ForEach(0..<fontSizeLabels.count, id: \.self) { index in
                        Button {
                            fontSizeIndex = index
                            HapticService.selection()
                        } label: {
                            HStack {
                                Text(fontSizeLabels[index])
                                if index == fontSizeIndex {
                                    Image(systemName: "checkmark")
                                }
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
        .sheet(isPresented: $showingSafari) {
            if let urlString = (fullArticle ?? article).url, let url = URL(string: urlString) {
                SafariView(url: url)
                    .ignoresSafeArea()
            }
        }
        .sheet(isPresented: $showingChat) {
            TuneView(
                viewModel: tuneViewModel,
                selectedTab: .constant(.tune),
                presentedAsSheet: true
            )
        }
        .task {
            BookmarkService.shared.markAsRead(article.id)
            ReadingEventTracker.shared.logTap(articleId: article.id)
            articleOpenTime = Date()
            await loadFullArticleIfNeeded()
        }
        .onDisappear {
            let duration = Int(Date().timeIntervalSince(articleOpenTime))
            ReadingEventTracker.shared.logRead(articleId: article.id, durationSeconds: duration)
        }
        .task(id: fullArticle?.id) {
            guard fullArticle != nil,
                  let token = AuthService.shared.getAccessToken() else { return }
            if let results = try? await BackendService.shared.semanticSearch(
                query: article.title, limit: 5, accessToken: token
            ) {
                relatedArticles = results.filter { $0.id != article.id }
            }
        }
    }

    // MARK: - Header Image

    @ViewBuilder
    private func headerImage(for article: NewsArticle) -> some View {
        if let imageURL = fullArticle?.imageURL ?? self.article.imageURL,
           let url = URL(string: imageURL) {
            AsyncImage(url: url) { phase in
                switch phase {
                case .success(let image):
                    image
                        .resizable()
                        .aspectRatio(contentMode: .fill)
                        .frame(maxWidth: .infinity)
                        .frame(height: 220)
                        .clipped()
                default:
                    Rectangle()
                        .fill(EditionPalette.paperSecondary)
                        .frame(height: 220)
                }
            }
        }
    }

    // MARK: - Content

    @ViewBuilder
    private func contentSection(for article: NewsArticle) -> some View {
        if let content = article.content,
           !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            VStack(alignment: .leading, spacing: AppSpacing.md) {
                ForEach(contentParagraphs(from: content), id: \.self) { paragraph in
                    ArticleBodyTextView(
                        text: paragraph,
                        lineSpacing: 6,
                        fontSizeMultiplier: fontSizeMultiplier
                    )
                }
            }
        } else if !isLoadingFullContent {
            VStack(spacing: AppSpacing.sm) {
                Text("Full article content is not available.")
                    .font(AppTypography.subheadline)
                    .foregroundStyle(EditionPalette.ink60)

                if article.url != nil {
                    Text("Read the full article at the source below.")
                        .font(AppTypography.caption1)
                        .foregroundStyle(EditionPalette.ink60)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, AppSpacing.md)
        }
    }

    private func discussButton(for article: NewsArticle) -> some View {
        Button {
            HapticService.impact(.medium)
            Task {
                await tuneViewModel.startArticleDiscussion(article)
                showingChat = true
            }
        } label: {
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
    private func externalLinkButton(for article: NewsArticle) -> some View {
        if article.url != nil {
            Button {
                showingSafari = true
            } label: {
                HStack(spacing: AppSpacing.xs) {
                    Text("Read full article at \(article.displaySource)")
                        .font(AppTypography.actionIcon)
                    Image(systemName: "arrow.up.right")
                        .font(AppTypography.sourceLabel)
                }
                .foregroundStyle(EditionPalette.inkBlue)
            }
            .padding(.top, AppSpacing.md)
        }
    }

    // MARK: - Helpers

    private func loadFullArticleIfNeeded() async {
        guard !isLoadingFullContent, fullArticle == nil else { return }

        if let existingContent = article.content, existingContent.count > 500 {
            fullArticle = article.normalizedForDisplay()
            return
        }

        guard let token = AuthService.shared.getAccessToken() else { return }

        isLoadingFullContent = true
        loadErrorMessage = nil

        do {
            let fetched = try await BackendService.shared.fetchFeedArticle(id: article.id, accessToken: token)
            fullArticle = NewsArticle(
                id: fetched.id,
                title: fetched.title,
                summary: fetched.summary ?? article.summary,
                content: fetched.content ?? article.content,
                author: fetched.author ?? article.author,
                source: fetched.source ?? article.source,
                imageURL: fetched.imageURL ?? article.imageURL,
                publishedAt: fetched.publishedAt ?? article.publishedAt,
                category: fetched.category ?? article.category,
                url: fetched.url ?? article.url
            ).normalizedForDisplay()
            isLoadingFullContent = false
        } catch {
            loadErrorMessage = "Couldn't load article. Tap to retry."
            isLoadingFullContent = false
        }
    }

    private func contentParagraphs(from content: String) -> [String] {
        ArticleTextNormalizer.normalizeBody(content)
            .components(separatedBy: "\n\n")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }

    private func formattedFullDate(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateStyle = .long
        formatter.timeStyle = .none
        return formatter.string(from: date)
    }
}

#Preview {
    NavigationView {
        ArticleDetailView(
            article: NewsArticle(
                id: "1",
                title: "Sample Article Title for Detail View",
                summary: "This is a concise summary of the article to give the reader context.",
                content: "This is the first paragraph.\n\nThis is another paragraph with more details.",
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
