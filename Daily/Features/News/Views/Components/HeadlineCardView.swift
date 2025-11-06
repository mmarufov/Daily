//
//  HeadlineCardView.swift
//  Daily
//
//  Created by Muhammadjon on 11/4/25.
//

import SwiftUI

struct HeadlineCardView: View {
    let article: NewsArticle
    
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Image
            if let imageURL = article.imageURL, let url = URL(string: imageURL) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .empty:
                        Rectangle()
                            .fill(
                                LinearGradient(
                                    colors: [Color.blue.opacity(0.4), Color.purple.opacity(0.4)],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                            .frame(height: 180)
                            .overlay {
                                ProgressView()
                            }
                    case .success(let image):
                        image
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                    case .failure:
                        Rectangle()
                            .fill(
                                LinearGradient(
                                    colors: [Color.blue.opacity(0.4), Color.purple.opacity(0.4)],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                            .frame(height: 180)
                            .overlay {
                                Image(systemName: "photo")
                                    .foregroundColor(.white.opacity(0.7))
                                    .font(.title2)
                            }
                    @unknown default:
                        EmptyView()
                    }
                }
                .frame(height: 180)
                .clipped()
            } else {
                // Placeholder when no image
                Rectangle()
                    .fill(
                        LinearGradient(
                            colors: [Color.blue.opacity(0.5), Color.purple.opacity(0.5)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(height: 180)
                    .overlay {
                        Image(systemName: "newspaper.fill")
                            .font(.system(size: 50))
                            .foregroundColor(.white.opacity(0.8))
                    }
            }
            
            // Content
            VStack(alignment: .leading, spacing: 8) {
                // Source and Date
                HStack(spacing: 6) {
                    Text(article.displaySource)
                        .font(.caption)
                        .fontWeight(.semibold)
                        .foregroundColor(.secondary)
                    
                    if !article.formattedDate.isEmpty {
                        Text("•")
                            .font(.caption)
                            .foregroundColor(.secondary)
                        
                        Text(article.formattedDate)
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
                
                // Title
                Text(article.title)
                    .font(.headline)
                    .fontWeight(.bold)
                    .foregroundColor(.primary)
                    .lineLimit(3)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
                
                // Summary (optional, shown if available)
                if let summary = article.summary, !summary.isEmpty {
                    Text(summary)
                        .font(.caption)
                        .foregroundColor(.secondary)
                        .lineLimit(2)
                }
            }
            .padding(12)
        }
        .frame(width: 300)
        .background(Color(.systemBackground))
        .cornerRadius(16)
        .shadow(color: Color.black.opacity(0.15), radius: 10, x: 0, y: 4)
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

