import Foundation
import Combine

enum ArticleReaderState: Equatable {
    case preview(NewsArticle)
    case loading(NewsArticle)
    case ready(NewsArticle)
    case sourceAvailable(NewsArticle, message: String)
    case authenticationRequired(NewsArticle, message: String)
    case offline(NewsArticle, message: String)
    case failed(NewsArticle, message: String)
    case unavailable(NewsArticle, message: String)

    var article: NewsArticle {
        switch self {
        case .preview(let article),
             .loading(let article),
             .ready(let article),
             .sourceAvailable(let article, _),
             .authenticationRequired(let article, _),
             .offline(let article, _),
             .failed(let article, _),
             .unavailable(let article, _):
            return article
        }
    }

    var isLoading: Bool {
        guard case .loading = self else { return false }
        return true
    }

    var isDisplayingNativeBody: Bool {
        guard case .ready(let article) = self else { return false }
        return article.verifiedNativeBody != nil
    }

    var canRetry: Bool {
        switch self {
        case .offline, .failed:
            return true
        default:
            return false
        }
    }
}

enum ArticleReaderCacheDisposition: Equatable {
    case store(NewsArticle)
    case evict(articleID: String)
    case none
}

@MainActor
final class ArticleReaderModel: ObservableObject {
    typealias FetchArticle = (_ articleID: String, _ accessToken: String) async throws -> NewsArticle

    @Published private(set) var state: ArticleReaderState {
        didSet {
            let body = state.article.verifiedNativeBody
            if body != oldValue.article.verifiedNativeBody {
                paragraphs = body.map(Self.paragraphs) ?? []
            }
        }
    }
    private(set) var paragraphs: [String] = []
    private static func paragraphs(_ text: String) -> [String] {
        ArticleTextNormalizer.normalizeBody(text).components(separatedBy: "\n\n")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
    }
    @Published private(set) var isSavedBody = false
    @Published private(set) var isRevalidating = false
    private var operation: UInt64 = 0
    private var expiryTask: Task<Void, Never>?
    private var loadInFlight = false

    private let originalArticle: NewsArticle
    private let fetchArticle: FetchArticle

    func invalidate() {
        operation &+= 1
        expiryTask?.cancel()
        loadInFlight = false; isRevalidating = false; isSavedBody = false
        state = .preview(originalArticle.safeForReaderCache())
    }

    init(
        article: NewsArticle,
        fetchArticle: @escaping FetchArticle = { articleID, accessToken in
            try await BackendService.shared.fetchFeedArticle(id: articleID, accessToken: accessToken)
        }
    ) {
        let normalized = article
            .safeForReaderCache(includeVerifiedNativeBody: true)
            .normalizedForDisplay()
        originalArticle = normalized
        self.fetchArticle = fetchArticle
        state = normalized.verifiedNativeBody == nil ? .preview(normalized) : .ready(normalized)
        paragraphs = normalized.verifiedNativeBody.map(Self.paragraphs) ?? []
    }

