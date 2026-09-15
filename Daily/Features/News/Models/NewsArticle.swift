//
//  NewsArticle.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import Foundation
import Darwin

nonisolated struct NewsArticle: Identifiable, Codable, Hashable, Sendable {
    let id: String
    let title: String
    let summary: String?
    let content: String?
    let author: String?
    let source: String?
    let imageURL: String?
    /// Provenance-bearing image metadata from the S2 API. The legacy
    /// `image_url` field is decoded for rolling compatibility but is never
    /// rendered by this client because its origin cannot be established.
    var image: ArticleImage? = nil
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
    /// A feed-safe preview. This is never treated as a complete publisher body.
    var bodyExcerpt: String? = nil
    /// Server-owned reading contract. Absent on older API versions.
    var presentation: ArticlePresentation? = nil
    /// Short-lived feed authorization, never an intrinsic article property.
    var eventDelivery: ArticleEventDelivery? = nil
    var readerGeneration: Int? = nil
    var readerRevision: Int? = nil
    var feedRequestID: String? = nil
    /// Server-assigned position in this immutable edition, never a current UI index.
    var deliveryPosition: Int? = nil

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case summary
        case content
        case author
        case source
        case imageURL = "image_url"
        case image
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
        case bodyExcerpt = "body_excerpt"
        case presentation
        case eventDelivery = "event_delivery"
        case readerGeneration = "reader_generation"
        case readerRevision = "reader_revision"
        case feedRequestID = "feed_request_id"
        case deliveryPosition = "delivery_position"
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
        if let source = source?.trimmingCharacters(in: .whitespacesAndNewlines), !source.isEmpty {
            return source
        }
        if let host = originalSourceURL?.host(percentEncoded: false), !host.isEmpty {
            return host.replacingOccurrences(of: "www.", with: "")
        }
        return "Unknown source"
    }

    var estimatedReadingTime: Int {
        let wordCount = [title, summary, verifiedNativeBody, bodyExcerpt]
            .compactMap { $0 }
            .joined(separator: " ")
            .split(separator: " ")
            .count
        return max(1, wordCount / 238)
    }
}

// MARK: - Reading contract

nonisolated enum ArticleImageOrigin: String, Codable, Hashable, Sendable {
    case publisherFeed = "publisher_feed"
    case publisherPage = "publisher_page"
    case licensedAPI = "licensed_api"
    case aggregatorAPI = "aggregator_api"
    case stock
    case generated
    case legacyUnknown = "legacy_unknown"
    case unsupported

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer().decode(String.self)
        self = Self(rawValue: value) ?? .unsupported
    }

    var isDisplayable: Bool {
        self != .legacyUnknown && self != .unsupported
    }
}

nonisolated struct ArticleImage: Codable, Hashable, Sendable {
    let url: String
    let origin: ArticleImageOrigin
    let sourceURL: String?
    let attribution: String?
    let illustrative: Bool

    enum CodingKeys: String, CodingKey {
        case url
        case origin
        case sourceURL = "source_url"
        case attribution
        case illustrative
    }
}

nonisolated enum ArticlePresentationMode: String, Codable, Hashable, Sendable {
    case nativeFullText = "native_full_text"
    case sourceWeb = "source_web"
    case unavailable

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer().decode(String.self)
        self = Self(rawValue: value) ?? .unavailable
    }
}

nonisolated enum ArticleBodyState: String, Codable, Hashable, Sendable {
    case verifiedFull = "verified_full"
    case partial
    case none

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer().decode(String.self)
        self = Self(rawValue: value) ?? .none
    }
}

