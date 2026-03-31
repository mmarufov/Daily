import XCTest
@testable import Daily

final class ChatV2ModelsTests: XCTestCase {
    func testStreamingEventDecodesLiveCoverageStatus() throws {
        let payload = """
        {"label":"Searching live coverage"}
        """.data(using: .utf8)!

        let event = try StreamingEvent.decode(event: "status", data: payload)

        switch event {
        case .status(let decoded):
            XCTAssertEqual(decoded.label, "Searching live coverage")
        default:
            XCTFail("Expected status")
        }
    }

    func testStreamingEventDecodesAnswerSectionDelta() throws {
        let payload = """
        {"index":1,"kind":"answer","delta":"Hello world"}
        """.data(using: .utf8)!

        let event = try StreamingEvent.decode(event: "section_delta", data: payload)

        switch event {
        case .sectionDelta(let decoded):
            XCTAssertEqual(decoded.index, 1)
            XCTAssertEqual(decoded.kind, .answer)
            XCTAssertEqual(decoded.delta, "Hello world")
        default:
            XCTFail("Expected section_delta")
        }
    }

    func testStreamingEventDecodesStructuredSectionDelta() throws {
        let payload = """
        {"index":2,"kind":"summary","delta":"Briefing text"}
        """.data(using: .utf8)!

        let event = try StreamingEvent.decode(event: "section_delta", data: payload)

        switch event {
        case .sectionDelta(let decoded):
            XCTAssertEqual(decoded.index, 2)
            XCTAssertEqual(decoded.kind, .summary)
            XCTAssertEqual(decoded.delta, "Briefing text")
        default:
            XCTFail("Expected section_delta")
        }
    }

    func testStreamingEventDecodesDonePayload() throws {
        let payload = """
        {
          "message": {
            "id": "assistant-1",
            "thread_id": "thread-1",
            "role": "assistant",
            "plain_text": "Direct answer",
            "blocks": [
              {
                "id": "answer-0",
                "kind": "answer",
                "heading": null,
                "text": "Big shift",
                "items": null
              }
            ],
            "follow_ups": [],
            "degraded": false,
            "created_at": "2026-03-30T12:00:00Z",
            "sources": []
          }
        }
        """.data(using: .utf8)!

        let event = try StreamingEvent.decode(event: "done", data: payload)

        switch event {
        case .done(let done):
            XCTAssertEqual(done.message.id, "assistant-1")
            XCTAssertEqual(done.message.blocks.first?.kind, .answer)
            XCTAssertTrue(done.message.sources.isEmpty)
        default:
            XCTFail("Expected done")
        }
    }

    func testChatIntentGroupsRemainStable() {
        XCTAssertEqual(ChatIntent.homeIntents, [.yourBriefing, .whatChangedToday, .whyThisMatters, .positiveSignal])
        XCTAssertEqual(ChatIntent.articleIntents, [.explainSimply, .bullVsBear, .whatsMissing, .whatToWatch])
        XCTAssertEqual(ChatIntent.positiveSignal.group, .home)
        XCTAssertEqual(ChatIntent.bullVsBear.group, .article)
    }
}
