//
//  ReadingEventTracker.swift
//  Daily
//
//  Tracks reading behavior and batches events for backend submission.
//  Events are accumulated locally and sent when the app goes to background.
//

import Foundation

@MainActor
@Observable
final class ReadingEventTracker {
    static let shared = ReadingEventTracker()

    struct ReadingEvent: Codable {
        var eventId: String = UUID().uuidString
        let articleId: String
        let type: String  // "impression", "tap", "read"
        let durationSeconds: Int?
        let feedRequestId: String?
        let position: Int?
        var readContentHash: String? = nil
    }

    private(set) var pendingEvents: [ReadingEvent] = []
    private var generation: UInt64 = 0
    private var isFlushing = false
    private let tokenProvider: @MainActor () -> String?
    private let submit: ([ReadingEvent], String) async throws -> Void

    init(
        tokenProvider: @escaping @MainActor () -> String? = { AuthService.shared.getAccessToken() },
        submit: @escaping ([ReadingEvent], String) async throws -> Void = {
            try await BackendService.shared.submitReadingEvents($0, accessToken: $1)
        }
    ) {
        self.tokenProvider = tokenProvider
        self.submit = submit
    }
    func logImpression(article: NewsArticle) {
        append(article: article, type: "impression", durationSeconds: nil)
    }

    func logTap(article: NewsArticle) {
        append(article: article, type: "tap", durationSeconds: nil)
    }

    func logRead(article: NewsArticle, durationSeconds: Int, nativeBodyWasDisplayed: Bool = true) {
        guard durationSeconds >= 5 else { return } // Dwell-time proxy, not proof of comprehension.
        append(article: article, type: "read", durationSeconds: durationSeconds,
               readContentHash: nativeBodyWasDisplayed ? article.readContentHash : nil)
    }

    /// S10 B1: a quick-back -- the reader opened this article and navigated
    /// away within seconds, never reaching the read dwell floor. A strong
    /// implicit negative the server folds into scoring as a small, bounded
    /// discount (see reward.QUICK_BACK_PENALTY); never treated as an
    /// explicit rejection like "not relevant" is.
    func logSkip(article: NewsArticle) {
        append(article: article, type: "skip", durationSeconds: nil)
    }

    private func append(article: NewsArticle, type: String, durationSeconds: Int?, readContentHash: String? = nil) {
        guard tokenProvider() != nil else { return }
        trimQueue()
        let receipt = article.deliveryReceipt
        pendingEvents.append(ReadingEvent(articleId: article.id, type: type,
            durationSeconds: durationSeconds, feedRequestId: receipt?.requestID, position: receipt?.position,
            readContentHash: readContentHash))
    }

    func logImpression(articleId: String, position: Int) {
        guard tokenProvider() != nil else { return }
        trimQueue()
        pendingEvents.append(ReadingEvent(
            articleId: articleId,
            type: "impression",
            durationSeconds: nil,
            feedRequestId: nil,
            position: nil
        ))
    }

    func logTap(articleId: String, position: Int? = nil) {
        guard tokenProvider() != nil else { return }
        trimQueue()
        pendingEvents.append(ReadingEvent(
            articleId: articleId,
            type: "tap",
            durationSeconds: nil,
            feedRequestId: nil,
            position: nil
        ))
    }

    func logRead(articleId: String, durationSeconds: Int) {
        guard tokenProvider() != nil else { return }
        trimQueue()
        guard durationSeconds >= 5 else { return }  // Dwell-time proxy only.
        pendingEvents.append(ReadingEvent(
            articleId: articleId,
            type: "read",
            durationSeconds: durationSeconds,
            feedRequestId: nil,
            position: nil
        ))
    }

    func flush() async {
        guard !isFlushing, let token = tokenProvider() else { return }
        let capturedGeneration = generation
        isFlushing = true
        defer { isFlushing = false }
        while !pendingEvents.isEmpty, capturedGeneration == generation, tokenProvider() == token {
            let events = Array(pendingEvents.prefix(100))
            pendingEvents.removeFirst(events.count)
            do {
                try await submit(events, token)
            } catch {
                // Never return an old account's batch to the current account's queue.
                if capturedGeneration == generation, tokenProvider() == token {
                    pendingEvents = Array((events + pendingEvents).prefix(500))
                }
                return
            }
        }
    }

    private func trimQueue() {
        if pendingEvents.count >= 500 { pendingEvents.removeFirst(pendingEvents.count - 499) }
    }

    /// Drop all queued events without submitting. Used on sign-out so the
    /// next user doesn't inherit the previous user's reading history.
    func discardPending() {
        generation &+= 1
        pendingEvents = []
    }
}
