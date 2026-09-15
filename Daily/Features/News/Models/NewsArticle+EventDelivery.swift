import Foundation

nonisolated extension CodingUserInfoKey {
    /// Tests/replay may inject a clock; ordinary API/cache decoding uses wall time.
    static let eventDeliveryValidationTime = CodingUserInfoKey(rawValue: "daily.eventDeliveryValidationTime")!
}

/// Optional S4 v1 metadata. Structural validity is not server authorization or
/// semantic truth; use an explicit current time every time priority is consumed.
nonisolated struct ArticleEventDelivery: Codable, Hashable, Sendable {
    let eventID: String
    let eventVersion: Int
    let assessmentID: String
    let assessmentVersion: String
    let developmentID: String
    let developmentVersion: Int
    let tier: String
    let asOf: Date
    let validUntil: Date
    private let asOfWire: String
    private let validUntilWire: String

    enum CodingKeys: String, CodingKey, CaseIterable {
        case eventID = "event_id"
        case eventVersion = "event_version"
        case assessmentID = "assessment_id"
        case assessmentVersion = "assessment_version"
        case developmentID = "development_id"
        case developmentVersion = "development_version"
        case tier
        case asOf = "as_of"
        case validUntil = "valid_until"
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        eventID = try values.decode(String.self, forKey: .eventID)
        eventVersion = try values.decode(Int.self, forKey: .eventVersion)
        assessmentID = try values.decode(String.self, forKey: .assessmentID)
        assessmentVersion = try values.decode(String.self, forKey: .assessmentVersion)
        developmentID = try values.decode(String.self, forKey: .developmentID)
        developmentVersion = try values.decode(Int.self, forKey: .developmentVersion)
        tier = try values.decode(String.self, forKey: .tier)
        asOfWire = try values.decode(String.self, forKey: .asOf)
        validUntilWire = try values.decode(String.self, forKey: .validUntil)
        guard [eventID, assessmentID, developmentID].allSatisfy(Self.validIdentity),
              eventVersion > 0, developmentVersion > 0,
              assessmentVersion.range(of: #"^[a-f0-9]{64}$"#, options: .regularExpression) != nil,
              tier == "world_critical",
              let start = Self.wireDate(asOfWire), let expiry = Self.wireDate(validUntilWire),
              expiry > start, expiry.timeIntervalSince(start) <= 86_400 else {
            throw DecodingError.dataCorrupted(.init(codingPath: decoder.codingPath,
                debugDescription: "Invalid event delivery metadata"))
        }
        asOf = start
        validUntil = expiry
    }

    func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(eventID, forKey: .eventID)
        try values.encode(eventVersion, forKey: .eventVersion)
        try values.encode(assessmentID, forKey: .assessmentID)
        try values.encode(assessmentVersion, forKey: .assessmentVersion)
        try values.encode(developmentID, forKey: .developmentID)
        try values.encode(developmentVersion, forKey: .developmentVersion)
        try values.encode(tier, forKey: .tier)
        // Preserve exact server precision; reformatting must never extend expiry.
        try values.encode(asOfWire, forKey: .asOf)
        try values.encode(validUntilWire, forKey: .validUntil)
    }

    func isCurrent(at now: Date) -> Bool {
        now.timeIntervalSinceReferenceDate.isFinite && asOf <= now && now < validUntil
    }

    nonisolated private static func validIdentity(_ value: String) -> Bool {
        !value.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && value.unicodeScalars.count <= 200
            && !value.unicodeScalars.contains(where: CharacterSet.controlCharacters.contains)
    }

    nonisolated private static func wireDate(_ value: String) -> Date? {
        guard value.range(of: #"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$"#,
                          options: .regularExpression) != nil else { return nil }
        let calendar = DateFormatter()
        calendar.locale = Locale(identifier: "en_US_POSIX")
        calendar.timeZone = TimeZone(secondsFromGMT: 0)
        calendar.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        calendar.isLenient = false
        let prefix = String(value.prefix(19))
        guard let calendarDate = calendar.date(from: prefix), calendar.string(from: calendarDate) == prefix else { return nil }
        // ISO8601DateFormatter truncates microseconds to milliseconds, which
        // can accidentally accept a slightly future assessment. FormatStyle
        // preserves the server's supported fractional precision.
        return try? Date.ISO8601FormatStyle(includingFractionalSeconds: value.contains(".")).parse(value)
    }
}

