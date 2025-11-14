//
//  HeadlineCardView.swift
//  Daily
//
//  Created by Muhammadjon on 11/4/25.
//

import SwiftUI

struct HeadlineCardView: View {
    let article: NewsArticle
    var onTap: () -> Void = {}
    
    var body: some View {
        Button(action: {
            onTap()
        }) {
            VStack(alignment: .leading, spacing: 0) {
            // Image
            if let imageURL = article.imageURL, let url = URL(string: imageURL) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .empty:
                        Rectangle()
                            .fill(AppGradients.primary)
                            .frame(height: 200)
                            .overlay {
                                ProgressView()
                                    .tint(.white)
                            }
                    case .success(let image):
                        image
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                    case .failure:
                        Rectangle()
                            .fill(AppGradients.primary)
                            .frame(height: 200)
                            .overlay {
                                Image(systemName: "photo")
                                    .font(.system(size: 28, weight: .medium))
                                    .foregroundColor(.white.opacity(0.8))
                            }
                    @unknown default:
                        EmptyView()
                    }
                }
                .frame(height: 200)
                .clipped()
            } else {
                // Placeholder when no image
                Rectangle()
                    .fill(AppGradients.primary)
                    .frame(height: 200)
                    .overlay {
                        Image(systemName: "newspaper.fill")
                            .font(.system(size: 52, weight: .bold))
                            .foregroundColor(.white.opacity(0.9))
                    }
            }
            
                // Content
                VStack(alignment: .leading, spacing: AppSpacing.sm) {
                    // Source and Date
                    HStack(spacing: AppSpacing.sm) {
                        HStack(spacing: AppSpacing.xs) {
                            Circle()
                                .fill(BrandColors.primary)
                                .frame(width: 5, height: 5)
                            
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
                    
                    // Summary (optional, shown if available)
                    if let summary = article.summary, !summary.isEmpty {
                        Text(summary)
                            .font(AppTypography.bodySmall)
                            .foregroundColor(BrandColors.textSecondary)
                            .lineLimit(2)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(AppSpacing.md)
            }
            .frame(width: 320)
            .background(BrandColors.cardBackground)
            .cornerRadius(AppCornerRadius.large)
            .overlay(
                RoundedRectangle(cornerRadius: AppCornerRadius.large)
                    .stroke(BrandColors.primary.opacity(0.15), lineWidth: 1.5)
            )
            .shadow(
                color: AppShadows.medium.color,
                radius: AppShadows.medium.radius,
                x: AppShadows.medium.x,
                y: AppShadows.medium.y
            )
        }
        .buttonStyle(.plain)
    }
}

#Preview {
    ScrollView(.horizontal) {
        HStack {
            HeadlineCardView(
                article: NewsArticle(
                    id: "1",
                    title: "Breaking: Major Tech Announcement Changes Everything",
                    summary: "This is a sample summary of the headline that provides context and preview of the breaking news.",
                    content: nil,
                    author: "Tech Reporter",
                    source: "Tech News",
                    imageURL: nil,
                    publishedAt: Date(),
                    category: "Technology",
                    url: nil
                )
            )
            HeadlineCardView(
                article: NewsArticle(
                    id: "2",
                    title: "Another Important Headline Story",
                    summary: "Short summary here.",
                    content: nil,
                    author: "News Reporter",
                    source: "Daily News",
                    imageURL: nil,
                    publishedAt: Date().addingTimeInterval(-3600),
                    category: "General",
                    url: nil
                )
            )
        }
        .padding()
    }
    .background(Color(.systemGroupedBackground))
}

