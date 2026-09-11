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

enum AuthState: Equatable {
    case unknown      // restoring session — show splash, not sign-in
    case authenticated
    /// Local presentation only. This state grants no server or mutation authority.
    case savedAccount(userID: String)
    case unauthenticated
}

@MainActor
final class AuthService: ObservableObject {
    static let shared = AuthService(
        baseURL: AppConfig.backendURL,
        urlSession: makeSession(),
        tokenStore: KeychainHelper(),
        identityCleanup: LiveAuthIdentityCleaner(),
        providerSignOut: GoogleAuthProviderSigner(),
        restoresSession: restoresLiveSession
    )

    private static var restoresLiveSession: Bool {
        #if DEBUG
        if ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil
            || ProcessInfo.processInfo.arguments.contains("--s2-reader-ui-test") { return false }
        #endif
        return true
    }

    @Published private(set) var state: AuthState = .unknown
    @Published private(set) var currentUser: User?

    /// Backwards-compat: views that only check a Bool can keep working.
    var isAuthenticated: Bool { state == .authenticated }

    private let baseURL: URL
    private let urlSession: URLSession
    private let tokenStore: any AuthTokenStoring
    private let identityCleanup: any AuthIdentityCleaning
    private let providerSignOut: any AuthProviderSigningOut
    private let tokenKey = "app_token"
    private let userIDKey = "app_user_id"
    private let logger = Logger(subsystem: "com.daily.app", category: "auth")
    private var transitionGeneration: UInt64 = 0
    private var restoreTask: Task<Void, Never>?
    /// Session identity, including A → B → A transitions. Never compare tokens alone.
    var sessionGeneration: UInt64 { transitionGeneration }

