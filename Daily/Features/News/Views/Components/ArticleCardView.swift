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
            // Image
            if let imageURL = article.imageURL, let url = URL(string: imageURL) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .empty:
                        Rectangle()
                            .fill(BrandColors.secondaryBackground)
                            .frame(height: 220)
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
                            .fill(AppGradients.card)
                            .frame(height: 220)
                            .overlay {
                                Image(systemName: "photo")
                                    .font(.system(size: 32, weight: .medium))
                                    .foregroundColor(BrandColors.textSecondary)
                            }
                    @unknown default:
                        EmptyView()
                    }
                }
                .frame(height: 220)
                .clipped()
            } else {
                // Placeholder when no image
                Rectangle()
                    .fill(AppGradients.primary)
                    .frame(height: 220)
                    .overlay {
                        Image(systemName: "newspaper.fill")
                            .font(.system(size: 48, weight: .bold))
                            .foregroundColor(.white.opacity(0.8))
                    }
            }
            
            // Content
            VStack(alignment: .leading, spacing: AppSpacing.sm) {
                // Source and Date
                HStack(spacing: AppSpacing.sm) {
                    HStack(spacing: AppSpacing.xs) {
                        Circle()
                            .fill(BrandColors.primary)
                            .frame(width: 6, height: 6)
                        
                        Text(article.displaySource)
                            .font(AppTypography.labelSmall)
                            .fontWeight(.semibold)
                            .foregroundColor(BrandColors.textSecondary)
                    }
                    
                    if !article.formattedDate.isEmpty {
                        Text("•")
                            .font(AppTypography.labelSmall)
                            .foregroundColor(BrandColors.textTertiary)
                        
                        Text(article.formattedDate)
                            .font(AppTypography.labelSmall)
                            .foregroundColor(BrandColors.textSecondary)
                    }
                }
                
                // Title
                Text(article.title)
                    .font(AppTypography.headlineMedium)
                    .fontWeight(.bold)
                    .foregroundColor(BrandColors.textPrimary)
                    .lineLimit(3)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
                
                // Summary
                if let summary = article.summary, !summary.isEmpty {
                    Text(summary)
                        .font(AppTypography.bodyMedium)
                        .foregroundColor(BrandColors.textSecondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .padding(AppSpacing.md)
        }
        .background(BrandColors.cardBackground)
        .cornerRadius(AppCornerRadius.medium)
        .overlay(
            RoundedRectangle(cornerRadius: AppCornerRadius.medium)
                .stroke(BrandColors.primary.opacity(0.1), lineWidth: 1)
        )
        .shadow(
            color: AppShadows.medium.color,
            radius: AppShadows.medium.radius,
            x: AppShadows.medium.x,
            y: AppShadows.medium.y
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

