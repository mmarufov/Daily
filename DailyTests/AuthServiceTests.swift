import XCTest
@testable import Daily

@MainActor
final class AuthServiceTests: XCTestCase {
    override func tearDown() {
        AuthURLProtocolStub.handler = nil
        super.tearDown()
    }

    func testSignOutClearsEveryIdentityOwnedStoreAndCredentials() async {
        let tokenStore = TestAuthTokenStore([
            "app_token": "token-a",
            "app_user_id": "user-a"
        ])
        let recorder = CleanupRecorder()
        let providerSignOut = ProviderSignOutRecorder()
        let service = makeService(
            tokenStore: tokenStore,
            recorder: recorder,
            providerSignOut: providerSignOut
        )

        service.signOut()

        XCTAssertEqual(service.state, .unauthenticated)
        XCTAssertNil(service.currentUser)
        XCTAssertNil(tokenStore.values["app_token"])
        XCTAssertNil(tokenStore.values["app_user_id"])
        XCTAssertEqual(recorder.bookmarksAndReads, 1)
        XCTAssertEqual(recorder.readingEvents, 1)
        XCTAssertEqual(recorder.backgroundCache, 1)
        XCTAssertEqual(providerSignOut.count, 1)
    }

    func testUnauthorizedRestoreUsesIdentityCleanupPath() async {
        let tokenStore = TestAuthTokenStore([
            "app_token": "rejected-token",
            "app_user_id": "user-a"
        ])
        let recorder = CleanupRecorder()
        let providerSignOut = ProviderSignOutRecorder()
        AuthURLProtocolStub.handler = { request in
            XCTAssertEqual(request.url?.path, "/me")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer rejected-token")
            return (self.response(for: request, statusCode: 401), Data())
        }
        let service = makeService(
            tokenStore: tokenStore,
            recorder: recorder,
            providerSignOut: providerSignOut
        )

        service.restoreSession()
        await waitUntil { providerSignOut.count == 1 }

        XCTAssertEqual(service.state, .unauthenticated)
        XCTAssertNil(tokenStore.values["app_token"])
        XCTAssertNil(tokenStore.values["app_user_id"])
        XCTAssertEqual(recorder.bookmarksAndReads, 1)
        XCTAssertEqual(recorder.readingEvents, 1)
        XCTAssertEqual(recorder.backgroundCache, 1)
    }

    func testReplacementLoginClearsOldIdentityBeforePublishingNewOne() async throws {
        let tokenStore = TestAuthTokenStore([
            "app_token": "token-a",
            "app_user_id": "user-a"
        ])
        let recorder = CleanupRecorder()
        AuthURLProtocolStub.handler = { request in
            XCTAssertEqual(request.url?.path, "/auth/google")
            let body = Data(
                #"{"token":"token-b","user":{"id":"user-b","email":"b@example.com","display_name":"B","photo_url":null}}"#.utf8
            )
            return (self.response(for: request, statusCode: 200), body)
        }
        let service = makeService(tokenStore: tokenStore, recorder: recorder)

        try await service.authenticateWithGoogle(idToken: "provider-token-b")

        XCTAssertEqual(service.state, .authenticated)
        XCTAssertEqual(service.currentUser?.id, "user-b")
        XCTAssertEqual(tokenStore.values["app_token"], "token-b")
        XCTAssertEqual(tokenStore.values["app_user_id"], "user-b")
        XCTAssertEqual(recorder.bookmarksAndReads, 1)
        XCTAssertEqual(recorder.readingEvents, 1)
        XCTAssertEqual(recorder.backgroundCache, 1)
    }

    func testSameAccountLoginKeepsExistingLocalState() async throws {
        let tokenStore = TestAuthTokenStore([
            "app_token": "old-token",
            "app_user_id": "user-a"
        ])
        let recorder = CleanupRecorder()
        AuthURLProtocolStub.handler = { request in
            let body = Data(
                #"{"token":"fresh-token","user":{"id":"user-a","email":"a@example.com","display_name":"A","photo_url":null}}"#.utf8
            )
            return (self.response(for: request, statusCode: 200), body)
        }
        let service = makeService(tokenStore: tokenStore, recorder: recorder)

        try await service.authenticateWithGoogle(idToken: "fresh-provider-token")

        XCTAssertEqual(service.currentUser?.id, "user-a")
        XCTAssertEqual(tokenStore.values["app_token"], "fresh-token")
        XCTAssertEqual(recorder.bookmarksAndReads, 0)
        XCTAssertEqual(recorder.readingEvents, 0)
        XCTAssertEqual(recorder.backgroundCache, 0)
    }

    func testTransientRestoreFailurePreservesCredentialsAndLocalState() async {
        let tokenStore = TestAuthTokenStore([
            "app_token": "offline-token",
            "app_user_id": "user-a"
        ])
        let recorder = CleanupRecorder()
        let providerSignOut = ProviderSignOutRecorder()
        let requestObserved = expectation(description: "Restore attempted without granting access")
        AuthURLProtocolStub.handler = { _ in
            requestObserved.fulfill()
            throw URLError(.notConnectedToInternet)
        }
        let service = makeService(
            tokenStore: tokenStore,
            recorder: recorder,
            providerSignOut: providerSignOut
        )

        service.restoreSession()
        await fulfillment(of: [requestObserved], timeout: 2)
        await waitUntil { service.state == .savedAccount(userID: "user-a") }

        XCTAssertFalse(service.isAuthenticated)
        XCTAssertNil(service.currentUser)
        XCTAssertNil(service.getAccessToken(), "A saved owner marker is not request authority")

        XCTAssertEqual(tokenStore.values["app_token"], "offline-token")
        XCTAssertEqual(tokenStore.values["app_user_id"], "user-a")
        XCTAssertEqual(recorder.bookmarksAndReads, 0)
        XCTAssertEqual(recorder.readingEvents, 0)
        XCTAssertEqual(recorder.backgroundCache, 0)
        XCTAssertEqual(providerSignOut.count, 0)
    }

