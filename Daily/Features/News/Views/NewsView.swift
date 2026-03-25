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

    var body: some View {
        NavigationStack {
            ScrollView(.vertical, showsIndicators: false) {
                LazyVStack(alignment: .leading, spacing: 0) {
                    dateHeader
                        .padding(.horizontal, AppSpacing.lg)
                        .padding(.top, AppSpacing.md)
                        .padding(.bottom, AppSpacing.lg)

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
            .background(Color(.systemBackground))
            .refreshable {
                await viewModel.refreshFeed()
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                toolbarContent
            }
            .sheet(isPresented: $showingProfile) {
                ProfileView()
            }
        }
    }
}

// MARK: - Private builders

private extension NewsView {
    var greeting: String {
        let hour = Calendar.current.component(.hour, from: Date())
        let firstName = auth.currentUser?.display_name?.components(separatedBy: " ").first

        switch hour {
        case 5..<12:
            if let name = firstName { return "Good morning, \(name)" }
            return "Good morning"
        case 12..<17:
            if let name = firstName { return "Good afternoon, \(name)" }
            return "Good afternoon"
        case 17..<21:
            if let name = firstName { return "Good evening, \(name)" }
            return "Good evening"
        default:
            return "Late night reads"
        }
    }

    var dateHeader: some View {
        VStack(alignment: .leading, spacing: AppSpacing.xs) {
            Text(greeting)
                .font(AppTypography.subheadline)
                .foregroundColor(BrandColors.textSecondary)

            Text("Daily")
                .font(.system(size: 28, weight: .bold, design: .serif))
                .foregroundColor(BrandColors.textPrimary)

            Text(formattedFullDate)
                .font(AppTypography.caption1)
                .foregroundColor(BrandColors.textTertiary)

            if let subtitle = updatedSubtitle {
                Text(subtitle)
                    .font(AppTypography.caption2)
                    .foregroundColor(BrandColors.textQuaternary)
                    .padding(.top, 2)
            }
        }
    }

    // MARK: - Skeleton Loading

    var skeletonLoading: some View {
        VStack(alignment: .leading, spacing: 0) {
            SkeletonFeaturedCard()

            HairlineDivider()
                .padding(.vertical, AppSpacing.lg)

            ForEach(0..<3, id: \.self) { _ in
                SkeletonCompactRow()
                HairlineDivider()
                    .padding(.leading, AppSpacing.lg)
            }
        }
    }

    // MARK: - Feed content

    var feedContent: some View {
        let articles = viewModel.articles

        return VStack(alignment: .leading, spacing: 0) {
            // Top Story
            if let featured = articles.first {
                sectionLabel("Top Story")
                    .padding(.horizontal, AppSpacing.lg)
                    .padding(.bottom, AppSpacing.md)

                NavigationLink(destination: ArticleDetailView(article: featured)) {
                    FeaturedArticleCard(article: featured, isRead: bookmarks.isRead(featured.id), style: .hero)
                }
                .buttonStyle(PressableButtonStyle())
                .padding(.horizontal, AppSpacing.lg)
                .contextMenu {
                    articleContextMenu(for: featured)
                }
            }

            // For You
            if articles.count > 1 {
                HairlineDivider()
                    .padding(.horizontal, AppSpacing.lg)
                    .padding(.vertical, AppSpacing.lg)

                sectionLabel("For You")
                    .padding(.horizontal, AppSpacing.lg)
                    .padding(.bottom, AppSpacing.sm)

                VStack(spacing: AppSpacing.sm) {
                    ForEach(articles.dropFirst()) { article in
                        NavigationLink(destination: ArticleDetailView(article: article)) {
                            CompactArticleRow(article: article, isRead: bookmarks.isRead(article.id))
                        }
                        .buttonStyle(PressableButtonStyle())
                        .contextMenu {
                            articleContextMenu(for: article)
                        }
                    }
                }
                .padding(.horizontal, AppSpacing.lg)
            }
        }
    }

    @ViewBuilder
    func articleContextMenu(for article: NewsArticle) -> some View {
        Button {
            HapticService.impact(.medium)
            bookmarks.toggleBookmark(article)
        } label: {
            Label(
                bookmarks.isBookmarked(article.id) ? "Remove Bookmark" : "Bookmark",
                systemImage: bookmarks.isBookmarked(article.id) ? "bookmark.slash" : "bookmark"
            )
        }

        if let urlString = article.url, let url = URL(string: urlString) {
            ShareLink(item: url) {
                Label("Share", systemImage: "square.and.arrow.up")
            }
        }

        Button {
            HapticService.impact(.medium)
            NotificationCenter.default.post(name: .discussArticle, object: article)
        } label: {
            Label("Discuss with AI", systemImage: "sparkles")
        }
    }

    func sectionLabel(_ title: String) -> some View {
        Text(title.uppercased())
            .font(AppTypography.sectionTitle)
            .foregroundColor(BrandColors.primary)
            .tracking(0.8)
    }

    func errorBanner(_ message: String) -> some View {
        HStack(spacing: AppSpacing.sm) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 14, weight: .semibold))
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
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundColor(BrandColors.textTertiary)
            }
        }
        .padding(AppSpacing.md)
        .background(BrandColors.warning.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous))
    }

    @ToolbarContentBuilder
    var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .navigationBarLeading) {
            Button(action: { showingProfile = true }) {
                if let photoURL = auth.currentUser?.photo_url,
                   let url = URL(string: photoURL) {
                    AsyncImage(url: url) { phase in
                        switch phase {
                        case .success(let image):
                            image.resizable().aspectRatio(contentMode: .fill)
                        default:
                            Image(systemName: "person.crop.circle.fill")
                                .resizable()
                                .foregroundColor(BrandColors.textTertiary)
                        }
                    }
                    .frame(width: 30, height: 30)
                    .clipShape(Circle())
                } else {
                    Image(systemName: "person.crop.circle.fill")
                        .font(.system(size: 26))
                        .foregroundColor(BrandColors.textTertiary)
                }
            }
        }
    }

    var formattedFullDate: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "EEEE, MMMM d"
        return formatter.string(from: Date())
    }

    var updatedSubtitle: String? {
        guard let date = viewModel.lastFetchDate else { return nil }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return "Updated \(formatter.localizedString(for: date, relativeTo: Date()))"
    }
}

