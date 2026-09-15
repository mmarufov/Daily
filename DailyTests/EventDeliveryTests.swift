import XCTest
@testable import Daily

@MainActor
final class EventDeliveryTests: XCTestCase {
    private let now = Date(timeIntervalSince1970: 1_783_684_800) // Fixed replay clock.

    private func wire(_ date: Date) -> String {
        ISO8601DateFormatter().string(from: date)
    }

    private func metadata(_ changes: [String: Any] = [:]) -> [String: Any] {
        var value: [String: Any] = [
            "event_id": "event-a", "event_version": 2, "assessment_id": "assessment-a",
            "assessment_version": String(repeating: "a", count: 64),
            "development_id": "development-a", "development_version": 1,
            "tier": "world_critical", "as_of": wire(now.addingTimeInterval(-60)),
            "valid_until": wire(now.addingTimeInterval(300))
        ]
        changes.forEach { value[$0.key] = $0.value }
        return value
    }

    private func article(metadata event: Any? = nil, role: String? = "world_critical") throws -> NewsArticle {
        var value: [String: Any] = ["id": "article-a", "title": "A  source\nreport", "summary": "Original summary",
            "url": "https://publisher.com/article", "why_now": "Current development"]
        value["feed_role"] = role
        value["event_delivery"] = event
        let decoder = JSONDecoder()
        decoder.userInfo[.eventDeliveryValidationTime] = now
        return try decoder.decode(NewsArticle.self, from: JSONSerialization.data(withJSONObject: value))
    }

    func testTypedMetadataAndExplicitExpiryBoundary() throws {
        let result = try article(metadata: metadata())
        XCTAssertEqual(result.eventDelivery?.eventID, "event-a")
        XCTAssertEqual(result.eventDelivery?.eventVersion, 2)
        XCTAssertEqual(result.eventDelivery?.developmentVersion, 1)
        XCTAssertNotNil(result.currentEventDelivery(at: now))
        XCTAssertNotNil(result.currentEventDelivery(at: now.addingTimeInterval(299)))
        XCTAssertNil(result.currentEventDelivery(at: now.addingTimeInterval(300)))
        XCTAssertNil(result.currentEventDelivery(at: now.addingTimeInterval(-61)))
        XCTAssertNil(result.currentEventDelivery(at: Date(timeIntervalSinceReferenceDate: .infinity)))
    }

    func testMalformedMetadataNeverMakesSourceArticleUnreadable() throws {
        let malformed: [Any] = [true, 7, "invalid", [:], metadata(["event_id": " "]),
            metadata(["event_version": true]), metadata(["event_version": 0]),
            metadata(["event_version": 1.5]), metadata(["development_version": -1]),
            metadata(["assessment_version": "not-a-hash"]), metadata(["tier": "routine"]),
            metadata(["as_of": "2026-02-30T10:00:00Z"]), metadata(["as_of": "2026-09-06T10:00:00"]),
            metadata(["valid_until": wire(now.addingTimeInterval(100_000))])]
        for item in malformed {
            let result = try article(metadata: item)
            XCTAssertNil(result.eventDelivery)
            XCTAssertNil(result.feedRole)
            XCTAssertNil(result.whyNow)
            XCTAssertEqual(result.id, "article-a")
            XCTAssertEqual(result.readerRoute, .source(URL(string: "https://publisher.com/article")!))
        }
    }

    func testFutureAndExpiredMetadataDroppedAtDecode() throws {
        for changes in [["as_of": wire(now.addingTimeInterval(1))],
                        ["valid_until": wire(now)], ["valid_until": wire(now.addingTimeInterval(-1))]] {
            let result = try article(metadata: metadata(changes))
            XCTAssertNil(result.eventDelivery)
            XCTAssertNil(result.feedRole)
            XCTAssertNotNil(result.originalSourceURL)
        }
    }

    func testMicrosecondFutureAndOverlongValidityCannotRoundIntoAcceptance() throws {
        let future = String(wire(now).dropLast()) + ".000123Z"
        XCTAssertNil(try article(metadata: metadata(["as_of": future])).eventDelivery)
        let overlong = String(wire(now.addingTimeInterval(86_340)).dropLast()) + ".000123Z"
        XCTAssertNil(try article(metadata: metadata(["valid_until": overlong])).eventDelivery)
    }

    func testOrdinaryLegacyAndNullMetadataRemainCompatible() throws {
        for item: Any? in [nil, NSNull()] {
            let result = try article(metadata: item, role: "relevant")
            XCTAssertNil(result.eventDelivery)
            XCTAssertEqual(result.feedRole, "relevant")
        }
        XCTAssertNil(try article(role: "world_critical").feedRole)
    }

    func testNormalizationPreservesCurrentButDropsExpiredPriority() throws {
        let original = try article(metadata: metadata())
        let current = original.normalizedForDisplay(at: now)
        XCTAssertEqual(current.eventDelivery, original.eventDelivery)
        XCTAssertEqual(current.title, "A source report")
        let expired = original.normalizedForDisplay(at: now.addingTimeInterval(300))
        XCTAssertNil(expired.eventDelivery)
        XCTAssertNil(expired.feedRole)
        XCTAssertNil(expired.whyNow)
        XCTAssertEqual(expired.summary, original.summary)
    }

    func testReaderDetailCannotIntroduceOrRenewPriority() throws {
        let original = try article(metadata: metadata())
        let detail = try article(metadata: metadata(["valid_until": wire(now.addingTimeInterval(1000))]))
        XCTAssertEqual(original.mergingReaderDetail(detail, at: now).eventDelivery, original.eventDelivery)
        XCTAssertNil(original.mergingReaderDetail(detail, at: now.addingTimeInterval(300)).eventDelivery)
        let ordinary = try article(role: "relevant")
        XCTAssertNil(ordinary.mergingReaderDetail(detail, at: now).eventDelivery)
    }

    func testReaderCacheAlwaysStoresOrdinaryArticleNotPriority() throws {
        let original = try article(metadata: metadata())
        for includeBody in [false, true] {
            let cached = original.safeForReaderCache(includeVerifiedNativeBody: includeBody)
            XCTAssertNil(cached.eventDelivery)
            XCTAssertNil(cached.feedRole)
            XCTAssertNil(cached.whyNow)
            XCTAssertEqual(cached.originalSourceURL, original.originalSourceURL)
            XCTAssertEqual(cached.summary, original.summary)
            let encoded = try JSONEncoder().encode(cached)
            let values = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
            XCTAssertNil(values["event_delivery"])
        }
    }

    func testMetadataRoundTripPreservesExactWirePrecision() throws {
        var value = metadata()
        let prefix = String(wire(now.addingTimeInterval(-60)).dropLast())
        value["as_of"] = prefix + ".123456Z"
        let original = try article(metadata: value)
        let encoded = try JSONEncoder().encode(original)
        let values = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        let restored = try XCTUnwrap(values["event_delivery"] as? [String: Any])
        XCTAssertEqual(restored["as_of"] as? String, value["as_of"] as? String)
        XCTAssertEqual(restored["valid_until"] as? String, value["valid_until"] as? String)
    }
}
