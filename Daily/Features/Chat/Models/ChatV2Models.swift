//
//  ChatV2Models.swift
//  Daily
//

import Foundation

enum ChatThreadKind: String, Codable, Equatable {
    case today
    case manual
    case article
}

struct ChatThread: Identifiable, Codable, Equatable {
    let id: String
    let kind: ChatThreadKind
    let title: String
    let articleID: String?
    let articleTitle: String?
    let localDay: String?
    let lastMessagePreview: String?
    let messageCount: Int
    let createdAt: Date?
    let updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id
        case kind
        case title
        case articleID = "article_id"
        case articleTitle = "article_title"
        case localDay = "local_day"
        case lastMessagePreview = "last_message_preview"
        case messageCount = "message_count"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

enum AssistantBlockKind: String, Codable, Equatable {
    case answer
    case headline
    case summary
    case bulletList = "bullet_list"
    case whyItMatters = "why_it_matters"
    case timeline
    case watchlist
    case body
}

struct AssistantBlock: Identifiable, Codable, Equatable {
    let id: String
    let kind: AssistantBlockKind
    let heading: String?
    var text: String?
    var items: [String]?
}

struct SourceCard: Identifiable, Codable, Equatable {
    let articleId: String
    let title: String
    let summary: String?
    let source: String?
    let imageURL: String?
    let publishedAt: Date?
    let category: String?
    let url: String?

    var id: String { articleId }

    enum CodingKeys: String, CodingKey {
        case articleId = "article_id"
        case title
        case summary
        case source
        case imageURL = "image_url"
        case publishedAt = "published_at"
        case category
        case url
    }

    var asNewsArticle: NewsArticle {
        NewsArticle(
            id: articleId,
            title: title,
            summary: summary,
            content: nil,
            author: nil,
            source: source,
            imageURL: imageURL,
            publishedAt: publishedAt,
            category: category,
            url: url
        )
    }
}

enum ChatTurnRole: String, Codable, Equatable {
    case user
    case assistant
}

struct ChatTurn: Identifiable, Codable, Equatable {
    let id: String
    let threadID: String
    let role: ChatTurnRole
    var plainText: String
    var blocks: [AssistantBlock]
    var followUps: [String]
    var degraded: Bool
    let createdAt: Date?
    var sources: [SourceCard]

    enum CodingKeys: String, CodingKey {
        case id
        case threadID = "thread_id"
        case role
        case plainText = "plain_text"
        case blocks
        case followUps = "follow_ups"
        case degraded
        case createdAt = "created_at"
        case sources
    }

    var isUser: Bool {
        role == .user
    }

    static func optimisticUser(threadID: String, text: String) -> ChatTurn {
        ChatTurn(
            id: UUID().uuidString,
            threadID: threadID,
            role: .user,
            plainText: text,
            blocks: [],
            followUps: [],
            degraded: false,
            createdAt: Date(),
            sources: []
        )
    }

    static func optimisticAssistant(threadID: String) -> ChatTurn {
        ChatTurn(
            id: UUID().uuidString,
            threadID: threadID,
            role: .assistant,
            plainText: "",
            blocks: [],
            followUps: [],
            degraded: false,
            createdAt: Date(),
            sources: []
        )
    }
}

struct ChatThreadDetail: Codable, Equatable {
    let thread: ChatThread
    let messages: [ChatTurn]
}

struct CreateThreadRequest: Encodable {
    let kind: ChatThreadKind
    let title: String?
    let articleID: String?
    let articleTitle: String?
    let localDay: String?

    enum CodingKeys: String, CodingKey {
        case kind
        case title
        case articleID = "article_id"
        case articleTitle = "article_title"
        case localDay = "local_day"
    }
}

struct StreamMessageRequest: Encodable {
    let content: String?
    let intent: String?
}

enum ChatIntent: String, CaseIterable, Identifiable {
    case yourBriefing = "your_briefing"
    case whatChangedToday = "what_changed_today"
    case whyThisMatters = "why_this_matters"
    case positiveSignal = "positive_signal"
    case explainSimply = "explain_simply"
    case bullVsBear = "bull_vs_bear"
    case whatsMissing = "whats_missing"
    case whatToWatch = "what_to_watch"

    enum Group {
        case home
        case article
    }

    var id: String { rawValue }

    var group: Group {
        switch self {
        case .yourBriefing, .whatChangedToday, .whyThisMatters, .positiveSignal:
            return .home
        case .explainSimply, .bullVsBear, .whatsMissing, .whatToWatch:
            return .article
        }
    }

    var title: String {
        switch self {
        case .yourBriefing:
            return "Your Briefing"
        case .whatChangedToday:
            return "What Changed Today"
        case .whyThisMatters:
            return "Why This Matters"
        case .positiveSignal:
            return "Positive Signal"
        case .explainSimply:
            return "Explain Simply"
        case .bullVsBear:
            return "Bull vs Bear"
        case .whatsMissing:
            return "What's Missing"
        case .whatToWatch:
            return "What To Watch"
        }
    }