    func testOfflineTokenWithoutVerifiedOwnerCannotPresentSavedAccount() async {
        let tokenStore = TestAuthTokenStore(["app_token": "unowned-token"])
        AuthURLProtocolStub.handler = { _ in throw URLError(.notConnectedToInternet) }
        let recorder = CleanupRecorder()
        let service = makeService(tokenStore: tokenStore, recorder: recorder)
        service.restoreSession()
        await waitUntil { service.state == .unauthenticated }
        XCTAssertNil(service.currentUser)
        XCTAssertNil(service.getAccessToken())
        XCTAssertEqual(recorder.backgroundCache, 0)
    }

    func testForbiddenRestoreRevokesSavedAccountAndClearsOwner() async {
        let tokenStore = TestAuthTokenStore(["app_token": "forbidden", "app_user_id": "user-a"])
        let recorder = CleanupRecorder()
        AuthURLProtocolStub.handler = { request in
            (self.response(for: request, statusCode: 403), Data())
        }
        let service = makeService(tokenStore: tokenStore, recorder: recorder)
        service.restoreSession()
        XCTAssertEqual(service.state, .savedAccount(userID: "user-a"))
        XCTAssertNil(service.getAccessToken())
        await waitUntil { service.state == .unauthenticated }
        XCTAssertNil(tokenStore.values["app_user_id"])
        XCTAssertEqual(recorder.backgroundCache, 1)
    }

    func testCredentialWriteFailureClearsPartialCredentialsAndLocalState() async {
        let tokenStore = TestAuthTokenStore(
            ["app_token": "token-a", "app_user_id": "user-a"],
            failingWriteKey: "app_user_id"
        )
        let recorder = CleanupRecorder()
        AuthURLProtocolStub.handler = { request in
            let body = Data(
                #"{"token":"token-b","user":{"id":"user-b","email":"b@example.com","display_name":"B","photo_url":null}}"#.utf8
            )
            return (self.response(for: request, statusCode: 200), body)
        }
        let service = makeService(tokenStore: tokenStore, recorder: recorder)

        await XCTAssertThrowsErrorAsync {
            try await service.authenticateWithGoogle(idToken: "provider-token-b")
        }

        XCTAssertEqual(service.state, .unauthenticated)
        XCTAssertNil(service.currentUser)
        XCTAssertNil(tokenStore.values["app_token"])
        XCTAssertNil(tokenStore.values["app_user_id"])
        XCTAssertEqual(recorder.bookmarksAndReads, 1)
        XCTAssertEqual(recorder.readingEvents, 1)
        XCTAssertEqual(recorder.backgroundCache, 1)
    }

    private func makeService(
        tokenStore: TestAuthTokenStore,
        recorder: CleanupRecorder,
        providerSignOut: (any AuthProviderSigningOut)? = nil
    ) -> AuthService {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [AuthURLProtocolStub.self]
        return AuthService(
            baseURL: URL(string: "https://daily-backend.fly.dev")!,
            urlSession: URLSession(configuration: configuration),
            tokenStore: tokenStore,
            identityCleanup: recorder,
            providerSignOut: providerSignOut ?? ProviderSignOutRecorder(),
            restoresSession: false
        )
    }

    private func XCTAssertThrowsErrorAsync(
        _ expression: () async throws -> Void,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async {
        do {
            try await expression()
            XCTFail("Expected expression to throw", file: file, line: line)
        } catch {
            // Expected.
        }
    }

    private func response(for request: URLRequest, statusCode: Int) -> HTTPURLResponse {
        HTTPURLResponse(
            url: request.url!,
            statusCode: statusCode,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )!
    }

    private func waitUntil(
        timeoutIterations: Int = 200,
        condition: @escaping @MainActor () -> Bool
    ) async {
        for _ in 0..<timeoutIterations {
            if condition() { return }
            try? await Task.sleep(nanoseconds: 5_000_000)
        }
        XCTFail("Timed out waiting for asynchronous auth transition")
    }
}

@MainActor
private final class CleanupRecorder: AuthIdentityCleaning {
    var bookmarksAndReads = 0
    var readingEvents = 0
    var backgroundCache = 0

    func run() {
        bookmarksAndReads += 1
        readingEvents += 1
        backgroundCache += 1
    }
}

@MainActor
private final class ProviderSignOutRecorder: AuthProviderSigningOut {
    var count = 0

    func signOut() {
        count += 1
    }
}

private final class TestAuthTokenStore: AuthTokenStoring {
    var values: [String: String]
    private let failingWriteKey: String?

    init(_ values: [String: String] = [:], failingWriteKey: String? = nil) {
        self.values = values
        self.failingWriteKey = failingWriteKey
    }

    func write(key: String, value: String) throws {
        if key == failingWriteKey {
            throw TestAuthTokenStoreError.writeFailed
        }
        values[key] = value
    }

    func read(key: String) -> String? {
        values[key]
    }

    func delete(key: String) {
        values.removeValue(forKey: key)
    }
}

private enum TestAuthTokenStoreError: Error {
    case writeFailed
}

private final class AuthURLProtocolStub: URLProtocol {
    static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    override class func canInit(with request: URLRequest) -> Bool { true }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let handler = Self.handler else {
            client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
            return
        }
        do {
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}
