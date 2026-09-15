import Foundation

struct ReaderIntent: Codable, Equatable, Identifiable {
    var id: String = UUID().uuidString.lowercased()
    var kind: String
    var label: String
    var query: String
    var priority: Double = 1
    var qualifiers: [String] = []
    var resolvedId: String?
    var expiresAt: String?
    var provenance: String = "explicit"
}

struct ReaderPolicy: Codable, Equatable, Identifiable {
    var id: String = UUID().uuidString.lowercased()
    var kind: String = "lexical"
    var value: String
    var scope: String = "topic"
    var expiresAt: String?
}

struct ReaderProfile: Codable, Equatable {
    var schemaVersion: Int = 3
    var intents: [ReaderIntent] = []
    var policies: [ReaderPolicy] = []
    var languages: [String] = []
    var depth: String = "balanced"
    var context: String = ""
}

struct ReaderEnvelope: Decodable {
    let profile: ReaderProfile
    let revision: Int
    let learningRevision: Int
    let generation: Int
    let migrationStatus: String
    var needsReview: Bool { migrationStatus == "needs_review" }

    private enum CodingKeys: String, CodingKey {
        case profile, revision, learningRevision, generation, migrationStatus, current
    }

    init(from decoder: Decoder) throws {
        let fields = try decoder.container(keyedBy: CodingKeys.self)
        // An idempotent retry can return its original receipt after a newer edit.
        // Acknowledge it without rolling displayed state back to that old snapshot.
        if let current = try fields.decodeIfPresent(ReaderEnvelope.self, forKey: .current) {
            self = current
            return
        }
        profile = try fields.decode(ReaderProfile.self, forKey: .profile)
        revision = try fields.decode(Int.self, forKey: .revision)
        learningRevision = try fields.decode(Int.self, forKey: .learningRevision)
        generation = try fields.decode(Int.self, forKey: .generation)
        migrationStatus = try fields.decode(String.self, forKey: .migrationStatus)
    }
}

/// Optional fields intentionally encode omission, while [] explicitly clears a collection.
struct ReaderPatch: Codable, Equatable {
    var intents: [ReaderIntent]?
    var policies: [ReaderPolicy]?
    var languages: [String]?
    var depth: String?
    var context: String?
}

struct ReaderMutation: Encodable {
    var operationId: String = UUID().uuidString.lowercased()
    let baseGeneration: Int
    let baseRevision: Int
    let patch: ReaderPatch
    var confirmMigration: Bool = false
}

struct ReaderProposal: Decodable, Identifiable {
    var id: String { operationId }
    let operationId: String
    let baseGeneration: Int
    let baseRevision: Int
    let patch: ReaderPatch
    let summary: String
}

enum ReaderEditor {
    /// Preserve rich intent identity/qualifiers and unexposed entity interests.
    static func intents(base: [ReaderIntent], topics: [String], current: [String], places: [String], utilities: [String]) -> [ReaderIntent] {
        let desired = topics.map { ($0, "topic", 1.0) } + current.map { ($0, "topic", 1.5) }
            + places.map { ($0, "place", 1.0) } + utilities.map { ($0, "utility", 1.0) }
        var result = base.filter { $0.kind == "entity" }
        var used = Set<String>()
        for (label, kind, priority) in desired {
            let key = kind + ":" + label
            guard used.insert(key).inserted else { continue }
            if var existing = base.first(where: { $0.kind == kind && $0.label == label }) {
                // Preserve fine-grained Tune weights unless the reader explicitly
                // moves a topic between ordinary and current-focus groups.
                if kind == "topic", (existing.priority > 1) != (priority > 1) {
                    existing.priority = priority
                }
                result.append(existing)
            } else {
                result.append(ReaderIntent(kind: kind, label: label, query: label, priority: priority))
            }
        }
        return result
    }

    static func policies(base: [ReaderPolicy], exclusions: [String]) -> [ReaderPolicy] {
        base.filter { $0.kind != "lexical" } + exclusions.map { label in
            base.first(where: { $0.kind == "lexical" && $0.value == label }) ?? ReaderPolicy(value: label)
        }
    }
}
