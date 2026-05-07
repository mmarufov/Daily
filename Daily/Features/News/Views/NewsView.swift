//
//  NewsView.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI

struct NewsView: View {
    @ObservedObject var viewModel: NewsViewModel
    @ObservedObject private var auth = AuthService.shared
    @ObservedObject private var bookmarks = BookmarkService.shared
    @State private var showingProfile = false
    @State private var showWelcomeBanner = false
    @State private var briefingContent: String?
    @State private var selectedFeedbackArticle: NewsArticle?

    var body: some View {
        NavigationStack {
            ScrollView(.vertical, showsIndicators: false) {
                LazyVStack(alignment: .leading, spacing: 0) {
                    editionHeader

                    if showWelcomeBanner {
                        welcomeBanner
                            .padding(.horizontal, AppSpacing.lg)
                            .padding(.bottom, AppSpacing.md)
                            .transition(.move(edge: .top).combined(with: .opacity))
                    }

                    if viewModel.articles.isEmpty && !viewModel.isLoading {
                        EmptyStateView(
                            icon: "newspaper",
                            title: "No articles yet",
                            subtitle: viewModel.errorMessage ?? "Pull down to refresh your feed."
                        )
                        .padding(.horizontal, AppSpacing.lg)
                        .padding(.top, AppSpacing.xxl)
                    } else if viewModel.isLoading {
                        VStack(alignment: .leading, spacing: AppSpacing.md) {
                            Text("Loading your personalized feed...")
                                .font(AppTypography.subheadline)
                                .foregroundColor(BrandColors.textSecondary)
                                .padding(.horizontal, AppSpacing.lg)

                            skeletonLoading
                                .padding(.horizontal, AppSpacing.lg)
                        }
                        .padding(.top, AppSpacing.md)
                    } else {
                        if let error = viewModel.errorMessage, !error.isEmpty {
                            errorBanner(error)
                                .padding(.horizontal, AppSpacing.lg)
                                .padding(.bottom, AppSpacing.md)
                        }

                        feedContent
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.bottom, AppSpacing.xxl)
            }
            .background(EditionPalette.paper)
            .refreshable {
                await viewModel.refreshFeed()
            }
            .sheet(isPresented: $showingProfile) {
                ProfileView()
            }
            .sheet(item: $selectedFeedbackArticle) { article in
                WhyThisStorySheet(
                    reason: feedbackReason(for: article),
                    onLessOfThis: { Task { await viewModel.submitFeedback(for: article, action: "less_like_this") } },
                    onWrongReason: { Task { await viewModel.submitFeedback(for: article, action: "not_relevant") } },
                    onHide: { Task { await viewModel.submitFeedback(for: article, action: "hide_source") } }
                )
            }
            .overlay {
                if viewModel.isSettingUp, let phase = viewModel.setupPhase {
                    BuildingFeedView(phase: phase, detailText: viewModel.setupDetailText)
                        .transition(.opacity)
                }
            }
            .onReceive(NotificationCenter.default.publisher(for: .onboardingCompleted)) { _ in
                withAnimation(.easeInOut(duration: 0.4)) {
                    showWelcomeBanner = true
                }
                Task {
                    try? await Task.sleep(for: .seconds(3))
                    withAnimation(.easeInOut(duration: 0.4)) {
                        showWelcomeBanner = false
                    }
                }
            }
            .task {
                // Load morning briefing
                guard let token = AuthService.shared.getAccessToken() else { return }
                if let response = try? await BackendService.shared.fetchBriefing(accessToken: token),
                   let content = response.content {
                    briefingContent = content
                }
            }
        }
    }
}

// MARK: - Private builders

private extension NewsView {
    var editionHeader: some View {
        EditionHeader(dateLabel: editionDateLabel, editionName: editionName) {
            profileAvatar
        }
    }

    @ViewBuilder
    var profileAvatar: some View {
        Button(action: { showingProfile = true }) {
            ZStack {
                if let photoURL = auth.currentUser?.photo_url,
                   let url = URL(string: photoURL) {
                    AsyncImage(url: url) { phase in
                        switch phase {
                        case .success(let image):
                            image.resizable().aspectRatio(contentMode: .fill)
                        default:
                            Image(systemName: "person.crop.circle.fill")
                                .resizable()
                                .aspectRatio(contentMode: .fit)
                                .foregroundStyle(EditionPalette.ink60)
                        }
                    }
                } else {
                    Image(systemName: "person.crop.circle.fill")
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .foregroundStyle(EditionPalette.ink60)
                }
            }
            .frame(width: 44, height: 44)
            .clipShape(Circle())
        }
        .accessibilityLabel("Open profile")
    }

