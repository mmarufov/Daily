import Foundation
import Combine
import UIKit
import os

extension Notification.Name {
    static let deliveryMembershipChanged = Notification.Name("Daily.deliveryMembershipChanged")
}

@MainActor
final class NewsViewModel: ObservableObject {
    enum SetupPhase {
        case discovering, building, rebuilding
        var title: String { self == .discovering ? "Finding sources" : "Updating your feed" }
        var subtitle: String { "Preparing an edition for your interests." }
    }
    struct Session: Equatable {
        let userID: String
        let token: String
        let generation: UInt64
    }
    struct Dependencies {
        var session: () -> Session?
        var fetch: (String) async throws -> BackendService.FeedResponse
        var build: (String) async throws -> BackendService.FeedResponse
        var discover: (String) async throws -> Void
        var load: (String) async -> CachedEditionLoad
        var store: ([NewsArticle], DeliveryMetadata?, String, UInt64) async throws -> ArticleCacheMutationDisposition
        var invalidate: () -> Void
        var now: () -> Date = Date.init
        static var live: Self {
            Self(session: {
                let auth = AuthService.shared
                guard auth.isAuthenticated, let user = auth.currentUser?.id,
                      let token = auth.getAccessToken() else { return nil }
                return Session(userID: user, token: token, generation: auth.sessionGeneration)
            }, fetch: { try await BackendService.shared.fetchFeedState(accessToken: $0) },
            build: { try await BackendService.shared.buildFeed(accessToken: $0) },
            discover: { _ = try await BackendService.shared.discoverSources(accessToken: $0) },
            load: { await BackgroundNewsFetcher.shared.loadCachedEdition(forUserID: $0) },
            store: { try await BackgroundNewsFetcher.shared.storeEdition($0, delivery: $1, forUserID: $2, sessionGeneration: $3) },
            invalidate: { BackgroundNewsFetcher.shared.clearCache() })
        }
    }
    @Published private(set) var articles: [NewsArticle] = []
    @Published private(set) var isLoading = false
    @Published private(set) var isRefreshing = false
    @Published private(set) var isSettingUp = false
    @Published private(set) var setupPhase: SetupPhase?
    @Published private(set) var setupDetailText: String?
    @Published var errorMessage: String?
    @Published private(set) var lastFetchDate: Date?
    @Published private(set) var editionPublishedAt: Date?
    @Published private(set) var isSavedEdition = false
    @Published private(set) var deliveryStatusLabel: String?
    var canAttributeImpressions: Bool { !isSavedEdition && delivery != nil }
    private let dependencies: Dependencies
    private var delivery: DeliveryMetadata?
    private var immutableCards: [NewsArticle] = []
    private var operation: UInt64 = 0
    private var activeTask: Task<Void, Never>?
    private var expiryTask: Task<Void, Never>?
    private var cancellables = Set<AnyCancellable>()
    private let logger = Logger(subsystem: "com.daily.app", category: "delivery")

    init(dependencies: Dependencies? = nil, startsAutomatically: Bool = true) {
        self.dependencies = dependencies ?? .live
        for name in [Notification.Name.readerPreferencesCommitted, .preferencesChanged] {
            NotificationCenter.default.publisher(for: name).receive(on: DispatchQueue.main)
                .sink { [weak self] _ in self?.invalidateForReaderChange() }.store(in: &cancellables)
        }
        NotificationCenter.default.publisher(for: .onboardingCompleted).receive(on: DispatchQueue.main)
            .sink { [weak self] _ in Task { await self?.loadFeed() } }.store(in: &cancellables)
        if startsAutomatically { Task { [weak self] in await self?.loadFeed() } }
    }