    var icon: String {
        switch self {
        case .yourBriefing:
            return "newspaper"
        case .whatChangedToday:
            return "arrow.triangle.2.circlepath"
        case .whyThisMatters:
            return "lightbulb"
        case .positiveSignal:
            return "sun.max"
        case .explainSimply:
            return "text.bubble"
        case .bullVsBear:
            return "arrow.left.arrow.right"
        case .whatsMissing:
            return "questionmark.bubble"
        case .whatToWatch:
            return "eye"
        }
    }

    var requestText: String {
        switch self {
        case .yourBriefing:
            return "Give me my briefing."
        case .whatChangedToday:
            return "What changed today?"
        case .whyThisMatters:
            return "Why does this matter?"
        case .positiveSignal:
            return "Show me the most credible positive signal."
        case .explainSimply:
            return "Explain this simply."
        case .bullVsBear:
            return "Give me the bull case and the bear case."
        case .whatsMissing:
            return "What's missing from this story?"
        case .whatToWatch:
            return "What should I watch next?"
        }
    }

    static var homeIntents: [ChatIntent] {
        [.yourBriefing, .whatChangedToday, .whyThisMatters, .positiveSignal]
    }

    static var articleIntents: [ChatIntent] {
        [.explainSimply, .bullVsBear, .whatsMissing, .whatToWatch]
    }
}

enum StreamingEvent {
    struct MetaPayload: Codable, Equatable {
        let thread: ChatThread
        let userMessageID: String
        let assistantMessageID: String
        let intent: String?

        enum CodingKeys: String, CodingKey {
            case thread
            case userMessageID = "user_message_id"
            case assistantMessageID = "assistant_message_id"
            case intent
        }
    }

    struct StatusPayload: Codable, Equatable {
        let label: String
    }

    struct SectionOpenPayload: Codable, Equatable {
        let index: Int
        let kind: AssistantBlockKind
        let heading: String?
    }

    struct SectionDeltaPayload: Codable, Equatable {
        let index: Int
        let kind: AssistantBlockKind
        let delta: String
    }

    struct SourcesPayload: Codable, Equatable {
        let sources: [SourceCard]
    }

    struct FollowUpsPayload: Codable, Equatable {
        let followUps: [String]

        enum CodingKeys: String, CodingKey {
            case followUps = "follow_ups"
        }
    }

    struct DonePayload: Codable, Equatable {
        let message: ChatTurn
    }

    struct ErrorPayload: Codable, Equatable {
        let detail: String
    }

    case meta(MetaPayload)
    case status(StatusPayload)
    case sectionOpen(SectionOpenPayload)
    case sectionDelta(SectionDeltaPayload)
    case sources(SourcesPayload)
    case followUps(FollowUpsPayload)
    case done(DonePayload)
    case error(ErrorPayload)

    static func decode(event: String, data: Data) throws -> StreamingEvent {
        let decoder = JSONDecoder.dailyChatDecoder
        switch event {
        case "meta":
            return .meta(try decoder.decode(MetaPayload.self, from: data))
        case "status":
            return .status(try decoder.decode(StatusPayload.self, from: data))
        case "section_open":
            return .sectionOpen(try decoder.decode(SectionOpenPayload.self, from: data))
        case "section_delta":
            return .sectionDelta(try decoder.decode(SectionDeltaPayload.self, from: data))
        case "sources":
            return .sources(try decoder.decode(SourcesPayload.self, from: data))
        case "follow_ups":
            return .followUps(try decoder.decode(FollowUpsPayload.self, from: data))
        case "done":
            return .done(try decoder.decode(DonePayload.self, from: data))
        case "error":
            return .error(try decoder.decode(ErrorPayload.self, from: data))
        default:
            throw NSError(domain: "StreamingEvent", code: -1, userInfo: [
                NSLocalizedDescriptionKey: "Unknown streaming event: \(event)"
            ])
        }
    }
}

extension JSONDecoder {
    static let dailyChatDecoder: JSONDecoder = {
        let decoder = JSONDecoder()
        let withFractional = ISO8601DateFormatter()
        withFractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let withoutFractional = ISO8601DateFormatter()
        withoutFractional.formatOptions = [.withInternetDateTime]
        let microFmt = DateFormatter()
        microFmt.locale = Locale(identifier: "en_US_POSIX")
        microFmt.dateFormat = "yyyy-MM-dd'T'HH:mm:ss.SSSSSSXXXXX"

        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let string = try container.decode(String.self)
            if let date = withFractional.date(from: string) { return date }
            if let date = withoutFractional.date(from: string) { return date }
            if let date = microFmt.date(from: string) { return date }
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Cannot decode date: \(string)")
        }
        return decoder
    }()
}
