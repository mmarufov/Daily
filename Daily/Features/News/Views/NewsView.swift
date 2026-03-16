//
//  NewsView.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI
import UIKit

struct NewsView: View {
    @StateObject private var viewModel = NewsViewModel()
    @ObservedObject private var auth = AuthService.shared
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
                        emptyState
                            .padding(.horizontal, AppSpacing.lg)
                            .padding(.top, AppSpacing.xxl)
                    } else if viewModel.isLoading && viewModel.articles.isEmpty {
                        loadingState
                            .padding(.top, AppSpacing.xxl)
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
    var dateHeader: some View {
        VStack(alignment: .leading, spacing: AppSpacing.xs) {
            Text("Daily")
                .font(.system(size: 28, weight: .bold, design: .serif))
                .foregroundColor(BrandColors.textPrimary)

            Text(formattedFullDate)
                .font(AppTypography.subheadline)
                .foregroundColor(BrandColors.textSecondary)

            if let subtitle = updatedSubtitle {
                Text(subtitle)
                    .font(AppTypography.caption1)
                    .foregroundColor(BrandColors.textTertiary)
                    .padding(.top, 2)
            }
        }
    }

    // MARK: - Feed content

    var feedContent: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Top Story
            if let featured = viewModel.articles.first {
                sectionLabel("Top Story")
                    .padding(.horizontal, AppSpacing.lg)
                    .padding(.bottom, AppSpacing.md)

                NavigationLink(destination: ArticleDetailView(article: featured)) {
                    FeaturedArticleCard(article: featured)
                }
                .buttonStyle(.plain)
                .padding(.horizontal, AppSpacing.lg)
            }

            // For You
            if viewModel.articles.count > 1 {
                HairlineDivider()
                    .padding(.horizontal, AppSpacing.lg)
                    .padding(.vertical, AppSpacing.lg)

                sectionLabel("For You")
                    .padding(.horizontal, AppSpacing.lg)
                    .padding(.bottom, AppSpacing.sm)

                VStack(spacing: 0) {
                    ForEach(Array(viewModel.articles.dropFirst().enumerated()), id: \.element.id) { index, article in
                        NavigationLink(destination: ArticleDetailView(article: article)) {
                            CompactArticleRow(article: article)
                        }
                        .buttonStyle(.plain)

                        if index < viewModel.articles.count - 2 {
                            HairlineDivider()
                                .padding(.leading, AppSpacing.lg)
                        }
                    }
                }
                .padding(.horizontal, AppSpacing.lg)
            }
        }
    }

    func sectionLabel(_ title: String) -> some View {
        Text(title.uppercased())
            .font(AppTypography.sectionTitle)
            .foregroundColor(BrandColors.primary)
            .tracking(0.8)
    }

    var emptyState: some View {
        VStack(spacing: AppSpacing.md) {
            Image(systemName: "newspaper")
                .font(.system(size: 36, weight: .ultraLight))
                .foregroundColor(BrandColors.textTertiary)

            VStack(spacing: AppSpacing.xs) {
                Text("No articles yet")
                    .font(AppTypography.headline)
                    .foregroundColor(BrandColors.textPrimary)

                Text(viewModel.errorMessage ?? "Pull down to refresh your feed.")
                    .font(AppTypography.subheadline)
                    .foregroundColor(viewModel.errorMessage == nil ? BrandColors.textSecondary : BrandColors.error)
                    .multilineTextAlignment(.center)
            }
        }
        .frame(maxWidth: .infinity)
    }

    var loadingState: some View {
        VStack(spacing: AppSpacing.md) {
            ProgressView()
                .scaleEffect(1.1)

            Text("Loading your feed...")
                .font(AppTypography.subheadline)
                .foregroundColor(BrandColors.textSecondary)
        }
        .frame(maxWidth: .infinity)
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
                let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                impactFeedback.impactOccurred()
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

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm + 2) {
            // Image
            if let imageURL = article.imageURL, let url = URL(string: imageURL) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image.resizable().aspectRatio(contentMode: .fill)
                    default:
                        Rectangle()
                            .fill(Color(.tertiarySystemFill))
                    }
                }
                .frame(maxWidth: .infinity)
                .frame(height: 200)
                .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
            }

            // Source + time
            HStack(spacing: AppSpacing.xs) {
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
            }

            // Headline
            Text(article.title)
                .font(AppTypography.feedHeroTitle)
                .foregroundColor(BrandColors.textPrimary)
                .lineLimit(3)
                .lineSpacing(2)
                .fixedSize(horizontal: false, vertical: true)

            // Summary
            if let summary = article.summary, !summary.isEmpty {
                Text(summary)
                    .font(AppTypography.subheadline)
                    .foregroundColor(BrandColors.textSecondary)
                    .lineLimit(2)
                    .lineSpacing(1)
            }
        }
    }
}

// MARK: - Compact Article Row

struct CompactArticleRow: View {
    let article: NewsArticle

    var body: some View {
        HStack(alignment: .top, spacing: AppSpacing.md) {
            // Text content
            VStack(alignment: .leading, spacing: AppSpacing.xs + 2) {
                HStack(spacing: AppSpacing.xs) {
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
                }

                Text(article.title)
                    .font(AppTypography.feedCardTitle)
                    .foregroundColor(BrandColors.textPrimary)
                    .lineLimit(3)
                    .lineSpacing(1)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 0)

            // Thumbnail
            if let imageURL = article.imageURL, let url = URL(string: imageURL) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image.resizable().aspectRatio(contentMode: .fill)
                    default:
                        Rectangle()
                            .fill(Color(.tertiarySystemFill))
                    }
                }
                .frame(width: 75, height: 75)
                .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.small, style: .continuous))
            }
        }
        .padding(.vertical, AppSpacing.md)
    }
}

#Preview {
    NewsView()
}