    /// Loads a materialized detail at most once at a time. The explicit return
    /// value keeps cache mutation tied to an authenticated server response:
    /// verified native bodies are stored, accepted downgrades are evicted, and
    /// local fallbacks or failures do not renew or mutate the cache.
    @discardableResult
    func load(
        accessToken: String?,
        cachedDetail: NewsArticle? = nil,
        revalidate: Bool = false,
        isCurrent: @escaping @MainActor () -> Bool = { true },
        accept: @escaping @MainActor (ArticleReaderCacheDisposition) async -> Bool = { _ in true }
    ) async -> ArticleReaderCacheDisposition {
        guard !loadInFlight, isCurrent() else { return .none }
        loadInFlight = true
        operation &+= 1
        let intent = operation
        defer { if intent == operation { loadInFlight = false; isRevalidating = false } }
        let current = revalidate ? state.article.safeForReaderCache() : state.article

        switch current.readerRoute {
        case .source:
            state = .sourceAvailable(
                current,
                message: Self.sourceMessage(for: current)
            )
            return .none
        case .unavailable:
            state = .unavailable(current, message: "The original source link is unavailable.")
            return .none
        case .native:
            break
        }

        if current.verifiedNativeBody != nil {
            state = .ready(current)
            return .none
        }

        let candidate = current.mergingCompatibleCachedDetail(cachedDetail)
        let compatibleCachedDetail = candidate?.hasOfflinePermission() == true ? candidate : nil

        guard let accessToken = accessToken?.trimmingCharacters(in: .whitespacesAndNewlines),
              !accessToken.isEmpty else {
            if let compatibleCachedDetail {
                // This is an already account-scoped, TTL-bounded fallback. Do
                // not return it to the caller, which would refresh its TTL.
                state = .ready(compatibleCachedDetail)
                isSavedBody = true
                scheduleExpiry(compatibleCachedDetail)
                return .none
            }
            state = .authenticationRequired(
                current,
                message: "Sign in again to load the native article. The original source remains available."
            )
            return .none
        }

        isRevalidating = true
        if let compatibleCachedDetail {
            state = .ready(compatibleCachedDetail); isSavedBody = true
            scheduleExpiry(compatibleCachedDetail)
        } else { state = .loading(current) }

        do {
            let detail = try await fetchArticle(originalArticle.id, accessToken)
            try Task.checkCancellation()
            guard intent == operation, isCurrent() else { return .none }
            guard originalArticle.acceptsReaderDetail(detail) else {
                state = .failed(
                    current,
                    message: "The publisher returned mismatched article data. Please try again."
                )
                return .none
            }
            let merged = originalArticle.mergingReaderDetail(detail)

            if merged.verifiedNativeBody != nil {
                let accepted = await accept(.store(merged))
                guard intent == operation, isCurrent() else { return .none }
                guard accepted else {
                    state = .failed(current.safeForReaderCache(), message: "This article changed. Please reload your edition.")
                    return .none
                }
                state = .ready(merged)
                isSavedBody = false
                scheduleExpiry(merged)
                return .store(merged)
            } else if merged.originalSourceURL != nil {
                _ = await accept(.evict(articleID: originalArticle.id))
                guard intent == operation, isCurrent() else { return .none }
                expiryTask?.cancel()
                state = .sourceAvailable(
                    merged,
                    message: Self.sourceMessage(for: merged)
                )
                return .evict(articleID: originalArticle.id)
            } else {
                _ = await accept(.evict(articleID: originalArticle.id))
                guard intent == operation, isCurrent() else { return .none }
                expiryTask?.cancel()
                state = .unavailable(merged, message: "This article is currently unavailable.")
                return .evict(articleID: originalArticle.id)
            }
        } catch is CancellationError {
            guard intent == operation, isCurrent() else { return .none }
            state = current.verifiedNativeBody == nil ? .preview(current) : .ready(current)
        } catch {
            guard intent == operation, isCurrent() else { return .none }
            if Task.isCancelled {
                state = current.verifiedNativeBody == nil ? .preview(current) : .ready(current)
            } else if Self.isAuthenticationFailure(error) {
                _ = await accept(.evict(articleID: originalArticle.id))
                guard intent == operation, isCurrent() else { return .none }
                expiryTask?.cancel()
                state = .authenticationRequired(
                    current,
                    message: "Your session expired. Sign in again to load the native article."
                )
            } else if Self.isTimeoutFailure(error) {
                if let compatibleCachedDetail, compatibleCachedDetail.hasOfflinePermission() {
                    state = .ready(compatibleCachedDetail)
                } else {
                    state = .failed(
                        current,
                        message: "The article request timed out. Please try again."
                    )
                }
            } else if Self.isConnectionFailure(error) {
                if let compatibleCachedDetail, compatibleCachedDetail.hasOfflinePermission() {
                    state = .ready(compatibleCachedDetail)
                } else {
                    state = .offline(
                        current,
                        message: "Connect to load the native article. The headline and source remain available."
                    )
                }
            } else {
                state = .failed(current, message: "Couldn't load the article. Please try again.")
            }
        }
        return .none
    }

    private func scheduleExpiry(_ article: NewsArticle) {
        expiryTask?.cancel()
        // Online-only material is revalidated on activation and removed after five minutes.
        let seconds = article.hasOfflinePermission()
            ? min(86_400, article.presentation!.offlineValidUntil!.timeIntervalSinceNow) : 300
        expiryTask = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(max(0, seconds))) } catch { return }
            self?.expireDisplayedBody()
        }
    }

    /// Expiration removes display permission, not the independent request's identity.
    /// A current revalidation may still complete, but no fallback renews the old grant.
    func expireDisplayedBody() {
        let preview = state.article.safeForReaderCache()
        isSavedBody = false
        state = loadInFlight ? .loading(preview)
            : .failed(preview, message: "This saved article expired. Reload to check availability.")
    }

    static func isConnectionFailure(_ error: Error) -> Bool {
        let nsError = error as NSError
        guard nsError.domain == NSURLErrorDomain else { return false }
        return [
            NSURLErrorNotConnectedToInternet,
            NSURLErrorNetworkConnectionLost,
            NSURLErrorCannotFindHost,
            NSURLErrorCannotConnectToHost,
            NSURLErrorDNSLookupFailed,
            NSURLErrorInternationalRoamingOff,
            NSURLErrorDataNotAllowed
        ].contains(nsError.code)
    }

    static func isTimeoutFailure(_ error: Error) -> Bool {
        let nsError = error as NSError
        return nsError.domain == NSURLErrorDomain && nsError.code == NSURLErrorTimedOut
    }

    static func isAuthenticationFailure(_ error: Error) -> Bool {
        let nsError = error as NSError
        return nsError.domain == "BackendService" && [401, 403].contains(nsError.code)
    }

    static func sourceMessage(for article: NewsArticle) -> String {
        let hint = article.presentation?.accessHint?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        switch hint {
        case "subscription", "subscriber_only", "paywall", "subscription_may_be_required":
            return "The publisher may require a subscription to read this story."
        case "registration", "sign_in", "publisher_sign_in_required":
            return "The publisher may ask you to sign in to read this story."
        case "publisher_consent_required", "consent":
            return "The publisher may ask you to review its privacy or cookie choices before reading."
        case "metered":
            return "The publisher may count this story toward its free article limit."
        default:
            return "Read the complete story on the original publisher's website."
        }
    }
}
