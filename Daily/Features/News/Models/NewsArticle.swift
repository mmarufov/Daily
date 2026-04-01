//
//  NewsArticle.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import Foundation

struct NewsArticle: Identifiable, Codable, Equatable {
    let id: String
    let title: String
    let summary: String?
    let content: String?
    let author: String?
    let source: String?
    let imageURL: String?
    let publishedAt: Date?
    let category: String?
    let url: String?
    var relevanceScore: Double? = nil
    var relevant: Bool? = nil
    var relevanceReason: String? = nil
    var feedRole: String? = nil
    var whyThisStory: String? = nil
    var whyNow: String? = nil
    var matchedProfileSignals: [String]? = nil
    var clusterID: String? = nil
    var importanceScore: Double? = nil

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case summary
        case content
        case author
        case source
        case imageURL = "image_url"
        case publishedAt = "published_at"
        case category
        case url
        case relevanceScore = "relevance_score"
        case relevant
        case relevanceReason = "relevance_reason"
        case feedRole = "feed_role"
        case whyThisStory = "why_this_story"
        case whyNow = "why_now"
        case matchedProfileSignals = "matched_profile_signals"
        case clusterID = "cluster_id"
        case importanceScore = "importance_score"
    }
    
    // Computed property for formatted date
    var formattedDate: String {
        guard let date = publishedAt else { return "" }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter.localizedString(for: date, relativeTo: Date())
    }
    
    // Computed property for display source
    var displaySource: String {
        source ?? author ?? "Daily"
    }

    var estimatedReadingTime: Int {
        let wordCount = [title, summary, content]
            .compactMap { $0 }
            .joined(separator: " ")
            .split(separator: " ")
            .count
        return max(1, wordCount / 238)
    }
}
