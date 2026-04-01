//
//  ReadingEventTracker.swift
//  Daily
//
//  Tracks reading behavior and batches events for backend submission.
//  Events are accumulated locally and sent when the app goes to background.
//

import Foundation

@Observable
final class ReadingEventTracker {
    static let shared = ReadingEventTracker()

    struct ReadingEvent: Codable {
        let articleId: String
        let type: String  // "impression", "tap", "read"
        let durationSeconds: Int?
        let feedRequestId: String?
        let position: Int?
    }

    private(set) var pendingEvents: [ReadingEvent] = []
    private var currentFeedRequestId: String?
    var feedRequestId: String? { currentFeedRequestId }

    func setFeedRequestId(_ id: String) {
        currentFeedRequestId = id
    }

    func logImpression(articleId: String, position: Int) {
        pendingEvents.append(ReadingEvent(
            articleId: articleId,
            type: "impression",
            durationSeconds: nil,
            feedRequestId: currentFeedRequestId,
            position: position
        ))
    }

    func logTap(articleId: String) {
        pendingEvents.append(ReadingEvent(
            articleId: articleId,
            type: "tap",
            durationSeconds: nil,
            feedRequestId: currentFeedRequestId,
            position: nil
        ))
    }

    func logRead(articleId: String, durationSeconds: Int) {
        guard durationSeconds >= 5 else { return }  // Min 5s = actual read
        pendingEvents.append(ReadingEvent(
            articleId: articleId,
            type: "read",
            durationSeconds: durationSeconds,
            feedRequestId: currentFeedRequestId,
            position: nil
        ))
    }

    func flush() async {
        guard !pendingEvents.isEmpty else { return }
        guard let token = AuthService.shared.getAccessToken() else { return }

        let events = pendingEvents
        pendingEvents = []

        do {
            try await BackendService.shared.submitReadingEvents(events, accessToken: token)
        } catch {
            // Re-queue failed events for next flush (max 500 to prevent unbounded growth)
            pendingEvents = (events + pendingEvents).suffix(500).map { $0 }
        }
    }
}