// MARK: - Featured Article Card

struct FeaturedArticleCard: View {
    let article: NewsArticle
    var isRead: Bool = false
    var style: CardStyle = .standard

    enum CardStyle {
        case standard  // 200px image, feedHeroTitle font
        case hero      // 260px image, articleTitle font (28pt)
    }

    private var imageHeight: CGFloat {
        style == .hero ? 260 : 200
    }

    private var titleFont: Font {
        style == .hero ? AppTypography.articleTitle : AppTypography.feedHeroTitle
    }

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm + 2) {
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
            .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))

            // Source + time + reading time + badge
            HStack(spacing: AppSpacing.xs) {
                if !isRead {
                    Circle()
                        .fill(BrandColors.primary)
                        .frame(width: 6, height: 6)
                }

                Text(article.displaySource.uppercased())
                    .font(AppTypography.sourceLabel)
                    .foregroundColor(BrandColors.primary)

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
                .lineSpacing(2)
                .fixedSize(horizontal: false, vertical: true)

            // Summary
            if let summary = article.summary, !summary.isEmpty {
                Text(summary)
                    .font(AppTypography.subheadline)
                    .foregroundColor(BrandColors.textSecondary)
                    .lineLimit(style == .hero ? 3 : 2)
                    .lineSpacing(1)
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

            VStack(spacing: 8) {
                Image(systemName: "newspaper.fill")
                    .font(.system(size: 36, weight: .light))
                    .foregroundColor(Color(.systemGray2))

                Text(article.displaySource.uppercased())
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundColor(Color(.systemGray2))
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

// MARK: - Compact Article Row

struct CompactArticleRow: View {
    let article: NewsArticle
    var isRead: Bool = false

    private var hasImage: Bool {
        article.imageURL != nil && !article.imageURL!.isEmpty
    }

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm) {
            // Image or placeholder
            ZStack(alignment: .bottomLeading) {
                if let imageURL = article.imageURL, let url = URL(string: imageURL) {
                    AsyncImage(url: url) { phase in
                        switch phase {
                        case .success(let image):
                            image.resizable().aspectRatio(contentMode: .fill)
                        default:
                            imagePlaceholder
                        }
                    }
                } else {
                    imagePlaceholder
                }
            }
            .frame(maxWidth: .infinity)
            .frame(height: 160)
            .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous))

            // Source + time + reading time
            HStack(spacing: AppSpacing.xs) {
                if !isRead {
                    Circle()
                        .fill(BrandColors.primary)
                        .frame(width: 6, height: 6)
                }

                Text(article.displaySource.uppercased())
                    .font(.system(size: 11, weight: .bold))
                    .foregroundColor(BrandColors.primary)

                if !article.formattedDate.isEmpty {
                    Circle()
                        .fill(BrandColors.textQuaternary)
                        .frame(width: 2.5, height: 2.5)
                    Text(article.formattedDate)
                        .font(.system(size: 11))
                        .foregroundColor(BrandColors.textTertiary)
                }

                Circle()
                    .fill(BrandColors.textQuaternary)
                    .frame(width: 2.5, height: 2.5)
                Text("\(article.estimatedReadingTime) min")
                    .font(.system(size: 11))
                    .foregroundColor(BrandColors.textTertiary)
            }

            // Title
            Text(article.title)
                .font(AppTypography.feedCardTitle)
                .foregroundColor(BrandColors.textPrimary)
                .opacity(isRead ? 0.6 : 1)
                .lineLimit(3)
                .lineSpacing(1)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(AppSpacing.sm)
        .background(BrandColors.cardBackground)
        .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.card, style: .continuous))
        .padding(.vertical, AppSpacing.xs)
    }

    private var imagePlaceholder: some View {
        ZStack {
            LinearGradient(
                colors: [
                    Color(.systemGray4),
                    Color(.systemGray5)
                ],
                startPoint: .topLeading,
                endPoint: .bottomTrailing
            )

            VStack(spacing: 6) {
                Image(systemName: "newspaper.fill")
                    .font(.system(size: 28, weight: .light))
                    .foregroundColor(Color(.systemGray2))

                Text(article.displaySource.uppercased())
                    .font(.system(size: 10, weight: .semibold))
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
