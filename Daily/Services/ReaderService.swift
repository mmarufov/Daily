import Foundation

enum ReaderClientError: LocalizedError {
    case authenticationRequired, unavailable, conflict, invalidResponse, requestFailed(Int)
    var errorDescription: String? {
        switch self {
        case .authenticationRequired: return "Sign in before saving your preferences."
        case .unavailable: return "Reader editing is not enabled yet. Use Personalization settings."
        case .conflict: return "Your preferences changed elsewhere. Reload and review before saving again; your draft has not been applied."
        case .invalidResponse: return "The server returned an invalid reader response."
        case .requestFailed(let status): return "The change was not confirmed (HTTP \(status)). Retry, or use the structured Personalization settings."
        }
    }
}

/// No persisted private state. Every caller carries its original version and session identity.
struct ReaderService {
    static let shared = ReaderService()
    var session: URLSession = .shared
    var baseURL: URL = AppConfig.backendURL

    func fetch(token: String) async throws -> ReaderEnvelope {
        try await request("", method: "GET", body: Optional<ReaderMutation>.none, token: token)
    }

    func apply(_ mutation: ReaderMutation, token: String) async throws -> ReaderEnvelope {
        try await request("", method: "PATCH", body: mutation, token: token)
    }

    func propose(text: String, base: ReaderEnvelope, operationID: String, token: String) async throws -> ReaderProposal {
        try await request("/proposals", method: "POST", body: ProposalRequest(
            operationId: operationID, baseGeneration: base.generation, baseRevision: base.revision, text: text
        ), token: token)
    }

    func resetLearning(base: ReaderEnvelope, operationID: String, token: String) async throws -> ReaderEnvelope {
        try await request("/reset-learning", method: "POST", body: ResetRequest(
            operationId: operationID, baseGeneration: base.generation, baseRevision: base.revision
        ), token: token)
    }

    private func request<Body: Encodable, Response: Decodable>(
        _ suffix: String, method: String, body: Body?, token: String
    ) async throws -> Response {
        var request = URLRequest(url: baseURL.appendingPathComponent("user/reader" + suffix))
        request.httpMethod = method
        request.timeoutInterval = 30
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let body {
            let encoder = JSONEncoder()
            encoder.keyEncodingStrategy = .convertToSnakeCase
            encoder.outputFormatting = [.sortedKeys]
            request.httpBody = try encoder.encode(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw ReaderClientError.invalidResponse }
        switch http.statusCode {
        case 200..<300: break
        case 401: throw ReaderClientError.authenticationRequired
        case 404: throw ReaderClientError.unavailable
        case 409: throw ReaderClientError.conflict
        default: throw ReaderClientError.requestFailed(http.statusCode)
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(Response.self, from: data)
    }

    private struct ProposalRequest: Encodable {
        let operationId: String
        let baseGeneration: Int
        let baseRevision: Int
        let text: String
    }
    private struct ResetRequest: Encodable {
        let operationId: String
        let baseGeneration: Int
        let baseRevision: Int
        let patch = ReaderPatch()
    }
}

extension Notification.Name {
    static let readerPreferencesCommitted = Notification.Name("readerPreferencesCommitted")
}
