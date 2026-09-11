import Foundation

/// Server publication identity, independent of reader revision and receipt position.
nonisolated struct DeliveryMetadata: Codable, Equatable, Sendable {
    let version: Int
    let editionID: String
    let sequence: Int64
    let publishedAt: Date
    let validatedAt: Date
    let validUntil: Date
    let readerGeneration: Int
    let readerRevision: Int

    enum CodingKeys: String, CodingKey {
        case version, sequence
        case editionID = "edition_id", publishedAt = "published_at"
        case validatedAt = "validated_at", validUntil = "valid_until"
        case readerGeneration = "reader_generation", readerRevision = "reader_revision"
    }

    var isValid: Bool {
        version == 1 && UUID(uuidString: editionID) != nil && sequence > 0
            && sequence <= 9_007_199_254_740_991 && readerGeneration > 0 && readerRevision > 0
            && publishedAt <= validatedAt && validatedAt < validUntil
            && validUntil.timeIntervalSince(publishedAt) <= 900
    }

    /// A revalidation can advance its timestamp, never the immutable edition or deadline.
    func canReplace(_ previous: DeliveryMetadata?) -> Bool {
        guard isValid else { return false }
        guard let previous else { return true }
        guard sequence >= previous.sequence, readerGeneration >= previous.readerGeneration else { return false }
        if readerGeneration == previous.readerGeneration && readerRevision < previous.readerRevision { return false }
        if sequence == previous.sequence {
            return editionID == previous.editionID && publishedAt == previous.publishedAt
                && validUntil == previous.validUntil && readerGeneration == previous.readerGeneration
                && readerRevision == previous.readerRevision && validatedAt >= previous.validatedAt
        }
        return editionID != previous.editionID
    }
}

/// Pure acceptance checks are shared by the coordinator, persistent store and tests.
nonisolated enum DeliveryValidation {
    static func accepts(_ metadata: DeliveryMetadata?, articles: [NewsArticle], requestID: String?) -> Bool {
        guard articles.count <= 100, Set(articles.map(\.id)).count == articles.count else { return false }
        guard let metadata else { return true } // Legacy: saved/unverified, never fresh authority.
        guard metadata.isValid, requestID == metadata.editionID else { return false }
        let positions = articles.compactMap(\.deliveryPosition)
        guard Set(positions).count == articles.count else { return false }
        return articles.allSatisfy {
            $0.feedRequestID == metadata.editionID && $0.readerGeneration == metadata.readerGeneration
                && $0.readerRevision == metadata.readerRevision && ($0.deliveryPosition ?? -1) >= 0
                && ($0.deliveryPosition ?? 100) < 100
        }
    }

    static func immutableArticlesEqual(_ lhs: [NewsArticle], _ rhs: [NewsArticle]) -> Bool {
        // The server can refresh response validation time, not card content or positions.
        lhs == rhs
    }
}