    var editionDateLabel: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "MMM d"
        return formatter.string(from: Date()).uppercased()
    }

    var editionName: String {
        auth.currentUser?.display_name?
            .split(separator: " ")
            .first
            .map(String.init)?
            .uppercased() ?? "YOU"
    }

    // MARK: - Skeleton Loading

    var skeletonLoading: some View {
        VStack(alignment: .leading, spacing: 0) {
            SkeletonFeaturedCard()

            HairlineDivider()
                .padding(.vertical, AppSpacing.lg)

            ForEach(0..<3, id: \.self) { _ in
                SkeletonFeedCard()
                HairlineDivider()
                    .padding(.vertical, AppSpacing.md)
            }
        }
    }

    // MARK: - Feed content

    var feedContent: some View {
        let articles = viewModel.articles

        return VStack(alignment: .leading, spacing: 0) {
            // Briefing card
            if let briefing = briefingContent {
                BriefingCard(content: briefing)
                    .padding(.horizontal, AppSpacing.lg)
                    .padding(.bottom, AppSpacing.md)
            }

            // Top Story (hero — full bleed)
            if let featured = articles.first {
                sectionLabel("Top Story")
                    .padding(.horizontal, AppSpacing.lg)
                    .padding(.bottom, AppSpacing.md)

                NavigationLink(destination: ArticleDetailView(article: featured)) {
                    HeroStory(
                        article: featured,
                        provenance: featured.whyThisStory,
                        isRead: bookmarks.isRead(featured.id)
                    )
                }
                .buttonStyle(PressableButtonStyle())
                .onLongPressGesture {
                    HapticService.impact(.medium)
                    selectedFeedbackArticle = featured
                }
                .onAppear {
                    ReadingEventTracker.shared.logImpression(articleId: featured.id, position: 0)
                }
            }

            // For You — uniform story rows, hairline-separated
            if articles.count > 1 {
                sepiaHairline
                    .padding(.horizontal, AppSpacing.lg)
                    .padding(.vertical, AppSpacing.lg)

                sectionLabel("For You")
                    .padding(.horizontal, AppSpacing.lg)
                    .padding(.bottom, AppSpacing.sm)

                VStack(spacing: 0) {
                    ForEach(Array(articles.dropFirst().enumerated()), id: \.element.id) { index, article in
                        NavigationLink(destination: ArticleDetailView(article: article)) {
                            StoryRow(
                                article: article,
                                isRead: bookmarks.isRead(article.id)
                            )
                        }
                        .buttonStyle(PressableButtonStyle())
                        .onLongPressGesture {
                            HapticService.impact(.medium)
                            selectedFeedbackArticle = article
                        }
                        .onAppear {
                            ReadingEventTracker.shared.logImpression(articleId: article.id, position: index + 1)
                        }

                        sepiaHairline
                            .padding(.horizontal, AppSpacing.lg)
                    }
                }
            }
        }
    }

    var sepiaHairline: some View {
        Rectangle()
            .fill(EditionPalette.sepia)
            .frame(height: EditionPalette.hairlineWidth)
    }

    func feedbackReason(for article: NewsArticle) -> String {
        if let reason = article.whyThisStory, !reason.isEmpty {
            return reason
        }
        return "I'm not sure why I picked this — tell me if it's off."
    }

    var welcomeBanner: some View {
        HStack(spacing: AppSpacing.sm) {
            Image(systemName: "checkmark.circle.fill")
                .font(AppTypography.headline)
                .foregroundColor(BrandColors.success)

            Text("Your personalized feed is ready")
                .font(AppTypography.subheadline)
                .foregroundColor(BrandColors.textPrimary)

            Spacer()
        }
        .padding(AppSpacing.md)
        .background(BrandColors.success.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous))
    }

    func sectionLabel(_ title: String) -> some View {
        Text(title)
            .font(AppTypography.metaCaps)
            .tracking(0.8)
            .textCase(.uppercase)
            .foregroundStyle(EditionPalette.inkBlue)
    }

    func errorBanner(_ message: String) -> some View {
        HStack(spacing: AppSpacing.sm) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(AppTypography.navIcon)
                .foregroundColor(BrandColors.warning)

            Text(message)
                .font(AppTypography.bodySmall)
                .foregroundColor(BrandColors.textPrimary)
                .fixedSize(horizontal: false, vertical: true)

            Spacer()

            Button {
                HapticService.impact(.light)
                withAnimation { viewModel.errorMessage = nil }
            } label: {
                Image(systemName: "xmark")
                    .font(AppTypography.sourceLabel)
                    .foregroundColor(BrandColors.textTertiary)
            }
        }
        .padding(AppSpacing.md)
        .background(BrandColors.warning.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous))
    }
}

