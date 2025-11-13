//
//  ArticleCardView.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI

struct ArticleCardView: View {
    let article: NewsArticle
    
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Image with Apple-style rounded corners
            if let imageURL = article.imageURL, let url = URL(string: imageURL) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .empty:
                        Rectangle()
                            .fill(BrandColors.secondaryBackground)
                            .frame(height: 200)
                            .overlay {
                                ProgressView()
                                    .tint(BrandColors.primary)
                            }
                    case .success(let image):
                        image
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                    case .failure:
                        Rectangle()
                            .fill(BrandColors.tertiaryBackground)
                            .frame(height: 200)
                            .overlay {
                                Image(systemName: "photo")
                                    .font(.system(size: 28, weight: .light))
                                    .foregroundColor(BrandColors.textTertiary)
                            }
                    @unknown default:
                        EmptyView()
                    }
                }
                .frame(height: 200)
                .clipped()
            } else {
                // Placeholder when no image - Apple style
                Rectangle()
                    .fill(BrandColors.tertiaryBackground)
                    .frame(height: 200)
                    .overlay {
                        Image(systemName: "newspaper")
                            .font(.system(size: 40, weight: .ultraLight))
                            .foregroundColor(BrandColors.textTertiary)
                    }
            }
            
            // Content - Apple style spacing
            VStack(alignment: .leading, spacing: AppSpacing.sm) {
                // Source and Date - Refined typography
                HStack(spacing: AppSpacing.xs) {
                    Text(article.displaySource)
                        .font(AppTypography.caption1)
                        .fontWeight(.medium)
                        .foregroundColor(BrandColors.textSecondary)
                    
                    if !article.formattedDate.isEmpty {
                        Text("·")
                            .font(AppTypography.caption1)
                            .foregroundColor(BrandColors.textTertiary)
                        
                        Text(article.formattedDate)
                            .font(AppTypography.caption1)
                            .foregroundColor(BrandColors.textTertiary)
                    }
                }
                .padding(.bottom, AppSpacing.xs)
                
                // Title - Apple headline style
                Text(article.title)
                    .font(AppTypography.headline)
                    .fontWeight(.semibold)
                    .foregroundColor(BrandColors.textPrimary)
                    .lineLimit(3)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.bottom, AppSpacing.xs)
                
                // Summary - Apple body style
                if let summary = article.summary, !summary.isEmpty {
                    Text(summary)
                        .font(AppTypography.subheadline)
                        .foregroundColor(BrandColors.textSecondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(AppSpacing.md)
        }
        .background(BrandColors.cardBackground)
        .cornerRadius(AppCornerRadius.card)
        .shadow(
            color: AppShadows.card.color,
            radius: AppShadows.card.radius,
            x: AppShadows.card.x,
            y: AppShadows.card.y
        )
    }
}

#Preview {
    ArticleCardView(
        article: NewsArticle(
            id: "1",
            title: "Sample Article Title",
            summary: "This is a sample summary of the article that provides context and preview.",
            content: nil,
            author: "John Doe",
            source: "Tech News",
            imageURL: nil,
            publishedAt: Date(),
            category: "Technology",
            url: nil
        )
    )
    .padding()
}

