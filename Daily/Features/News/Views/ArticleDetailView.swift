//
//  ArticleDetailView.swift
//  Daily
//
//  Created by AI on 11/13/25.
//

import SwiftUI

struct ArticleDetailView: View {
    let article: NewsArticle
    
    @State private var fullArticle: NewsArticle?
    @State private var isLoadingFullContent = false
    @State private var loadErrorMessage: String?
    
    var body: some View {
        ZStack {
            AppleBackgroundView()
            
            Group {
                if isLoadingFullContent && fullArticle == nil {
                    VStack {
                        ProgressView()
                            .scaleEffect(1.5)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if let error = loadErrorMessage, fullArticle == nil {
                    VStack {
                        Text(error)
                            .font(AppTypography.footnote)
                            .foregroundColor(BrandColors.error)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, AppSpacing.xxl)
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 0) {
                            if let full = fullArticle {
                                HStack {
                                    Spacer()
                                    Text(full.title)
                                        .font(AppTypography.articleTitle)
                                        .foregroundColor(BrandColors.textPrimary)
                                        .multilineTextAlignment(.leading)
                                        .fixedSize(horizontal: false, vertical: true)
                                        .frame(maxWidth: 700)
                                    Spacer()
                                }
                                .padding(.horizontal, AppSpacing.xxl)
                                .padding(.top, AppSpacing.sm)
                                
                                headerImage
                                
                                HStack {
                                    Spacer()
                                    VStack(alignment: .leading, spacing: AppSpacing.md) {
                                        metaSection(for: full)
                                        summarySection(for: full)
                                        contentSection(for: full)
                                        externalLink(for: full)
                                    }
                                    .frame(maxWidth: 700)
                                    Spacer()
                                }
                                .padding(.horizontal, AppSpacing.xxl)
                                .padding(.bottom, AppSpacing.xl)
                            }
                        }
                    }
                }
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.ultraThinMaterial, for: .navigationBar)
        .toolbarBackground(.visible, for: .navigationBar)
        .task {
            await loadFullArticleIfNeeded()
        }
    }
    
    // MARK: - Subviews
    
    @ViewBuilder
    private var headerImage: some View {
        Group {
            if let imageURL = fullArticle?.imageURL ?? article.imageURL,
               let url = URL(string: imageURL) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .empty:
                        Rectangle()
                            .fill(AppGradients.subtle)
                            .frame(height: 260)
                            .overlay {
                                ProgressView()
                                    .tint(.white)
                            }
                    case .success(let image):
                        image
                            .resizable()
                            .scaledToFill()
                            .frame(maxWidth: .infinity)
                    case .failure:
                        placeholderHeader
                    @unknown default:
                        placeholderHeader
                    }
                }
                .frame(height: 260)
                .clipped()
            } else {
                placeholderHeader
            }
        }
        .overlay(
            LinearGradient(
                colors: [Color.black.opacity(0.35), Color.clear],
                startPoint: .bottom,
                endPoint: .top
            )
            .frame(height: 120),
            alignment: .bottom
        )
    }
    
    private var placeholderHeader: some View {
        Rectangle()
            .fill(AppGradients.subtle)
            .frame(height: 260)
            .overlay {
                Image(systemName: "newspaper.fill")
                    .font(.system(size: 54, weight: .bold))
                    .foregroundColor(.white.opacity(0.9))
            }
    }
    
    // MARK: - Helpers
    
    private func loadFullArticleIfNeeded() async {
        // Only attempt if we have a source URL and haven't loaded yet
        guard !isLoadingFullContent,
              fullArticle == nil,
              let urlString = article.url,
              !urlString.isEmpty else {
            return
        }
        
        // Check if article already has full content (more than 500 chars)
        // If so, use it directly without fetching
        if let existingContent = article.content,
           existingContent.count > 500 {
            // Article already has full content, use it
            fullArticle = article
            return
        }
        
        guard let token = AuthService.shared.getAccessToken() else {
            return
        }
        
        isLoadingFullContent = true
        loadErrorMessage = nil
        
        do {
            let fetched = try await BackendService.shared.fetchFullArticle(from: urlString, accessToken: token)
            // Merge: prefer fetched fields but keep original id/url/category if needed
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
            )
            isLoadingFullContent = false
        } catch {
            loadErrorMessage = error.localizedDescription
            isLoadingFullContent = false
        }
    }
    
    /// Clean up raw content coming from NewsAPI:
    /// - Removes the trailing "[+1234 chars]" marker
    /// - Normalizes whitespace so it wraps nicely in the UI
    private func cleanedContent(from content: String) -> String {
        var text = content.trimmingCharacters(in: .whitespacesAndNewlines)
        
        // Remove the typical NewsAPI suffix like: " [+2095 chars]"
        if let range = text.range(of: #"\s*\[\+\d+\s+chars\]"#, options: .regularExpression) {
            text.removeSubrange(range)
        }
        
        return text
    }
    
    private func contentParagraphs(from content: String) -> [String] {
        let normalized = cleanedContent(from: content)
        
        let rawParagraphs = normalized
            .replacingOccurrences(of: "\\n", with: "\n")
            .components(separatedBy: CharacterSet.newlines.union(.init(charactersIn: "\n\n")))
        
        return rawParagraphs
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
    }
    
    @ViewBuilder
    private func metaSection(for article: NewsArticle) -> some View {
        VStack(alignment: .leading, spacing: AppSpacing.xs) {
            HStack(spacing: AppSpacing.xs) {
                Text(article.displaySource.uppercased())
                    .font(AppTypography.caption2)
                    .fontWeight(.semibold)
                    .foregroundColor(BrandColors.primary)
                
                if let category = article.category, !category.isEmpty {
                    Text("•")
                        .font(AppTypography.caption2)
                        .foregroundColor(BrandColors.textTertiary)
                    
                    Text(category)
                        .font(AppTypography.caption2)
                        .foregroundColor(BrandColors.textSecondary)
                }
            }
            
            if !article.formattedDate.isEmpty {
                Text(article.formattedDate)
                    .font(AppTypography.caption1)
                    .foregroundColor(BrandColors.textSecondary)
            }
            
            if let author = article.author, !author.isEmpty {
                Text("By \(author)")
                    .font(AppTypography.subheadline)
                    .foregroundColor(BrandColors.textSecondary)
                    .padding(.top, AppSpacing.xs)
            }
        }
    }
    
    @ViewBuilder
    private func summarySection(for article: NewsArticle) -> some View {
        if let summary = article.summary, !summary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            Text(summary.trimmingCharacters(in: .whitespacesAndNewlines))
                .font(AppTypography.callout)
                .foregroundColor(BrandColors.textPrimary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.all, AppSpacing.md)
                .glassCard(cornerRadius: AppCornerRadius.large)
        }
    }
    
    @ViewBuilder
    private func contentSection(for article: NewsArticle) -> some View {
        if let content = article.content,
           !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            VStack(alignment: .leading, spacing: AppSpacing.md) {
                ForEach(contentParagraphs(from: content), id: \.self) { paragraph in
                    Text(paragraph)
                        .font(AppTypography.articleBody)
                        .foregroundColor(BrandColors.textPrimary)
                        .multilineTextAlignment(.leading)
                        .lineSpacing(4)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(.top, AppSpacing.md)
        }
    }
    
    @ViewBuilder
    private func externalLink(for article: NewsArticle) -> some View {
        if let urlString = article.url,
           let url = URL(string: urlString) {
            Link(destination: url) {
                HStack(spacing: AppSpacing.sm) {
                    Image(systemName: "safari.fill")
                        .font(.system(size: 16, weight: .medium))
                    Text("Open Original Article")
                        .font(AppTypography.labelMedium)
                }
                .foregroundColor(.white)
                .padding(.horizontal, AppSpacing.lg)
                .padding(.vertical, AppSpacing.sm)
                .background(BrandColors.primary)
                .cornerRadius(AppCornerRadius.button)
            }
            .padding(.top, AppSpacing.lg)
        }
    }
}

#Preview {
    NavigationView {
        ArticleDetailView(
            article: NewsArticle(
                id: "1",
                title: "Sample Article Title for Detail View",
                summary: "This is a concise summary of the article to give the reader context before diving into the full story.",
                content: "This is the first paragraph of the article body, written in a human-friendly, readable way.\n\nThis is another paragraph that continues the story with more details and background information.",
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


