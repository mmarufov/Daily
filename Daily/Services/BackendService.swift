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
    private static let iso8601Decoder: JSONDecoder = {
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

    private init(baseURL: URL = URL(string: "https://daily-backend.fly.dev")!, urlSession: URLSession = .shared) {
        self.baseURL = baseURL
        self.urlSession = urlSession
    }

    // MARK: - Feed Endpoints (new architecture)

    /// Fetch personalized feed from the shared article pool.
    func fetchFeed(
        accessToken: String,
        limit: Int = 20,
        category: String? = nil,
        section: String? = nil
    ) async throws -> [NewsArticle] {
        let endpoint = baseURL.appendingPathComponent("/feed")
        var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false)
        var queryItems = [URLQueryItem(name: "limit", value: "\(limit)")]
        if let category { queryItems.append(URLQueryItem(name: "category", value: category)) }
        if let section { queryItems.append(URLQueryItem(name: "section", value: section)) }
        components?.queryItems = queryItems

        guard let url = components?.url else {
            throw NSError(domain: "BackendService", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid URL"])
        }

        var request = URLRequest(url: url)
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

        return try Self.iso8601Decoder.decode([NewsArticle].self, from: data)
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

    /// Force re-score articles (ignores cache).
    func refreshFeed(
        accessToken: String,
        limit: Int = 20,
        category: String? = nil,
        section: String? = nil
    ) async throws -> [NewsArticle] {
        let endpoint = baseURL.appendingPathComponent("/feed/refresh")
        var queryItems = [URLQueryItem(name: "limit", value: "\(limit)")]
        if let category { queryItems.append(URLQueryItem(name: "category", value: category)) }
        if let section { queryItems.append(URLQueryItem(name: "section", value: section)) }
        var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false)
        components?.queryItems = queryItems

        guard let url = components?.url else {
            throw NSError(domain: "BackendService", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid URL"])
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
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

        return try Self.iso8601Decoder.decode([NewsArticle].self, from: data)
    }

    // MARK: - Chat Endpoints

    func sendChatMessage(
        message: String,
        accessToken: String,
        history: [[String: String]]? = nil,
        articleContext: [String: String]? = nil
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

    // MARK: - Interest Onboarding & Preferences

    struct UserPreferencesResponse: Decodable {
        let id: String?
        let userId: String
        let interests: [String: AnyCodable]?
        let aiProfile: String?
        let completed: Bool
        let completedAt: Date?

        enum CodingKeys: String, CodingKey {
            case id
            case userId = "user_id"
            case interests
            case aiProfile = "ai_profile"
            case completed
            case completedAt = "completed_at"
        }
    }

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
    /// Returns nothing — we only care that the server accepted it.
    func completeUserPreferences(
        accessToken: String,
        history: [[String: String]]
    ) async throws {
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
}

// MARK: - UserPreferencesResponse Helpers

extension BackendService.UserPreferencesResponse {
    /// Extract the user's interest topics as a simple string array.
    var topicsList: [String] {
        guard let interests = interests,
              let topicsValue = interests["topics"],
              let topics = topicsValue.value as? [Any] else { return [] }
        return topics.compactMap { $0 as? String }
    }
}