// MARK: - Featured Article Card (legacy — removed in Phase 9 cleanup)

struct FeaturedArticleCard: View {
    let article: NewsArticle
    var isRead: Bool = false
    var style: CardStyle = .standard

    enum CardStyle {
        case standard  // 200px image, feedHeroTitle font
        case feed      // 180px image, feedHeroTitle font, 2-line summary
        case hero      // 260px image, articleTitle font (28pt)
    }

    private var imageHeight: CGFloat {
        switch style {
        case .hero:
            return 260
        case .feed:
            return 180
        case .standard:
            return 200
        }
    }

    private var titleFont: Font {
        style == .hero ? AppTypography.heroHeadline : AppTypography.feedHeroTitle
    }

    private var summaryFont: Font {
        style == .hero ? AppTypography.articleLeadIn : AppTypography.subheadline
    }

    private var headlineTracking: CGFloat {
        style == .hero ? -0.7 : -0.3
    }

    private var headlineLineSpacing: CGFloat {
        style == .hero ? 4 : 2
    }

    private var summaryLineSpacing: CGFloat {
        style == .hero ? 3 : 1
    }

    private var summaryLineLimit: Int {
        switch style {
        case .hero:
            return 3
        case .feed:
            return 2
        case .standard:
            return 2
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.smPlus) {
            // Image
            ZStack {
                if let imageURL = article.imageURL, let url = URL(string: imageURL) {
                    AsyncImage(url: url) { phase in
                        switch phase {
                        case .success(let image):
                            image.resizable().aspectRatio(contentMode: .fill)
                        default:
                            featuredPlaceholder
                        }
                    }
                } else {
                    featuredPlaceholder
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: imageHeight)
            .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.image, style: .continuous))

            // Source + time + reading time + badge
            HStack(spacing: AppSpacing.xs) {
                if !isRead {
                    Circle()
                        .fill(BrandColors.primary)
                        .frame(width: 6, height: 6)
                }

                Text(article.displaySource)
                    .textCase(.uppercase)
                    .accessibilityLabel(article.displaySource)
                    .font(AppTypography.sourceLabel)
                    .foregroundColor(BrandColors.sourceText)

                if !article.formattedDate.isEmpty {
                    Circle()
                        .fill(BrandColors.textQuaternary)
                        .frame(width: 3, height: 3)
                    Text(article.formattedDate)
                        .font(AppTypography.dateLabel)
                        .foregroundColor(BrandColors.textTertiary)
                }

                Circle()
                    .fill(BrandColors.textQuaternary)
                    .frame(width: 3, height: 3)
                Text("\(article.estimatedReadingTime) min")
                    .font(AppTypography.dateLabel)
                    .foregroundColor(BrandColors.textTertiary)

                Spacer()

                ArticleBadge(publishedAt: article.publishedAt)
            }

            // Headline
            Text(article.title)
                .font(titleFont)
                .foregroundColor(BrandColors.textPrimary)
                .opacity(isRead ? 0.6 : 1)
                .lineLimit(3)
                .tracking(headlineTracking)
                .lineSpacing(headlineLineSpacing)
                .fixedSize(horizontal: false, vertical: true)

            // Summary
            if let summary = article.summary, !summary.isEmpty {
                Text(summary)
                    .font(summaryFont)
                    .foregroundColor(BrandColors.textSecondary)
                    .lineLimit(summaryLineLimit)
                    .lineSpacing(summaryLineSpacing)
            }
        }
    }

    private var featuredPlaceholder: some View {
        ZStack {
            LinearGradient(
                colors: [
                    Color(.systemGray4),
                    Color(.systemGray5)
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )

            VStack(spacing: AppSpacing.sm) {
                Image(systemName: "newspaper.fill")
                    .font(AppTypography.iconLarge)
                    .foregroundColor(Color(.systemGray2))

                Text(article.displaySource)
                    .textCase(.uppercase)
                    .accessibilityLabel(article.displaySource)
                    .font(AppTypography.metaLabel)
                    .foregroundColor(Color(.systemGray2))
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}


#Preview {
    NewsView(viewModel: NewsViewModel())
}
