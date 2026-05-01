//
//  AuthService.swift
//  Daily
//
//  Created by Muhammadjon on 11/4/25.
//

import Foundation
import Combine
import os
import Security

enum AuthState {
    case unknown      // restoring session — show splash, not sign-in
    case authenticated
    case unauthenticated
}

@MainActor
final class AuthService: ObservableObject {
    static let shared = AuthService()

    @Published private(set) var state: AuthState = .unknown
    @Published private(set) var currentUser: User?

    /// Backwards-compat: views that only check a Bool can keep working.
    var isAuthenticated: Bool { state == .authenticated }

    private let baseURL: URL
    private let urlSession: URLSession
    private let keychain = KeychainHelper()
    private let tokenKey = "app_token"
    private let logger = Logger(subsystem: "com.daily.app", category: "auth")

    private init(baseURL: URL = AppConfig.backendURL, urlSession: URLSession = .shared) {
        self.baseURL = baseURL
        self.urlSession = urlSession
        self.restoreSession()
    }

    func authenticateWithGoogle(idToken: String) async throws {
        let endpoint = baseURL.appendingPathComponent("/auth/google")
        try await authenticate(providerEndpoint: endpoint, payload: ["id_token": idToken])
    }

    func signOut() {
        keychain.delete(key: tokenKey)
        self.currentUser = nil
        self.state = .unauthenticated
        // Clear all per-user local state so a new sign-in starts clean.
        BookmarkService.shared.clearAll()
        ReadingEventTracker.shared.discardPending()
        BackgroundNewsFetcher.shared.clearCache()
        GoogleSignInHelper.shared.signOut()
    }

    func getAccessToken() -> String? {
        keychain.read(key: tokenKey)
    }

    private func restoreSession() {
        guard let token = keychain.read(key: tokenKey) else {
            self.state = .unauthenticated
            return
        }
        // Optimistically authenticated while we verify with /me. ContentView
        // shows a splash for `.unknown` state; once /me responds we resolve.
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

        guard let http = response as? HTTPURLResponse else {
            throw NSError(domain: "AuthService", code: 1, userInfo: [NSLocalizedDescriptionKey: "Invalid response"])
        }

        guard (200..<300).contains(http.statusCode) else {
            let errorMessage: String
            if let errorData = try? JSONDecoder().decode([String: String].self, from: data),
               let detail = errorData["detail"] {
                errorMessage = detail
            } else if let errorString = String(data: data, encoding: .utf8) {
                errorMessage = errorString
            } else {
                errorMessage = "Auth failed with status \(http.statusCode)"
            }
            // status code is safe to log; body may contain detail strings — keep private.
            logger.error("Auth error status=\(http.statusCode, privacy: .public) detail=\(errorMessage, privacy: .private)")
            throw NSError(domain: "AuthService", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: errorMessage])
        }

        struct AuthResponse: Codable { let token: String; let user: User }
        do {
            let decoded = try JSONDecoder().decode(AuthResponse.self, from: data)
            try keychain.write(key: tokenKey, value: decoded.token)
            self.currentUser = decoded.user
            self.state = .authenticated
        } catch {
            logger.error("Failed to decode auth response: \(error.localizedDescription, privacy: .private)")
            throw NSError(domain: "AuthService", code: 2, userInfo: [
                NSLocalizedDescriptionKey: "Failed to parse server response"
            ])
        }
    }

    private func hydrateUser(with token: String) async {
        var request = URLRequest(url: baseURL.appendingPathComponent("/me"))
        request.httpMethod = "GET"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        do {
            let (data, response) = try await urlSession.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                // Network error — keep token, retry on next launch.
                self.state = .unauthenticated
                return
            }
            if http.statusCode == 401 {
                // Token revoked or expired — clear it so user isn't stuck.
                keychain.delete(key: tokenKey)
                self.state = .unauthenticated
                return
            }
            guard (200..<300).contains(http.statusCode) else {
                self.state = .unauthenticated
                return
            }
            let user = try JSONDecoder().decode(User.self, from: data)
            self.currentUser = user
            self.state = .authenticated
        } catch {
            // Network error during silent restore — don't kick user to sign-in.
            // Keep them in `.unknown` would block forever; flip to unauth so
            // they can choose to retry by re-signing in.
            self.state = .unauthenticated
        }
    }
}

// Simple Keychain wrapper suitable for tokens.
// - Sets kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly so tokens never
//   leave the device (no iCloud backup).
// - Surfaces OSStatus failures by throwing on write so callers can handle.
final class KeychainHelper {
    enum KeychainError: Error { case unhandledStatus(OSStatus) }

    private static let accessibility = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly

    func write(key: String, value: String) throws {
        let data = Data(value.utf8)
        let baseQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key
        ]
        // SecItemDelete is allowed to return errSecItemNotFound — treat that as success.
        let deleteStatus = SecItemDelete(baseQuery as CFDictionary)
        guard deleteStatus == errSecSuccess || deleteStatus == errSecItemNotFound else {
            throw KeychainError.unhandledStatus(deleteStatus)
        }
        var addQuery = baseQuery
        addQuery[kSecValueData as String] = data
        addQuery[kSecAttrAccessible as String] = Self.accessibility
        let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        guard addStatus == errSecSuccess else {
            throw KeychainError.unhandledStatus(addStatus)
        }
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
