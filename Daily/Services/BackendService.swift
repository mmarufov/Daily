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
    
    private init(baseURL: URL = URL(string: "https://daily-backend.fly.dev")!, urlSession: URLSession = .shared) {
        self.baseURL = baseURL
        self.urlSession = urlSession
    }
    
    // MARK: - News/Articles Endpoints
    
    func fetchArticles(accessToken: String, limit: Int = 20, offset: Int = 0) async throws -> [NewsArticle] {
        let endpoint = baseURL.appendingPathComponent("/articles")
        var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false)
        components?.queryItems = [
            URLQueryItem(name: "limit", value: "\(limit)"),
            URLQueryItem(name: "offset", value: "\(offset)")
        ]
        
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
        
        do {
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            return try decoder.decode([NewsArticle].self, from: data)
        } catch {
            print("Failed to decode articles: \(error)")
            throw NSError(domain: "BackendService", code: 2, userInfo: [NSLocalizedDescriptionKey: "Failed to parse response: \(error.localizedDescription)"])
        }
    }
    
    func fetchArticle(id: String, accessToken: String) async throws -> NewsArticle {
        let endpoint = baseURL.appendingPathComponent("/articles/\(id)")
        
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
        
        do {
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            return try decoder.decode(NewsArticle.self, from: data)
        } catch {
            print("Failed to decode article: \(error)")
            throw NSError(domain: "BackendService", code: 2, userInfo: [NSLocalizedDescriptionKey: "Failed to parse response: \(error.localizedDescription)"])
        }
    }
    
    // MARK: - Headlines Endpoints
    
    func fetchHeadlines(accessToken: String, limit: Int = 5) async throws -> [NewsArticle] {
        let endpoint = baseURL.appendingPathComponent("/news/headlines")
        var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false)
        components?.queryItems = [
            URLQueryItem(name: "limit", value: "\(limit)")
        ]
        
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
        
        do {
            // Debug: Print raw response
            if let jsonString = String(data: data, encoding: .utf8) {
                print("Headlines response: \(jsonString.prefix(500))")
            }
            
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            let articles = try decoder.decode([NewsArticle].self, from: data)
            print("Successfully decoded \(articles.count) headlines")
            return articles
        } catch {
            // More detailed error logging
            if let jsonString = String(data: data, encoding: .utf8) {
                print("Failed to decode headlines. Response: \(jsonString)")
            }
            print("Decoding error: \(error)")
            if let decodingError = error as? DecodingError {
                switch decodingError {
                case .keyNotFound(let key, let context):
                    print("Missing key: \(key.stringValue) at \(context.codingPath)")
                case .typeMismatch(let type, let context):
                    print("Type mismatch: expected \(type) at \(context.codingPath)")
                case .valueNotFound(let type, let context):
                    print("Value not found: \(type) at \(context.codingPath)")
                case .dataCorrupted(let context):
                    print("Data corrupted at \(context.codingPath): \(context.debugDescription)")
                @unknown default:
                    print("Unknown decoding error")
                }
            }
            throw NSError(domain: "BackendService", code: 2, userInfo: [NSLocalizedDescriptionKey: "Failed to parse response: \(error.localizedDescription)"])
        }
    }
    
    // MARK: - Curation Endpoints
    
    func curateNews(accessToken: String, topic: String, limit: Int = 10) async throws -> [NewsArticle] {
        let endpoint = baseURL.appendingPathComponent("/news/curate")
        var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false)
        components?.queryItems = [
            URLQueryItem(name: "limit", value: "\(limit)"),
            URLQueryItem(name: "topic", value: topic)
        ]
        
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
            var errorMessage = "Request failed with status \(http.statusCode)"
            if let dataString = String(data: data, encoding: .utf8) {
                print("Error response from server: \(dataString)")
                // Try to extract detail from JSON response
                if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let detail = json["detail"] as? String {
                    errorMessage = detail
                } else {
                    errorMessage = dataString
                }
            }
            throw NSError(domain: "BackendService", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: errorMessage])
        }
        
        do {
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            let articles = try decoder.decode([NewsArticle].self, from: data)
            print("Successfully decoded \(articles.count) curated articles")
            return articles
        } catch {
            if let jsonString = String(data: data, encoding: .utf8) {
                print("Failed to decode curated articles. Response: \(jsonString.prefix(500))")
            }
            print("Decoding error: \(error)")
            throw NSError(domain: "BackendService", code: 2, userInfo: [NSLocalizedDescriptionKey: "Failed to parse response: \(error.localizedDescription)"])
        }
    }
    
    // MARK: - Chat Endpoints
    
    func sendChatMessage(message: String, accessToken: String) async throws -> String {
        let endpoint = baseURL.appendingPathComponent("/chat")
        
        var request = URLRequest(url: endpoint)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        let body: [String: Any] = ["message": message]
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
        
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try decoder.decode(UserPreferencesResponse.self, from: data)
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
        
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try decoder.decode(UserPreferencesResponse.self, from: data)
    }
    
    /// Let the backend/AI summarize full chat history and store a compact profile.
    func completeUserPreferences(
        accessToken: String,
        history: [[String: String]]
    ) async throws -> UserPreferencesResponse {
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
        
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try decoder.decode(UserPreferencesResponse.self, from: data)
    }
    
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