nonisolated struct ArticleContentProvenance: Codable, Hashable, Sendable {
    let kind: String?
    let method: String?
    let sourceURL: String?
    let sourceName: String?
    let fetchedAt: Date?
    let contentHash: String?
    let extractorVersion: Int?
    let rightsPolicy: String?
    let completeness: String?
    let confidence: Double?
    let contentVersion: Int?
    let policyVersion: Int?

    enum CodingKeys: String, CodingKey {
        case kind
        case method
        case sourceURL = "source_url"
        case sourceName = "source_name"
        case fetchedAt = "fetched_at"
        case contentHash = "content_hash"
        case extractorVersion = "extractor_version"
        case rightsPolicy = "rights_policy"
        case completeness
        case confidence
        case contentVersion = "content_version"
        case policyVersion = "policy_version"
    }

    init(
        kind: String? = nil,
        method: String? = nil,
        sourceURL: String? = nil,
        sourceName: String? = nil,
        fetchedAt: Date? = nil,
        contentHash: String? = nil,
        extractorVersion: Int? = nil,
        rightsPolicy: String? = nil,
        completeness: String? = nil,
        confidence: Double? = nil,
        contentVersion: Int? = nil,
        policyVersion: Int? = nil
    ) {
        self.kind = kind
        self.method = method
        self.sourceURL = sourceURL
        self.sourceName = sourceName
        self.fetchedAt = fetchedAt
        self.contentHash = contentHash
        self.extractorVersion = extractorVersion
        self.rightsPolicy = rightsPolicy
        self.completeness = completeness
        self.confidence = confidence
        self.contentVersion = contentVersion
        self.policyVersion = policyVersion
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        kind = try? container.decodeIfPresent(String.self, forKey: .kind)
        method = try? container.decodeIfPresent(String.self, forKey: .method)
        sourceURL = try? container.decodeIfPresent(String.self, forKey: .sourceURL)
        sourceName = try? container.decodeIfPresent(String.self, forKey: .sourceName)
        fetchedAt = try? container.decodeIfPresent(Date.self, forKey: .fetchedAt)
        contentHash = try? container.decodeIfPresent(String.self, forKey: .contentHash)
        extractorVersion = try? container.decodeIfPresent(Int.self, forKey: .extractorVersion)
        rightsPolicy = try? container.decodeIfPresent(String.self, forKey: .rightsPolicy)
        completeness = try? container.decodeIfPresent(String.self, forKey: .completeness)
        confidence = try? container.decodeIfPresent(Double.self, forKey: .confidence)
        contentVersion = try? container.decodeIfPresent(Int.self, forKey: .contentVersion)
        policyVersion = try? container.decodeIfPresent(Int.self, forKey: .policyVersion)
    }
}

nonisolated struct ArticlePresentation: Codable, Hashable, Sendable {
    let mode: ArticlePresentationMode
    let originalURL: String?
    let body: String?
    let bodyState: ArticleBodyState
    let accessHint: String?
    let reason: String?
    let provenance: ArticleContentProvenance?
    var offlineValidUntil: Date? = nil
    var validatedAt: Date? = nil

    enum CodingKeys: String, CodingKey {
        case mode
        case originalURL = "original_url"
        case body
        case bodyState = "body_state"
        case accessHint = "access_hint"
        case reason
        case provenance
        case offlineValidUntil = "offline_valid_until"
        case validatedAt = "validated_at"
    }

    init(
        mode: ArticlePresentationMode,
        originalURL: String? = nil,
        body: String? = nil,
        bodyState: ArticleBodyState = .none,
        accessHint: String? = nil,
        reason: String? = nil,
        provenance: ArticleContentProvenance? = nil,
        offlineValidUntil: Date? = nil,
        validatedAt: Date? = nil
    ) {
        self.mode = mode
        self.originalURL = originalURL
        self.body = body
        self.bodyState = bodyState
        self.accessHint = accessHint
        self.reason = reason
        self.provenance = provenance
        self.offlineValidUntil = offlineValidUntil
        self.validatedAt = validatedAt
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        mode = (try? container.decodeIfPresent(ArticlePresentationMode.self, forKey: .mode)) ?? .unavailable
        originalURL = try? container.decodeIfPresent(String.self, forKey: .originalURL)
        body = try? container.decodeIfPresent(String.self, forKey: .body)
        bodyState = (try? container.decodeIfPresent(ArticleBodyState.self, forKey: .bodyState)) ?? .none
        accessHint = try? container.decodeIfPresent(String.self, forKey: .accessHint)
        reason = try? container.decodeIfPresent(String.self, forKey: .reason)
        provenance = try? container.decodeIfPresent(ArticleContentProvenance.self, forKey: .provenance)
        offlineValidUntil = try? container.decodeIfPresent(Date.self, forKey: .offlineValidUntil)
        validatedAt = try? container.decodeIfPresent(Date.self, forKey: .validatedAt)
    }
}

nonisolated enum ArticleReaderRoute: Equatable, Sendable {
    case native
    case source(URL)
    case unavailable
}

