import Foundation

/// Bounded account-owned retry receipts, not a second personalization model.
@MainActor
final class ReaderFeedbackStore {
    static let shared = ReaderFeedbackStore()
    private let key = "daily.reader.feedback.pending.v1"
    private var inFlight = Set<String>()

    private struct Pending: Codable {
        let eventID: String
        let userID: String
        let articleID: String
        let action: String
        let feedRequestID: String?
        let readerGeneration: Int?
        let position: Int?
        let createdAt: Date
    }

    private func load(userID: String) -> [Pending] {
        guard let data = UserDefaults.standard.data(forKey: key),
              let values = try? JSONDecoder().decode([Pending].self, from: data) else { return [] }
        return values.filter { $0.userID == userID && Date().timeIntervalSince($0.createdAt) < 7 * 86_400 }
    }

    private func persist(_ values: [Pending]) {
        if let data = try? JSONEncoder().encode(Array(values.suffix(100))) {
            UserDefaults.standard.set(data, forKey: key)
        }
    }

    func clear() {
        UserDefaults.standard.removeObject(forKey: key)
        inFlight = []
    }

    func submit(article: NewsArticle, action: String, position: Int?) async throws {
        let auth = AuthService.shared
        guard let userID = auth.currentUser?.id, let token = auth.getAccessToken() else { throw ReaderClientError.authenticationRequired }
        let session = auth.sessionGeneration
        let feedRequestID = article.deliveryReceipt?.requestID
        var values = load(userID: userID)
        let receipt = values.first {
            $0.articleID == article.id && $0.action == action && $0.feedRequestID == feedRequestID && $0.readerGeneration == article.readerGeneration
        } ?? Pending(eventID: UUID().uuidString, userID: userID, articleID: article.id, action: action,
                     feedRequestID: feedRequestID,
                     readerGeneration: article.readerGeneration, position: article.deliveryReceipt?.position, createdAt: Date())
        guard !inFlight.contains(receipt.eventID) else { throw CancellationError() }
        if !values.contains(where: { $0.eventID == receipt.eventID }) { values.append(receipt); persist(values) }
        inFlight.insert(receipt.eventID)
        defer { inFlight.remove(receipt.eventID) }
        do {
            try await BackendService.shared.submitFeedFeedback(
                articleID: receipt.articleID, action: receipt.action, accessToken: token,
                feedRequestID: receipt.feedRequestID, position: receipt.position,
                eventID: receipt.eventID, readerGeneration: receipt.readerGeneration
            )
            guard session == auth.sessionGeneration else { throw CancellationError() }
            persist(load(userID: userID).filter { $0.eventID != receipt.eventID })
        } catch {
            guard session == auth.sessionGeneration else { throw CancellationError() }
            if (error as NSError).code == 409 || (error as NSError).code == 422 {
                persist(load(userID: userID).filter { $0.eventID != receipt.eventID })
            }
            throw error
        }
    }
}
