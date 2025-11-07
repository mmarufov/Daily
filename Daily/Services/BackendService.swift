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
}

