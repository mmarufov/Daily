import XCTest
@testable import Daily

final class ReaderProfileTests: XCTestCase {
    func testPatchOmissionVersusExplicitClear() throws {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        let data = try encoder.encode(ReaderPatch(intents: [], context: ""))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual((object["intents"] as? [Any])?.count, 0)
        XCTAssertNil(object["policies"])
        XCTAssertEqual(object["context"] as? String, "")
    }

    func testEditorPreservesUnexposedIdentityQualifiersAndClearsTopics() {
        let entity = ReaderIntent(kind: "entity", label: "Apple", query: "Apple company", qualifiers: ["company"], resolvedId: "entity:apple")
        let topic = ReaderIntent(kind: "topic", label: "AI policy", query: "AI regulation affecting startups", priority: 0.7, qualifiers: ["startups"])
        let kept = ReaderEditor.intents(base: [entity, topic], topics: ["AI policy"], current: [], places: [], utilities: [])
        XCTAssertEqual(kept, [entity, topic])
        let cleared = ReaderEditor.intents(base: [entity, topic], topics: [], current: [], places: [], utilities: [])
        XCTAssertEqual(cleared, [entity])
    }

    func testPolicyEditorDoesNotDropPublisherBlock() {
        let publisher = ReaderPolicy(kind: "publisher", value: "publisher.example", scope: "source")
        let lexical = ReaderPolicy(value: "celebrity")
        XCTAssertEqual(ReaderEditor.policies(base: [publisher, lexical], exclusions: []), [publisher])
    }

    func testMovingTopicToCurrentFocusChangesPriorityWithoutLosingIdentity() {
        let topic = ReaderIntent(kind: "topic", label: "AI", query: "AI regulation", priority: 0.7)
        let focused = ReaderEditor.intents(base: [topic], topics: [], current: ["AI"], places: [], utilities: [])
        XCTAssertEqual(focused.first?.id, topic.id)
        XCTAssertEqual(focused.first?.query, topic.query)
        XCTAssertEqual(focused.first?.priority, 1.5)
        let ordinary = ReaderEditor.intents(base: focused, topics: ["AI"], current: [], places: [], utilities: [])
        XCTAssertEqual(ordinary.first?.priority, 1)
    }

    func testWireContractUsesCanonicalFieldNames() throws {
        let json = #"{"profile":{"schema_version":3,"intents":[],"policies":[],"languages":["tg"],"depth":"deep","context":"test"},"revision":2,"learning_revision":1,"generation":1,"migration_status":"needs_review","capabilities":{}}"#
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let envelope = try decoder.decode(ReaderEnvelope.self, from: Data(json.utf8))
        XCTAssertEqual(envelope.profile.languages, ["tg"])
        XCTAssertEqual(envelope.profile.depth, "deep")
        XCTAssertTrue(envelope.needsReview)
    }

    func testHistoricalReceiptReconcilesCurrentStateInsteadOfRollingBack() throws {
        let profile = #"{"schema_version":3,"intents":[],"policies":[],"languages":[],"depth":"balanced","context":""}"#
        let old = "\"profile\":\(profile),\"revision\":2,\"learning_revision\":1,\"generation\":1,\"migration_status\":\"ready\""
        let current = "{\"profile\":\(profile),\"revision\":5,\"learning_revision\":3,\"generation\":2,\"migration_status\":\"ready\"}"
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let result = try decoder.decode(ReaderEnvelope.self, from: Data("{\(old),\"current\":\(current)}".utf8))
        XCTAssertEqual(result.revision, 5)
        XCTAssertEqual(result.generation, 2)
    }
}
