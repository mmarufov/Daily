//
//  BackendService.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import Foundation

final class BackendService {
    static let shared = BackendService()

    private let baseURL: URL
    private let urlSession: URLSession

    /// ISO8601 date decoder that handles fractional seconds (from PostgreSQL's `now()`).
    static let iso8601Decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        let withFractional = ISO8601DateFormatter()
        withFractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let withoutFractional = ISO8601DateFormatter()
        withoutFractional.formatOptions = [.withInternetDateTime]
        // Fallback for microsecond-precision dates from Python's datetime.isoformat()
        let microFmt = DateFormatter()
        microFmt.locale = Locale(identifier: "en_US_POSIX")
        microFmt.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSSXXXXX"
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let string = try container.decode(String.self)
            if let date = withFractional.date(from: string) { return date }
            if let date = withoutFractional.date(from: string) { return date }
            if let date = microFmt.date(from: string) { return date }
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Cannot decode date: \(string)")
        }
        return decoder
    }()

    /// Session with extended timeout for AI-scored feed requests.
    private let feedSession: URLSession = {
        let config = URLSessionConfiguration.default
        config.timeoutIntervalForRequest = 300
        config.timeoutIntervalForResource = 300
        config.waitsForConnectivity = true
        return URLSession(configuration: config)
    }()

    private init(baseURL: URL = URL(string: "https://daily-backend.fly.dev")!, urlSession: URLSession = .shared) {
        self.baseURL = baseURL
        self.urlSession = urlSession
    }

    // MARK: - Feed Endpoints (new architecture)

    func fetchFeedState(
        accessToken: String,
        limit: Int = 50
    ) async throws -> FeedResponse {
        let endpoint = baseURL.appendingPathComponent("/feed")
        var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false)
        let queryItems = [URLQueryItem(name: "limit", value: "\(limit)")]
        components?.queryItems = queryItems

        guard let url = components?.url else {
            throw NSError(domain: "BackendService", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid URL"])
        }

        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let (data, response) = try await feedSession.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw NSError(domain: "BackendService", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid response"])
        }

        guard (200..<300).contains(http.statusCode) else {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Request failed with status \(http.statusCode)"
            throw NSError(domain: "BackendService", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: errorMessage])
        }

        let feedResponse = try Self.iso8601Decoder.decode(FeedResponse.self, from: data)
        if let feedRequestId = feedResponse.feedRequestId {
            ReadingEventTracker.shared.setFeedRequestId(feedRequestId)
        }
        return feedResponse
    }

    /// Convenience wrapper for legacy callers that only need ready articles.
    func fetchFeed(
        accessToken: String,
        limit: Int = 50
    ) async throws -> [NewsArticle] {
        let response = try await fetchFeedState(accessToken: accessToken, limit: limit)
        return response.articles
    }

    /// Fetch a single article with full content (extracts on-demand if needed).
    func fetchFeedArticle(id: String, accessToken: String) async throws -> NewsArticle {
        let endpoint = baseURL.appendingPathComponent("/feed/\(id)")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "GET"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let (data, response) = try await urlSession.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw NSError(domain: "BackendService", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid response"])
        }

        guard (200..<300).contains(http.statusCode) else {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Request failed with status \(http.statusCode)"
            throw NSError(domain: "BackendService", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: errorMessage])
        }

        return try Self.iso8601Decoder.decode(NewsArticle.self, from: data)
    }

    func buildFeed(
        accessToken: String,
        limit: Int = 50
    ) async throws -> FeedResponse {
        let endpoint = baseURL.appendingPathComponent("/feed/build")
        let queryItems = [URLQueryItem(name: "limit", value: "\(limit)")]
        var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false)
        components?.queryItems = queryItems

        guard let url = components?.url else {
            throw NSError(domain: "BackendService", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid URL"])
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let (data, response) = try await feedSession.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw NSError(domain: "BackendService", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid response"])
        }

        guard (200..<300).contains(http.statusCode) else {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Request failed with status \(http.statusCode)"
            throw NSError(domain: "BackendService", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: errorMessage])
        }

        let feedResponse = try Self.iso8601Decoder.decode(FeedResponse.self, from: data)
        if let feedRequestId = feedResponse.feedRequestId {
            ReadingEventTracker.shared.setFeedRequestId(feedRequestId)
        }
        return feedResponse
    }

    /// Force refresh from the existing personalized source graph.
    func refreshFeedStatus(
        accessToken: String,
        limit: Int = 50
    ) async throws -> FeedResponse {
        let endpoint = baseURL.appendingPathComponent("/feed/refresh")
        let queryItems = [URLQueryItem(name: "limit", value: "\(limit)")]
        var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false)
        components?.queryItems = queryItems

        guard let url = components?.url else {
            throw NSError(domain: "BackendService", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid URL"])
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let (data, response) = try await feedSession.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw NSError(domain: "BackendService", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid response"])
        }

        guard (200..<300).contains(http.statusCode) else {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Request failed with status \(http.statusCode)"
            throw NSError(domain: "BackendService", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: errorMessage])
        }

        let feedResponse = try Self.iso8601Decoder.decode(FeedResponse.self, from: data)
        if let feedRequestId = feedResponse.feedRequestId {
            ReadingEventTracker.shared.setFeedRequestId(feedRequestId)
        }
        return feedResponse
    }

    func refreshFeed(
        accessToken: String,
        limit: Int = 50
    ) async throws -> [NewsArticle] {
        let response = try await refreshFeedStatus(accessToken: accessToken, limit: limit)
        return response.articles
    }

    func discoverSources(accessToken: String) async throws -> DiscoverSourcesResponse {
        let endpoint = baseURL.appendingPathComponent("/sources/discover")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let (data, response) = try await feedSession.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw NSError(domain: "BackendService", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid response"])
        }

        guard (200..<300).contains(http.statusCode) else {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Request failed with status \(http.statusCode)"
            throw NSError(domain: "BackendService", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: errorMessage])
        }

        return try Self.iso8601Decoder.decode(DiscoverSourcesResponse.self, from: data)
    }

    // MARK: - Chat Endpoints

    func sendChatMessage(
        message: String,
        accessToken: String,
        history: [[String: String]]? = nil,
        articleContext: [String: String]? = nil,
        articlesContext: [[String: String]]? = nil
    ) async throws -> String {
        let endpoint = baseURL.appendingPathComponent("/chat")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        var body: [String: Any] = ["message": message]
        if let history, !history.isEmpty {
            body["history"] = history
        }
        if let articleContext, !articleContext.isEmpty {
            body["article_context"] = articleContext
        }
        if let articlesContext, !articlesContext.isEmpty {
            body["articles_context"] = articlesContext
        }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await urlSession.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw NSError(domain: "BackendService", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid response"])
        }

        guard (200..<300).contains(http.statusCode) else {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Request failed with status \(http.statusCode)"
            throw NSError(domain: "BackendService", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: errorMessage])
        }

        do {
            if let json = try JSONSerialization.jsonObject(with: data) as? [String: Any],
               let response = json["response"] as? String {
                return response
            } else {
                throw NSError(domain: "BackendService", code: 2, userInfo: [NSLocalizedDescriptionKey: "Invalid response format"])
            }
        } catch {
            throw NSError(domain: "BackendService", code: 2, userInfo: [NSLocalizedDescriptionKey: "Failed to parse response: \(error.localizedDescription)"])
        }
    }

    // MARK: - Semantic Search & Categories

    func semanticSearch(query: String, limit: Int = 8, accessToken: String) async throws -> [NewsArticle] {
        let endpoint = baseURL.appendingPathComponent("/search/semantic")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = ["query": query, "limit": limit]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await urlSession.data(for: request)

        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Search failed"
            throw NSError(domain: "BackendService", code: (response as? HTTPURLResponse)?.statusCode ?? 0,
                          userInfo: [NSLocalizedDescriptionKey: errorMessage])
        }

        // Decode the {articles: [...]} wrapper
        let wrapper = try Self.iso8601Decoder.decode(SemanticSearchResponse.self, from: data)
        return wrapper.articles
    }

    struct SemanticSearchResponse: Decodable {
        let articles: [NewsArticle]
    }

    struct CategoryCount: Decodable {
        let name: String
        let count: Int
    }

    func fetchCategories(accessToken: String) async throws -> [CategoryCount] {
        let endpoint = baseURL.appendingPathComponent("/categories")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "GET"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let (data, response) = try await urlSession.data(for: request)

        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            return []
        }

        let wrapper = try JSONDecoder().decode(CategoriesResponse.self, from: data)
        return wrapper.categories
    }

    struct CategoriesResponse: Decodable {
        let categories: [CategoryCount]
    }

    enum FeedStatus: String, Decodable {
        case ready
        case needsBuild = "needs_build"
        case needsDiscovery = "needs_discovery"
    }

    struct FeedResponse: Decodable {
        let status: FeedStatus
        let articles: [NewsArticle]
        let feedRequestId: String?
        let articleCount: Int?
        let qualityMet: Bool?
        let buildTimeSeconds: Double?
        let profileSpecificity: String?

        enum CodingKeys: String, CodingKey {
            case status
            case articles
            case feedRequestId = "feed_request_id"
            case articleCount = "article_count"
            case qualityMet = "quality_met"
            case buildTimeSeconds = "build_time_seconds"
            case profileSpecificity = "profile_specificity"
        }
    }

    struct DiscoverSourcesResponse: Decodable {
        let sourcesFound: Int
        let exactSources: Int
        let supportingSources: Int
        let discoveryTimeSeconds: Double?
        let profileSpecificity: String?

        enum CodingKeys: String, CodingKey {
            case sourcesFound = "sources_found"
            case exactSources = "exact_sources"
            case supportingSources = "supporting_sources"
            case discoveryTimeSeconds = "discovery_time_seconds"
            case profileSpecificity = "profile_specificity"
        }
    }

    struct BriefingResponse: Decodable {
        let content: String?
        let generatedAt: String?

        enum CodingKeys: String, CodingKey {
            case content
            case generatedAt = "generated_at"
        }
    }

    struct EntityPin: Codable, Identifiable {
        let id: String
        let name: String
        let type: String
        let createdAt: String?

        enum CodingKeys: String, CodingKey {
            case id, name, type
            case createdAt = "created_at"
        }
    }

    struct EntityListResponse: Decodable {
        let entities: [EntityPin]
    }

    struct InterestSuggestion: Codable, Identifiable {
        let id: String
        let topic: String
        let confidence: Double
        let createdAt: String?

        enum CodingKeys: String, CodingKey {
            case id, topic, confidence
            case createdAt = "created_at"
        }
    }

    struct SuggestionsResponse: Decodable {
        let suggestions: [InterestSuggestion]
    }

    // MARK: - Interest Onboarding & Preferences

    struct UserPreferencesResponse: Decodable {
        let id: String?
        let userId: String
        let interests: [String: AnyCodable]?
        let aiProfile: String?
        let completed: Bool
        let completedAt: Date?
        let profileSpecificity: String?
        let setupRequired: Bool?

        enum CodingKeys: String, CodingKey {
            case id
            case userId = "user_id"
            case interests
            case aiProfile = "ai_profile"
            case completed
            case completedAt = "completed_at"
            case profileSpecificity = "profile_specificity"
            case setupRequired = "setup_required"
        }
    }

    typealias CompleteUserPreferencesResponse = UserPreferencesResponse

    /// Lightweight type-erased wrapper to decode arbitrary JSON into Swift.
    struct AnyCodable: Codable {
        let value: Any

        init(_ value: Any) {
            self.value = value
        }

        init(from decoder: Decoder) throws {
            let container = try decoder.singleValueContainer()

            if container.decodeNil() {
                self.value = NSNull()
            } else if let bool = try? container.decode(Bool.self) {
                self.value = bool
            } else if let int = try? container.decode(Int.self) {
                self.value = int
            } else if let double = try? container.decode(Double.self) {
                self.value = double
            } else if let string = try? container.decode(String.self) {
                self.value = string
            } else if let array = try? container.decode([AnyCodable].self) {
                self.value = array.map { $0.value }
            } else if let dict = try? container.decode([String: AnyCodable].self) {
                var result: [String: Any] = [:]
                for (key, wrapped) in dict {
                    result[key] = wrapped.value
                }
                self.value = result
            } else {
                throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported JSON type")
            }
        }

        func encode(to encoder: Encoder) throws {
            var container = encoder.singleValueContainer()

            switch value {
            case is NSNull:
                try container.encodeNil()
            case let bool as Bool:
                try container.encode(bool)
            case let int as Int:
                try container.encode(int)
            case let double as Double:
                try container.encode(double)
            case let string as String:
                try container.encode(string)
            case let array as [Any]:
                let wrapped = array.map { AnyCodable($0) }
                try container.encode(wrapped)
            case let dict as [String: Any]:
                let wrapped = dict.mapValues { AnyCodable($0) }
                try container.encode(wrapped)
            default:
                let context = EncodingError.Context(codingPath: container.codingPath, debugDescription: "Unsupported JSON type")
                throw EncodingError.invalidValue(value, context)
            }
        }
    }

    func fetchUserPreferences(accessToken: String) async throws -> UserPreferencesResponse {
        let endpoint = baseURL.appendingPathComponent("/user/preferences")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "GET"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let (data, response) = try await urlSession.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw NSError(domain: "BackendService", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid response"])
        }

        guard (200..<300).contains(http.statusCode) else {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Request failed with status \(http.statusCode)"
            throw NSError(domain: "BackendService", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: errorMessage])
        }

        return try Self.iso8601Decoder.decode(UserPreferencesResponse.self, from: data)
    }

    func saveUserPreferences(
        accessToken: String,
        interests: [String: Any],
        aiProfile: String,
        completed: Bool = true
    ) async throws -> UserPreferencesResponse {
        let endpoint = baseURL.appendingPathComponent("/user/preferences")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = [
            "interests": interests,
            "ai_profile": aiProfile,
            "completed": completed
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await urlSession.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw NSError(domain: "BackendService", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid response"])
        }

        guard (200..<300).contains(http.statusCode) else {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Request failed with status \(http.statusCode)"
            throw NSError(domain: "BackendService", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: errorMessage])
        }

        return try Self.iso8601Decoder.decode(UserPreferencesResponse.self, from: data)
    }

    /// Let the backend/AI summarize full chat history and store a compact profile.
    func completeUserPreferences(
        accessToken: String,
        history: [[String: String]]
    ) async throws -> CompleteUserPreferencesResponse {
        let endpoint = baseURL.appendingPathComponent("/user/preferences/complete")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = [
            "history": history
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await urlSession.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw NSError(domain: "BackendService", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid response"])
        }

        guard (200..<300).contains(http.statusCode) else {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Request failed with status \(http.statusCode)"
            throw NSError(domain: "BackendService", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: errorMessage])
        }

        return try Self.iso8601Decoder.decode(CompleteUserPreferencesResponse.self, from: data)
    }

    // MARK: - Interest Onboarding Chat

    func sendInterestChatMessage(
        message: String,
        history: [[String: String]],
        accessToken: String
    ) async throws -> String {
        let endpoint = baseURL.appendingPathComponent("/chat/interests")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = [
            "message": message,
            "history": history
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await urlSession.data(for: request)

        guard let http = response as? HTTPURLResponse else {
            throw NSError(domain: "BackendService", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid response"])
        }

        guard (200..<300).contains(http.statusCode) else {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Request failed with status \(http.statusCode)"
            throw NSError(domain: "BackendService", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: errorMessage])
        }

        if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let responseText = json["response"] as? String {
            return responseText
        } else {
            throw NSError(domain: "BackendService", code: 2, userInfo: [NSLocalizedDescriptionKey: "Invalid response format"])
        }
    }

    // MARK: - Reading Events

    func submitReadingEvents(_ events: [ReadingEventTracker.ReadingEvent], accessToken: String) async throws {
        let endpoint = baseURL.appendingPathComponent("/reading-events")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let eventsPayload = events.map { event -> [String: Any] in
            var dict: [String: Any] = [
                "article_id": event.articleId,
                "type": event.type
            ]
            if let duration = event.durationSeconds { dict["duration_seconds"] = duration }
            if let feedReqId = event.feedRequestId { dict["feed_request_id"] = feedReqId }
            if let position = event.position { dict["position"] = position }
            return dict
        }
        let body: [String: Any] = ["events": eventsPayload]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (_, response) = try await urlSession.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            return // Silent failure — reading events are non-critical
        }
    }

    // MARK: - Briefing

    func fetchBriefing(accessToken: String) async throws -> BriefingResponse {
        let endpoint = baseURL.appendingPathComponent("/briefing")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "GET"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let (data, response) = try await urlSession.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            return BriefingResponse(content: nil, generatedAt: nil)
        }

        return try Self.iso8601Decoder.decode(BriefingResponse.self, from: data)
    }

    // MARK: - Entities

    func fetchEntityPins(accessToken: String) async throws -> [EntityPin] {
        let endpoint = baseURL.appendingPathComponent("/entities")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "GET"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await urlSession.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            return []
        }

        return try Self.iso8601Decoder.decode(EntityListResponse.self, from: data).entities
    }

    func createEntityPin(name: String, type: String = "topic", accessToken: String) async throws -> EntityPin {
        let endpoint = baseURL.appendingPathComponent("/entities")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = ["name": name, "type": type]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await urlSession.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? -1
            let errorMessage = String(data: data, encoding: .utf8) ?? "Failed to create entity"
            throw NSError(domain: "BackendService", code: statusCode, userInfo: [NSLocalizedDescriptionKey: errorMessage])
        }

        return try Self.iso8601Decoder.decode(EntityPin.self, from: data)
    }

    func deleteEntityPin(id: String, accessToken: String) async throws {
        let endpoint = baseURL.appendingPathComponent("/entities/\(id)")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "DELETE"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")

        let (_, response) = try await urlSession.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw NSError(domain: "BackendService", code: -1, userInfo: [NSLocalizedDescriptionKey: "Failed to delete entity"])
        }
    }

    // MARK: - Interest Suggestions

    func fetchInterestSuggestions(accessToken: String) async throws -> [InterestSuggestion] {
        let endpoint = baseURL.appendingPathComponent("/interests/suggestions")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "GET"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")

        let (data, response) = try await urlSession.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            return []
        }

        return try Self.iso8601Decoder.decode(SuggestionsResponse.self, from: data).suggestions
    }

    func acceptInterestSuggestion(id: String, accessToken: String) async throws {
        let endpoint = baseURL.appendingPathComponent("/interests/suggestions/\(id)/accept")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")

        let (_, response) = try await urlSession.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw NSError(domain: "BackendService", code: -1, userInfo: [NSLocalizedDescriptionKey: "Failed to accept suggestion"])
        }
    }

    func dismissInterestSuggestion(id: String, accessToken: String) async throws {
        let endpoint = baseURL.appendingPathComponent("/interests/suggestions/\(id)/dismiss")

        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")

        let (_, response) = try await urlSession.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw NSError(domain: "BackendService", code: -1, userInfo: [NSLocalizedDescriptionKey: "Failed to dismiss suggestion"])
        }
    }
}

// MARK: - UserPreferencesResponse Helpers

extension BackendService.UserPreferencesResponse {
    /// Preserve the raw interests payload when updating only the AI profile.
    var interestsDictionary: [String: Any] {
        interests?.reduce(into: [:]) { partialResult, element in
            partialResult[element.key] = element.value.value
        } ?? [:]
    }

    /// Build topic tabs from the structured interests the onboarding flow captures.
    var topicsList: [String] {
        let keys = ["topics", "industries", "people", "locations"]
        var seen = Set<String>()
        var result: [String] = []

        for key in keys {
            guard let values = interests?[key]?.value as? [Any] else { continue }

            for value in values {
                guard let stringValue = value as? String else { continue }
                let trimmed = stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
                guard !trimmed.isEmpty else { continue }

                let normalized = trimmed.lowercased()
                guard seen.insert(normalized).inserted else { continue }
                result.append(trimmed)
            }
        }

        return result
    }
}