nonisolated extension NewsArticle {
    /// Optional new metadata must not make the publisher article undecodable.
    /// Keep all previous field decoding semantics; only S4 metadata is lossy.
    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        self.init(id: try values.decode(String.self, forKey: .id),
            title: try values.decode(String.self, forKey: .title),
            summary: try values.decodeIfPresent(String.self, forKey: .summary),
            content: try values.decodeIfPresent(String.self, forKey: .content),
            author: try values.decodeIfPresent(String.self, forKey: .author),
            source: try values.decodeIfPresent(String.self, forKey: .source),
            imageURL: try values.decodeIfPresent(String.self, forKey: .imageURL),
            image: try values.decodeIfPresent(ArticleImage.self, forKey: .image),
            publishedAt: try values.decodeIfPresent(Date.self, forKey: .publishedAt),
            category: try values.decodeIfPresent(String.self, forKey: .category),
            url: try values.decodeIfPresent(String.self, forKey: .url))
        relevanceScore = try values.decodeIfPresent(Double.self, forKey: .relevanceScore)
        relevant = try values.decodeIfPresent(Bool.self, forKey: .relevant)
        relevanceReason = try values.decodeIfPresent(String.self, forKey: .relevanceReason)
        feedRole = try values.decodeIfPresent(String.self, forKey: .feedRole)
        whyThisStory = try values.decodeIfPresent(String.self, forKey: .whyThisStory)
        whyNow = try values.decodeIfPresent(String.self, forKey: .whyNow)
        matchedProfileSignals = try values.decodeIfPresent([String].self, forKey: .matchedProfileSignals)
        clusterID = try values.decodeIfPresent(String.self, forKey: .clusterID)
        importanceScore = try values.decodeIfPresent(Double.self, forKey: .importanceScore)
        bodyExcerpt = try values.decodeIfPresent(String.self, forKey: .bodyExcerpt)
        presentation = try values.decodeIfPresent(ArticlePresentation.self, forKey: .presentation)
        eventDelivery = try? values.decodeIfPresent(ArticleEventDelivery.self, forKey: .eventDelivery)
        readerGeneration = try values.decodeIfPresent(Int.self, forKey: .readerGeneration)
        readerRevision = try values.decodeIfPresent(Int.self, forKey: .readerRevision)
        feedRequestID = try values.decodeIfPresent(String.self, forKey: .feedRequestID)
        deliveryPosition = try values.decodeIfPresent(Int.self, forKey: .deliveryPosition)
        if values.contains(.eventDelivery), !(try values.decodeNil(forKey: .eventDelivery)), eventDelivery == nil {
            feedRole = nil
            whyNow = nil
        }
        let now = (decoder.userInfo[.eventDeliveryValidationTime] as? Date) ?? Date()
        self = removingExpiredEventDelivery(at: now)
    }

    func currentEventDelivery(at now: Date) -> ArticleEventDelivery? {
        guard let eventDelivery, eventDelivery.isCurrent(at: now) else { return nil }
        return eventDelivery
    }

    func removingExpiredEventDelivery(at now: Date) -> NewsArticle {
        guard currentEventDelivery(at: now) == nil else { return self }
        return withoutEventDelivery()
    }

    /// Saved/ordinary article caches never persist a feed's priority decision.
    func withoutEventDelivery() -> NewsArticle {
        var article = self
        if eventDelivery != nil || feedRole == "world_critical" || feedRole == "event_priority" {
            article.feedRole = nil
            article.whyNow = nil
        }
        article.eventDelivery = nil
        return article
    }
}