    func loadFeed(forceRefresh: Bool = false) async {
        guard let session = dependencies.session() else { return }
        if let activeTask, !forceRefresh { await activeTask.value; return }
        activeTask?.cancel()
        operation &+= 1
        let intent = operation
        let task = Task<Void, Never> { [weak self] in
            await self?.performLoad(session, intent: intent, explicit: forceRefresh)
        }
        activeTask = task
        await task.value
        if intent == operation { activeTask = nil }
    }
    func refreshFeed() async { await loadFeed(forceRefresh: true) }
    func suspend() {
        operation &+= 1; activeTask?.cancel(); activeTask = nil
        isLoading = false; isRefreshing = false; isSettingUp = false; setupPhase = nil
    }
    func foregroundRefresh() async {
        if let delivery, dependencies.now() >= delivery.validUntil { showSaved() }
        guard lastFetchDate.map({ dependencies.now().timeIntervalSince($0) < 30 }) != true else { return }
        await loadFeed()
    }
    func rebuildAfterPreferenceChange() async {
        invalidateForReaderChange(reload: false)
        await loadFeed(forceRefresh: true)
    }
    func invalidateForReaderChange(reload: Bool = true) {
        operation &+= 1
        activeTask?.cancel(); activeTask = nil; expiryTask?.cancel()
        dependencies.invalidate()
        NotificationCenter.default.post(name: .deliveryMembershipChanged, object: [NewsArticle]())
        articles = []; immutableCards = []; delivery = nil
        editionPublishedAt = nil; lastFetchDate = nil; isSavedEdition = false
        isLoading = false; isRefreshing = false; isSettingUp = false; setupPhase = nil
        deliveryStatusLabel = "Interests changed — updating edition"
        if reload { Task { [weak self] in await self?.loadFeed(forceRefresh: true) } }
    }
    private func current(_ session: Session, _ intent: UInt64) -> Bool {
        !Task.isCancelled && intent == operation && dependencies.session() == session
    }
    private func performLoad(_ session: Session, intent: UInt64, explicit: Bool) async {
        os_signpost(.event, log: OSLog(subsystem: "com.daily.app", category: "delivery"), name: "FeedLoadStarted")
        isRefreshing = explicit; isLoading = articles.isEmpty; errorMessage = nil
        defer {
            if intent == operation {
                isLoading = false; isRefreshing = false; isSettingUp = false; setupPhase = nil
            }
        }
        if delivery == nil && immutableCards.isEmpty {
            let cached = await dependencies.load(session.userID)
            guard current(session, intent) else { return }
            if case .saved(let edition) = cached {
                delivery = edition.delivery; immutableCards = edition.articles
                editionPublishedAt = edition.delivery?.publishedAt ?? edition.receivedAt
                showSaved(); isLoading = false
            }
        }
        do {
            var response = try await dependencies.fetch(session.token)
            guard current(session, intent) else { return }
            if response.status == .needsBuild || response.status == .needsDiscovery {
                isSettingUp = articles.isEmpty
                if response.status == .needsDiscovery {
                    setupPhase = .discovering
                    try await dependencies.discover(session.token)
                    guard current(session, intent) else { return }
                }
                setupPhase = .building
                response = try await dependencies.build(session.token)
                guard current(session, intent) else { return }
            }
            for delay in [2, 4, 8] where response.status == .building {
                deliveryStatusLabel = "Preparing edition"
                try await Task.sleep(for: .seconds(delay))
                guard current(session, intent) else { return }
                response = try await dependencies.fetch(session.token)
            }
            guard current(session, intent) else { return }
            switch response.status {
            case .ready: try await accept(response, session: session, intent: intent)
            case .needsReaderReview:
                invalidateForReaderChange(reload: false)
                errorMessage = "Review your interests in Personalization settings to continue."
                deliveryStatusLabel = "Review required"
            case .building: errorMessage = "Your edition is still being prepared. Pull down to check again."
            case .unavailable: errorMessage = "Your feed is temporarily unavailable. Pull down to retry."
            case .needsBuild, .needsDiscovery: errorMessage = "Your edition isn't ready yet. Pull down to retry."
            }
        } catch {
            guard current(session, intent), !(error is CancellationError) else { return }
            if ArticleReaderModel.isAuthenticationFailure(error) {
                invalidateForReaderChange(reload: false)
                if dependencies.session() == session { AuthService.shared.signOut() }
            } else {
                showSaved(); errorMessage = "Couldn't update your edition. Pull down to retry."
            }
        }
    }
    private func accept(_ response: BackendService.FeedResponse, session: Session, intent: UInt64) async throws {
        guard DeliveryValidation.accepts(response.delivery, articles: response.articles, requestID: response.feedRequestId),
              response.delivery?.canReplace(delivery) ?? (delivery == nil) else { throw URLError(.cannotParseResponse) }
        let cards = response.articles.map { $0.safeForReaderCache() }
        if let next = response.delivery, let previous = delivery, next.sequence == previous.sequence,
           !DeliveryValidation.immutableArticlesEqual(cards, immutableCards) { throw URLError(.cannotParseResponse) }
        let result = try await dependencies.store(cards, response.delivery, session.userID, session.generation)
        guard current(session, intent), result == .stored || result == .unchanged else { return }
        delivery = response.delivery; immutableCards = cards; lastFetchDate = dependencies.now()
        NotificationCenter.default.post(name: .deliveryMembershipChanged, object: cards)
        editionPublishedAt = delivery?.publishedAt ?? lastFetchDate
        isSavedEdition = delivery == nil
        articles = isSavedEdition ? cards.map { $0.withoutFeedReceipt().normalizedForDisplay() } : cards.map { $0.normalizedForDisplay() }
        deliveryStatusLabel = isSavedEdition ? "Saved edition · freshness unverified" : (cards.isEmpty ? "No matching stories" : "Up to date")
        logger.info("edition_accepted cards=\(cards.count, privacy: .public) versioned=\(self.delivery != nil, privacy: .public)")
        scheduleExpiry()
    }
    private func showSaved() {
        isSavedEdition = true
        articles = immutableCards.map { $0.withoutFeedReceipt().normalizedForDisplay() }
        deliveryStatusLabel = "Saved edition · reconnect to update"
    }
    private func scheduleExpiry() {
        expiryTask?.cancel()
        guard let delivery else { return }
        let remaining = min(delivery.validUntil.timeIntervalSince(delivery.validatedAt),
                            delivery.validUntil.timeIntervalSince(dependencies.now()))
        if remaining <= 0 { showSaved(); return }
        expiryTask = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(remaining)) } catch { return }
            self?.showSaved()
        }
    }
    func submitFeedback(for article: NewsArticle, action: String, position: Int? = nil) async {
        guard let session = dependencies.session() else { return }
        do {
            try await ReaderFeedbackStore.shared.submit(article: article, action: action, position: position)
            guard dependencies.session() == session else { return }
            if action == "hide_source" || action == "not_relevant" {
                // No authoritative source ID on legacy cards: invalidate rather than guess.
                invalidateForReaderChange()
            } else if action == "less_like_this" { articles.removeAll { $0.id == article.id } }
        } catch {
            guard dependencies.session() == session else { return }
            errorMessage = "Couldn't save your feedback. Please retry."
        }
    }
}
