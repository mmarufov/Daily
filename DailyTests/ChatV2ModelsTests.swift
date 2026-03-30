import XCTest
@testable import Daily

final class ChatV2ModelsTests: XCTestCase {
    func testStreamingEventDecodesSectionDelta() throws {
        let payload = """
        {"index":1,"kind":"summary","delta":"Hello world"}
        """.data(using: .utf8)!

        let event = try StreamingEvent.decode(event: "section_delta", data: payload)

        switch event {
        case .sectionDelta(let decoded):
            XCTAssertEqual(decoded.index, 1)
            XCTAssertEqual(decoded.kind, .summary)
            XCTAssertEqual(decoded.delta, "Hello world")
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
            "plain_text": "Headline\\nSummary",
            "blocks": [
              {
                "id": "headline-0",
                "kind": "headline",
                "heading": "Headline",
                "text": "Big shift",
                "items": null
              }
            ],
            "follow_ups": ["What changed next?"],
            "degraded": false,
            "created_at": "2026-03-30T12:00:00Z",
            "sources": [
              {
                "article_id": "article-1",
                "title": "Major shift",
                "summary": "Summary",
                "source": "Daily",
                "image_url": null,
                "published_at": "2026-03-30T11:00:00Z",
                "category": "technology",
                "url": "https://example.com/story"
              }
            ]
          }
        }
        """.data(using: .utf8)!

        let event = try StreamingEvent.decode(event: "done", data: payload)

        switch event {
        case .done(let done):
            XCTAssertEqual(done.message.id, "assistant-1")
            XCTAssertEqual(done.message.blocks.first?.kind, .headline)
            XCTAssertEqual(done.message.sources.first?.articleId, "article-1")
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
