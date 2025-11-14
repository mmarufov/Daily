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
        Group {
            if isLoadingFullContent && fullArticle == nil {
                // Show only loading indicator while loading
                VStack {
                    Spacer()
                    ProgressView()
                        .scaleEffect(1.5)
                    Spacer()
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(BrandColors.background.ignoresSafeArea())
            } else if let error = loadErrorMessage, fullArticle == nil {
                // Show error if loading failed
                VStack {
                    Spacer()
                    Text(error)
                        .font(AppTypography.footnote)
                        .foregroundColor(BrandColors.error)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, AppSpacing.xxl)
                    Spacer()
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(BrandColors.background.ignoresSafeArea())
            } else {
                // Show article content after it's loaded
                ScrollView {
                    VStack(alignment: .leading, spacing: AppSpacing.lg) {
                        // Title at the top, using the loaded title
                        if let full = fullArticle {
                            Text(full.title)
                                .font(AppTypography.articleTitle)
                                .foregroundColor(BrandColors.textPrimary)
                                .multilineTextAlignment(.leading)
                                .fixedSize(horizontal: false, vertical: true)
                                .padding(.horizontal, AppSpacing.xxl)
                            
                            // Article image directly under the title
                            headerImage
                            
                            VStack(alignment: .leading, spacing: AppSpacing.md) {
                                // Source, category & date
                                VStack(alignment: .leading, spacing: AppSpacing.xs) {
                                    HStack(spacing: AppSpacing.xs) {
                                        Text(full.displaySource.uppercased())
                                            .font(AppTypography.caption2)
                                            .fontWeight(.semibold)
                                            .foregroundColor(BrandColors.primary)
                                        
                                        if let category = full.category, !category.isEmpty {
                                            Text("•")
                                                .font(AppTypography.caption2)
                                                .foregroundColor(BrandColors.textTertiary)
                                            
                                            Text(category)
                                                .font(AppTypography.caption2)
                                                .foregroundColor(BrandColors.textSecondary)
                                        }
                                    }
                                    
                                    if !full.formattedDate.isEmpty {
                                        Text(full.formattedDate)
                                            .font(AppTypography.caption1)
                                            .foregroundColor(BrandColors.textSecondary)
                                    }
                                }
                                
                                // Author – only after full article is loaded
                                if let author = full.author,
                                   !author.isEmpty {
                                    Text("By \(author)")
                                        .font(AppTypography.subheadline)
                                        .foregroundColor(BrandColors.textSecondary)
                                }
                                
                                // Summary callout – only from full article / AI extraction
                                if let summary = full.summary,
                                   !summary.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                                    Text(summary.trimmingCharacters(in: .whitespacesAndNewlines))
                                        .font(AppTypography.callout)
                                        .foregroundColor(BrandColors.textPrimary)
                                        .fixedSize(horizontal: false, vertical: true)
                                        .padding(.all, AppSpacing.md)
                                        .background(BrandColors.secondaryBackground)
                                        .cornerRadius(AppCornerRadius.medium)
                                }
                                
                                // Full content (cleaned and nicely formatted) – ONLY from fullArticle.
                                if let content = full.content,
                                   !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                                    VStack(alignment: .leading, spacing: AppSpacing.md) {
                                        ForEach(contentParagraphs(from: content), id: \.self) { paragraph in
                                            Text(paragraph)
                                                .font(AppTypography.articleBody)
                                                .foregroundColor(BrandColors.textPrimary)
                                                .multilineTextAlignment(.leading)
                                                .fixedSize(horizontal: false, vertical: true)
                                                .lineSpacing(4)
                                        }
                                    }
                                    .padding(.top, AppSpacing.md)
                                }
                                
                                // External link
                                if let urlString = full.url,
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
                            .padding(.horizontal, AppSpacing.xxl)
                            .padding(.bottom, AppSpacing.xl)
                        }
                    }
                    .padding(.top, AppSpacing.sm)
                }
                .background(BrandColors.background.ignoresSafeArea())
            }
        }
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await loadFullArticleIfNeeded()
        }
    }
    
    // MARK: - Subviews
    
    private var headerImage: some View {
        Group {
            let imageURLToUse = fullArticle?.imageURL ?? article.imageURL
            if let imageURL = imageURLToUse,
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


