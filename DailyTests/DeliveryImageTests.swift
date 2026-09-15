import XCTest
import UIKit
@testable import Daily

@MainActor
final class DeliveryImageTests: XCTestCase {
    private func png() -> Data {
        UIGraphicsImageRenderer(size: CGSize(width: 200, height: 100)).pngData { context in
            UIColor.blue.setFill()
            context.fill(CGRect(x: 0, y: 0, width: 200, height: 100))
        }
    }

    private func service() -> ImageCacheService {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [DeliveryImageProtocol.self]
        return ImageCacheService(configuration: configuration)
    }

    override func tearDown() {
        DeliveryImageProtocol.reset(data: Data())
        super.tearDown()
    }

    func testDownsamplesWithoutFullSizeImage() throws {
        let image = try ImageCacheService.downsample(png(), pixels: 40)
        XCTAssertEqual(image.cgImage?.width, 40)
        XCTAssertEqual(image.cgImage?.height, 20)
    }

    func testRejectsInvalidAndOversizedCompressedData() {
        XCTAssertThrowsError(try ImageCacheService.downsample(Data("<html>bad</html>".utf8), pixels: 80))
        XCTAssertThrowsError(try ImageCacheService.downsample(Data(count: ImageCacheService.maximumBytes + 1), pixels: 80))
    }

    func testHTTPFreshnessCannotBeExtendedByDecodedCache() throws {
        let date = Date(timeIntervalSince1970: 0)
        func response(_ control: String, age: String = "0") -> HTTPURLResponse {
            HTTPURLResponse(url: URL(string: "https://images.example/test")!, statusCode: 200,
                            httpVersion: nil, headerFields: ["Cache-Control": control, "Age": age,
                                "Date": "Thu, 01 Jan 1970 00:00:00 GMT"])!
        }
        XCTAssertEqual(ImageCacheService.decodedFreshness(response: response("max-age=60"), now: date.addingTimeInterval(10)), 50)
        XCTAssertEqual(ImageCacheService.decodedFreshness(response: response("max-age=60", age: "55"), now: date), 5)
        XCTAssertEqual(ImageCacheService.decodedFreshness(response: response("max-age=60"), now: date.addingTimeInterval(61)), 0)
        XCTAssertEqual(ImageCacheService.decodedFreshness(response: response("no-store, max-age=60"), now: date), 0)
        XCTAssertEqual(ImageCacheService.decodedFreshness(response: response("no-cache, max-age=60"), now: date), 0)
    }

    func testDuplicateRequestsCoalesce() async throws {
        DeliveryImageProtocol.reset(data: png())
        let loader = service()
        let url = URL(string: "https://images.example/coalesce")!
        async let first = loader.image(url: url, pixelSize: 40)
        async let second = loader.image(url: url, pixelSize: 40)
        let images = try await (first, second)
        XCTAssertEqual(images.0.cgImage?.width, 40)
        XCTAssertEqual(images.1.cgImage?.width, 40)
        XCTAssertEqual(DeliveryImageProtocol.requestCount, 1)
    }

    func testRejectsHTTPErrorHTMLAndDeclaredOversize() async {
        for (status, mime, length) in [(404, "image/png", "1"), (200, "text/html", "1"),
                                      (200, "image/png", "6000000")] {
            DeliveryImageProtocol.reset(data: png(), status: status, mime: mime, length: length)
            do {
                _ = try await service().image(url: URL(string: "https://images.example/reject")!, pixelSize: 40)
                XCTFail("Invalid image response accepted")
            } catch { }
        }
    }

    func testClearFencesInFlightResultAndAllowsNewRequest() async throws {
        DeliveryImageProtocol.reset(data: png())
        let loader = service()
        let url = URL(string: "https://images.example/clear")!
        let old = Task { try await loader.image(url: url, pixelSize: 40) }
        await DeliveryImageProtocol.waitForRequests(1)
        loader.clearCache()
        do { _ = try await old.value; XCTFail("Old owner received image") } catch { }
        let image = try await loader.image(url: url, pixelSize: 40)
        XCTAssertEqual(image.cgImage?.width, 40)
        XCTAssertEqual(DeliveryImageProtocol.requestCount, 2)
    }