    private static func makeSession() -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 5
        configuration.timeoutIntervalForResource = 8
        configuration.waitsForConnectivity = false
        configuration.urlCache = nil
        configuration.httpCookieStorage = nil
        return URLSession(configuration: configuration)
    }

    init(
        baseURL: URL,
        urlSession: URLSession,
        tokenStore: any AuthTokenStoring,
        identityCleanup: any AuthIdentityCleaning,
        providerSignOut: any AuthProviderSigningOut,
        restoresSession: Bool
    ) {
        self.baseURL = baseURL
        self.urlSession = urlSession
        self.tokenStore = tokenStore
        self.identityCleanup = identityCleanup
        self.providerSignOut = providerSignOut
        if restoresSession {
            restoreSession()
        } else {
            state = tokenStore.read(key: tokenKey) == nil ? .unauthenticated : .unknown
        }
    }

    func authenticateWithGoogle(idToken: String) async throws {
        transitionGeneration &+= 1
        restoreTask?.cancel()
        let requestGeneration = transitionGeneration
        let endpoint = baseURL.appendingPathComponent("/auth/google")
        try await authenticate(
            providerEndpoint: endpoint,
            payload: ["id_token": idToken],
            requestGeneration: requestGeneration
        )
    }

    func signOut() {
        transitionToUnauthenticated(signOutProvider: true)
    }

    func getAccessToken() -> String? {
        guard isAuthenticated else { return nil }
        return tokenStore.read(key: tokenKey)
    }

    func restoreSession() {
        restoreTask?.cancel()
        guard let token = tokenStore.read(key: tokenKey) else {
            transitionToUnauthenticated(signOutProvider: false)
            return
        }

        transitionGeneration &+= 1
        let requestGeneration = transitionGeneration
        currentUser = nil
        if let owner = tokenStore.read(key: userIDKey), !owner.isEmpty {
            state = .savedAccount(userID: owner)
        } else {
            state = .unknown
        }
        restoreTask = Task { [weak self] in
            await self?.hydrateUser(with: token, requestGeneration: requestGeneration)
        }
    }

    private func authenticate(
        providerEndpoint: URL,
        payload: [String: String],
        requestGeneration: UInt64
    ) async throws {
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
        let decoded: AuthResponse
        do {
            decoded = try JSONDecoder().decode(AuthResponse.self, from: data)
        } catch {
            logger.error("Failed to decode auth response: \(error.localizedDescription, privacy: .private)")
            throw NSError(domain: "AuthService", code: 2, userInfo: [
                NSLocalizedDescriptionKey: "Failed to parse server response"
            ])
        }

        // A sign-out or newer login request supersedes this response.
        try Task.checkCancellation()
        guard requestGeneration == transitionGeneration else {
            throw CancellationError()
        }
        try transitionToAuthenticated(user: decoded.user, token: decoded.token)
    }

    private func hydrateUser(with token: String, requestGeneration: UInt64) async {
        var request = URLRequest(url: baseURL.appendingPathComponent("/me"))
        request.timeoutInterval = 8
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.httpMethod = "GET"
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        do {
            let (data, response) = try await urlSession.data(for: request)
            guard isCurrentRestore(token: token, generation: requestGeneration) else { return }
            guard let http = response as? HTTPURLResponse else {
                resolveTransientRestoreFailure()
                return
            }
            if [401, 403].contains(http.statusCode) {
                transitionToUnauthenticated(signOutProvider: true)
                return
            }
            guard (200..<300).contains(http.statusCode) else {
                resolveTransientRestoreFailure()
                return
            }
            let user = try JSONDecoder().decode(User.self, from: data)
            guard isCurrentRestore(token: token, generation: requestGeneration) else { return }
            try transitionToAuthenticated(user: user, token: token)
        } catch {
            guard isCurrentRestore(token: token, generation: requestGeneration) else { return }
            resolveTransientRestoreFailure()
        }
    }

    private func transitionToAuthenticated(user: User, token: String) throws {
        let previousUserID = currentUser?.id ?? tokenStore.read(key: userIDKey)

        // Persist credentials before publishing the new identity. If either
        // write fails, no new account state becomes visible to the app.
        do {
            try tokenStore.write(key: tokenKey, value: token)
            try tokenStore.write(key: userIDKey, value: user.id)
        } catch {
            transitionToUnauthenticated(signOutProvider: false)
            throw error
        }

        transitionGeneration &+= 1
        if previousUserID != user.id {
            identityCleanup.run()
        }
        currentUser = user
        identityCleanup.activate(userID: user.id, sessionGeneration: transitionGeneration)
        state = .authenticated
    }

    private func transitionToUnauthenticated(signOutProvider: Bool) {
        transitionGeneration &+= 1
        restoreTask?.cancel()
        restoreTask = nil
        tokenStore.delete(key: tokenKey)
        tokenStore.delete(key: userIDKey)
        identityCleanup.run()
        currentUser = nil
        state = .unauthenticated
        if signOutProvider {
            providerSignOut.signOut()
        }
    }

    private func isCurrentRestore(token: String, generation: UInt64) -> Bool {
        generation == transitionGeneration && tokenStore.read(key: tokenKey) == token
    }

    private func resolveTransientRestoreFailure() {
        // The backend may be briefly unreachable. Retain the token and its
        // owner marker so retrying does not destroy the user's local state.
        currentUser = nil
        if let owner = tokenStore.read(key: userIDKey), !owner.isEmpty {
            state = .savedAccount(userID: owner)
        } else {
            state = .unauthenticated
        }
    }
}

@MainActor
protocol AuthIdentityCleaning {
    func run()
    func activate(userID: String, sessionGeneration: UInt64)
}

extension AuthIdentityCleaning {
    func activate(userID: String, sessionGeneration: UInt64) {}
}

@MainActor
struct LiveAuthIdentityCleaner: AuthIdentityCleaning {
    func run() {
        BookmarkService.shared.clearAll()
        ReadingEventTracker.shared.discardPending()
        ReaderFeedbackStore.shared.clear()
        BackgroundNewsFetcher.shared.clearCache()
        ImageCacheService.shared.clearCache()
    }

    func activate(userID: String, sessionGeneration: UInt64) {
        BackgroundNewsFetcher.shared.invalidatePendingWrites()
        BookmarkService.shared.activate(userID: userID, sessionGeneration: sessionGeneration)
    }
}

@MainActor
protocol AuthProviderSigningOut {
    func signOut()
}

@MainActor
struct GoogleAuthProviderSigner: AuthProviderSigningOut {
    func signOut() {
        GoogleSignInHelper.shared.signOut()
    }
}

protocol AuthTokenStoring {
    func write(key: String, value: String) throws
    func read(key: String) -> String?
    func delete(key: String)
}

// Simple Keychain wrapper suitable for tokens.
// - Sets kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly so tokens never
//   leave the device (no iCloud backup).
// - Surfaces OSStatus failures by throwing on write so callers can handle.
final class KeychainHelper: AuthTokenStoring {
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
