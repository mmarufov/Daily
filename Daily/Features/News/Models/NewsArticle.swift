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
}