    func testCancelOneSubscriberDoesNotCancelOther() async throws {
        DeliveryImageProtocol.reset(data: png())
        let loader = service()
        let url = URL(string: "https://images.example/partial-cancel")!
        let first = Task { try await loader.image(url: url, pixelSize: 40) }
        let second = Task { try await loader.image(url: url, pixelSize: 40) }
        await DeliveryImageProtocol.waitForRequests(1)
        first.cancel()
        do { _ = try await first.value; XCTFail("Canceled subscriber received image") } catch { }
        let image = try await second.value
        XCTAssertEqual(image.cgImage?.width, 40)
        XCTAssertEqual(DeliveryImageProtocol.requestCount, 1)
    }

    func testCancelledLastSubscriberCanImmediatelyRequestSameKey() async throws {
        DeliveryImageProtocol.reset(data: png())
        let loader = service()
        let url = URL(string: "https://images.example/retry")!
        let first = Task { try await loader.image(url: url, pixelSize: 40) }
        await DeliveryImageProtocol.waitForRequests(1)
        first.cancel()
        do { _ = try await first.value; XCTFail("Canceled subscriber received image") } catch { }
        let result = try await loader.image(url: url, pixelSize: 40)
        XCTAssertEqual(result.cgImage?.width, 40)
    }

    func testNoMoreThanFourActiveDownloads() async throws {
        DeliveryImageProtocol.reset(data: png())
        let loader = service()
        try await withThrowingTaskGroup(of: Void.self) { group in
            for index in 0..<9 {
                group.addTask {
                    _ = try await loader.image(url: URL(string: "https://images.example/\(index)")!, pixelSize: 40)
                }
            }
            try await group.waitForAll()
        }
        XCTAssertEqual(DeliveryImageProtocol.requestCount, 9)
        XCTAssertLessThanOrEqual(DeliveryImageProtocol.peakCount, 4)
    }

    func testDwellRequiresContinuousEligibleSecondAndEmitsOnce() {
        var dwell = ImpressionDwell()
        dwell.update(visible: true, eligible: true, at: .zero)
        XCTAssertFalse(dwell.consume(at: .milliseconds(999)))
        dwell.update(visible: false, eligible: true, at: .milliseconds(999))
        XCTAssertFalse(dwell.consume(at: .seconds(4)))
        dwell.update(visible: true, eligible: true, at: .seconds(5))
        XCTAssertFalse(dwell.consume(at: .milliseconds(5999)))
        XCTAssertTrue(dwell.consume(at: .seconds(6)))
        XCTAssertFalse(dwell.consume(at: .seconds(7)))
    }

    func testInactiveAndSavedEditionDoNotAccumulateDwell() {
        var dwell = ImpressionDwell()
        dwell.update(visible: true, eligible: false, at: .zero)
        XCTAssertFalse(dwell.consume(at: .seconds(10)))
        dwell.update(visible: true, eligible: true, at: .seconds(10))
        dwell.update(visible: true, eligible: false, at: .milliseconds(10500))
        XCTAssertFalse(dwell.consume(at: .seconds(20)))
    }
}

private final class DeliveryImageProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var data = Data()
    private static var status = 200
    private static var mime = "image/png"
    private static var length: String?
    private static var count = 0
    private static var active = 0
    private static var peak = 0
    private var stopped = false
    static var requestCount: Int { lock.withLock { count } }
    static var peakCount: Int { lock.withLock { peak } }

    static func reset(data: Data, status: Int = 200, mime: String = "image/png", length: String? = nil) {
        lock.withLock {
            self.data = data; self.status = status; self.mime = mime; self.length = length
            count = 0; active = 0; peak = 0
        }
    }

    static func waitForRequests(_ minimum: Int) async {
        for _ in 0..<1000 {
            if requestCount >= minimum { return }
            try? await Task.sleep(for: .milliseconds(1))
        }
        XCTFail("Image transport did not start")
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let fixture = Self.lock.withLock {
            Self.count += 1; Self.active += 1; Self.peak = max(Self.peak, Self.active)
            return (Self.data, Self.status, Self.mime, Self.length)
        }
        DispatchQueue.global().asyncAfter(deadline: .now() + 0.1) { [self] in
            let shouldFinish = Self.lock.withLock {
                guard !stopped else { return false }
                stopped = true; Self.active -= 1; return true
            }
            guard shouldFinish else { return }
            let response = HTTPURLResponse(url: request.url!, statusCode: fixture.1, httpVersion: nil,
                headerFields: ["Content-Type": fixture.2,
                               "Content-Length": fixture.3 ?? String(fixture.0.count), "Cache-Control": "no-store"])!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: fixture.0)
            client?.urlProtocolDidFinishLoading(self)
        }
    }
    override func stopLoading() {
        Self.lock.withLock {
            if !stopped { stopped = true; Self.active -= 1 }
        }
    }
}
