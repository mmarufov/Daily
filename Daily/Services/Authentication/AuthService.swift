//
//  AuthService.swift
//  Daily
//
//  Created by Assistant on 11/4/25.
//

import Foundation

@MainActor
final class AuthService: ObservableObject {
    static let shared = AuthService()

    @Published private(set) var isAuthenticated: Bool = false
    @Published private(set) var currentUser: User?

    private let baseURL: URL
    private let urlSession: URLSession
    private let keychain = KeychainHelper()
    private let tokenKey = "app_token"

    private init(baseURL: URL = URL(string: "http://localhost:8000")!, urlSession: URLSession = .shared) {
        self.baseURL = baseURL
        self.urlSession = urlSession
        self.restoreSession()
    }

    func authenticateWithGoogle(idToken: String) async throws {
        let endpoint = baseURL.appendingPathComponent("/auth/google")
        try await authenticate(providerEndpoint: endpoint, payload: ["id_token": idToken])
    }

    func authenticateWithApple(identityToken: String) async throws {
        let endpoint = baseURL.appendingPathComponent("/auth/apple")
        try await authenticate(providerEndpoint: endpoint, payload: ["identity_token": identityToken])
    }

    func signOut() {
        keychain.delete(key: tokenKey)
        self.currentUser = nil
        self.isAuthenticated = false
    }

    func getAccessToken() -> String? {
        keychain.read(key: tokenKey)
    }

    private func restoreSession() {
        guard let token = keychain.read(key: tokenKey) else { return }
        Task { [weak self] in
            await self?.hydrateUser(with: token)
        }
    }

    private func authenticate(providerEndpoint: URL, payload: [String: String]) async throws {
        var request = URLRequest(url: providerEndpoint)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: payload, options: [])

        let (data, response) = try await urlSession.data(for: request)
        guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw NSError(domain: "AuthService", code: 1, userInfo: [NSLocalizedDescriptionKey: "Auth failed"])
        }

        struct AuthResponse: Codable { let token: String; let user: User }
        let decoded = try JSONDecoder().decode(AuthResponse.self, from: data)
        keychain.write(key: tokenKey, value: decoded.token)

        self.currentUser = decoded.user
        self.isAuthenticated = true
    }

    private func hydrateUser(with token: String) async {
        var request = URLRequest(url: baseURL.appendingPathComponent("/me"))
        request.httpMethod = "GET"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        do {
            let (data, response) = try await urlSession.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { return }
            let user = try JSONDecoder().decode(User.self, from: data)
            self.currentUser = user
            self.isAuthenticated = true
        } catch {
            // Ignore errors during silent restore
        }
    }
}

// Simple Keychain wrapper suitable for tokens
import Security

final class KeychainHelper {
    func write(key: String, value: String) {
        let data = Data(value.utf8)
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key
        ]
        SecItemDelete(query as CFDictionary)
        var addQuery = query
        addQuery[kSecValueData as String] = data
        SecItemAdd(addQuery as CFDictionary, nil)
    }

    func read(key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne
        ]
        var out: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &out)
        guard status == errSecSuccess, let data = out as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    func delete(key: String) {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key
        ]
        SecItemDelete(query as CFDictionary)
    }
}