nonisolated extension NewsArticle {
    /// Only an explicit server assertion may enable native publisher text.
    var verifiedNativeBody: String? {
        guard presentation?.mode == .nativeFullText,
              presentation?.bodyState == .verifiedFull,
              let provenance = presentation?.provenance,
              ["licensed_api", "publisher_feed", "origin_extract"].contains(provenance.kind),
              provenance.completeness == "complete",
              let rightsPolicy = provenance.rightsPolicy?
                .trimmingCharacters(in: .whitespacesAndNewlines)
                .lowercased(),
              !rightsPolicy.isEmpty,
              !Self.nonExplicitRightsPolicies.contains(rightsPolicy),
              (provenance.contentVersion ?? 0) > 0,
              (provenance.policyVersion ?? 0) > 0,
              let canonicalURL = Self.validSourceURL(presentation?.originalURL),
              let provenanceURL = Self.validSourceURL(provenance.sourceURL),
              Self.provenanceOriginIsBound(
                kind: provenance.kind,
                canonicalURL: canonicalURL,
                provenanceURL: provenanceURL
              ),
              let body = presentation?.body?.trimmingCharacters(in: .whitespacesAndNewlines),
              !body.isEmpty else {
            return nil
        }
        if let retainedLegacyURL = Self.validSourceURL(url),
           !Self.hasSamePublisherOrigin(canonicalURL, retainedLegacyURL) {
            return nil
        }
        return body
    }

    private static let nonExplicitRightsPolicies: Set<String> = [
        "false", "n_a", "no_rights", "none", "not_applicable", "pending",
        "revoked", "unknown", "unreviewed", "unspecified", "unverified"
    ]

    /// Only typed, provenance-bearing image URLs are eligible for rendering.
    /// This deliberately fails closed for old `image_url`-only payloads.
    var displayImageURL: URL? {
        guard let image, image.origin.isDisplayable else { return nil }
        return Self.validSourceURL(image.url)
    }

    var imageIsIllustrative: Bool {
        guard displayImageURL != nil, let image else { return false }
        return image.illustrative || image.origin == .stock || image.origin == .generated
    }

    var originalSourceURL: URL? {
        // Once a typed presentation exists, its canonical destination is
        // authoritative. An older additive `url` field must not repair or
        // silently undo a malformed/withdrawn typed contract.
        if let presentation {
            return Self.validSourceURL(presentation.originalURL)
        }
        return Self.validSourceURL(url)
    }

    var readerRoute: ArticleReaderRoute {
        guard let presentation else {
            return originalSourceURL.map(ArticleReaderRoute.source) ?? .unavailable
        }
        switch presentation.mode {
        case .nativeFullText:
            // `native_full_text` is also the feed's promise that a body may be
            // fetched from the detail endpoint. Feed rows intentionally omit it.
            // A valid canonical origin is mandatory even before that fetch.
            guard originalSourceURL != nil else { return .unavailable }
            return .native
        case .sourceWeb:
            return originalSourceURL.map(ArticleReaderRoute.source) ?? .unavailable
        case .unavailable:
            return .unavailable
        }
    }

    static func validSourceURL(_ rawValue: String?) -> URL? {
        guard let rawValue = rawValue?.trimmingCharacters(in: .whitespacesAndNewlines),
              !rawValue.isEmpty,
              let components = URLComponents(string: rawValue),
              let scheme = components.scheme?.lowercased(),
              scheme == "https" || scheme == "http",
              components.user == nil,
              components.password == nil,
              components.port == nil || components.port == 80 || components.port == 443,
              let host = components.host?.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: ".")),
              !host.isEmpty,
              Self.isSafeSourceHost(host) else {
            return nil
        }
        return components.url
    }

    static func hasSamePublisherOrigin(_ left: URL, _ right: URL) -> Bool {
        normalizedPublisherHost(left) == normalizedPublisherHost(right)
    }

    static func provenanceOriginIsBound(
        kind: String?,
        canonicalURL: URL,
        provenanceURL: URL
    ) -> Bool {
        switch kind {
        case "origin_extract":
            return hasSamePublisherOrigin(canonicalURL, provenanceURL)
        case "publisher_feed", "licensed_api":
            // These acquisition principals can live on a sibling or API host.
            // Their exact identity is reviewed and versioned by backend policy;
            // the client still requires a structurally public provenance URL.
            return true
        default:
            return false
        }
    }

    private static func normalizedPublisherHost(_ url: URL) -> String? {
        guard let host = url.host(percentEncoded: false)?
            .trimmingCharacters(in: CharacterSet(charactersIn: "."))
            .lowercased(),
              !host.isEmpty else {
            return nil
        }
        return host.hasPrefix("www.") ? String(host.dropFirst(4)) : host
    }

    private static func isSafeSourceHost(_ host: String) -> Bool {
        let specialUseSuffixes = [
            "localhost", "local", "localdomain", "internal", "home", "lan",
            "test", "invalid", "example"
        ]
        if specialUseSuffixes.contains(where: { host == $0 || host.hasSuffix(".\($0)") }) {
            return false
        }

        if host.contains(":") {
            let compact = host.replacingOccurrences(of: "[", with: "")
                .replacingOccurrences(of: "]", with: "")
            return isPublicIPv6Literal(compact)
        }

        let rawLabels = host.split(separator: ".", omittingEmptySubsequences: false)
        guard rawLabels.count >= 2,
              rawLabels.allSatisfy({ !$0.isEmpty && $0.count <= 63 }),
              rawLabels.allSatisfy({ !$0.hasPrefix("-") && !$0.hasSuffix("-") }) else {
            // Public publisher hostnames need a registrable-looking dotted
            // name. This also blocks single-label intranet destinations.
            return false
        }

        let isIPv4Like = host.unicodeScalars.allSatisfy {
            CharacterSet.decimalDigits.contains($0) || $0 == "."
        }
        guard isIPv4Like else { return true }

        return isPublicIPv4Literal(rawLabels.map(String.init))
    }

    private static func isPublicIPv4Literal(_ rawOctets: [String]) -> Bool {
        guard rawOctets.count == 4,
              rawOctets.allSatisfy({ !$0.isEmpty && ($0 == "0" || !$0.hasPrefix("0")) }),
              rawOctets.allSatisfy({ $0.unicodeScalars.allSatisfy(CharacterSet.decimalDigits.contains) }),
              rawOctets.compactMap(Int.init).count == 4 else {
            // Reject shorthand, integer, hexadecimal, octal, and malformed
            // spellings that different URL stacks can normalize differently.
            return false
        }

        let octets = rawOctets.compactMap(Int.init)
        guard octets.allSatisfy({ (0...255).contains($0) }) else { return false }

        if (octets[0] == 192 && octets[1] == 0 && octets[2] == 0)
            || (octets[0] == 192 && octets[1] == 0 && octets[2] == 2)
            || (octets[0] == 192 && octets[1] == 88 && octets[2] == 99)
            || (octets[0] == 198 && octets[1] == 51 && octets[2] == 100)
            || (octets[0] == 203 && octets[1] == 0 && octets[2] == 113) {
            return false
        }

        switch (octets[0], octets[1]) {
        case (0, _), (10, _), (127, _), (169, 254):
            return false
        case (172, 16...31), (192, 168), (100, 64...127):
            return false
        case (198, 18...19):
            return false
        case (224...255, _):
            return false
        default:
            return true
        }
    }

    private static func isPublicIPv6Literal(_ host: String) -> Bool {
        guard !host.contains("%") else { return false } // scoped/link-local address

        var address = in6_addr()
        guard inet_pton(AF_INET6, host, &address) == 1 else { return false }
        let bytes = withUnsafeBytes(of: &address) { Array($0) }
        guard bytes.count == 16 else { return false }

        let isUnspecified = bytes.allSatisfy { $0 == 0 }
        let isLoopback = bytes.dropLast().allSatisfy { $0 == 0 } && bytes.last == 1
        let isUniqueLocal = bytes[0] & 0xFE == 0xFC
        let isLinkLocal = bytes[0] == 0xFE && bytes[1] & 0xC0 == 0x80
        let isMulticast = bytes[0] == 0xFF
        guard !isUnspecified, !isLoopback, !isUniqueLocal, !isLinkLocal, !isMulticast else {
            return false
        }

        let isIPv4Mapped = bytes.prefix(10).allSatisfy { $0 == 0 }
            && bytes[10] == 0xFF && bytes[11] == 0xFF
        let isIPv4Compatible = bytes.prefix(12).allSatisfy { $0 == 0 }
        if isIPv4Mapped || isIPv4Compatible {
            return isPublicIPv4Literal(bytes.suffix(4).map { String($0) })
        }

        let isDocumentation = bytes[0] == 0x20 && bytes[1] == 0x01
            && bytes[2] == 0x0D && bytes[3] == 0xB8
        let isBenchmarking = bytes[0] == 0x20 && bytes[1] == 0x01
            && bytes[2] == 0x00 && bytes[3] == 0x02
        guard !isDocumentation, !isBenchmarking else { return false }

        // Literal addresses shown in a source link must be globally routed
        // unicast. Publisher domains still support IPv6 through normal DNS.
        return bytes[0] & 0xE0 == 0x20
    }
}
