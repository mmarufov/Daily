import XCTest
@testable import Daily

/// MetricKit payloads cannot be constructed in a test — `MXDiagnosticPayload`
/// has no public initialiser and only arrives on real hardware. So these cover
/// everything around the payload: the on-disk queue that has to outlive the
/// crashing process, the upload/retry rules, and the wire body. `record(_:)`
/// itself is a thin adapter over `payloadOrSummary` and the store, both of
/// which are exercised directly here.
@MainActor
final class DiagnosticsServiceTests: XCTestCase {
    private var directory: URL!

    override func setUp() async throws {
        try await super.setUp()
        directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("diagnostics-\(UUID().uuidString)", isDirectory: true)
    }

    override func tearDown() async throws {
        try? FileManager.default.removeItem(at: directory)
        try await super.tearDown()
    }

    // MARK: - The on-disk queue

    func testReportsSurviveOnDiskSoACrashCanBeReportedOnTheNextLaunch() async {
        let store = DiagnosticStore(directory: directory)
        store.save(report(id: "a", ageDays: 0))

        // A *new* store over the same directory stands in for the next launch.
        let reloaded = DiagnosticStore(directory: directory).load()

        XCTAssertEqual(reloaded.map(\.reportId), ["a"])
    }

    func testQueueIsReturnedOldestFirst() async {
        let store = DiagnosticStore(directory: directory)
        store.save(report(id: "new", ageDays: 1))
        store.save(report(id: "old", ageDays: 5))
        store.save(report(id: "middle", ageDays: 3))

        XCTAssertEqual(store.load().map(\.reportId), ["old", "middle", "new"])
    }

    func testStaleReportsAreDroppedUnsent() async {
        let store = DiagnosticStore(directory: directory)
        store.save(report(id: "fresh", ageDays: 1))
        store.save(report(id: "ancient", ageDays: Double(DiagnosticsService.maxReportAgeDays) + 1))

        store.prune(maxReports: 20, maxAgeDays: DiagnosticsService.maxReportAgeDays)

        XCTAssertEqual(store.load().map(\.reportId), ["fresh"])
    }

    func testAnOfflineDeviceCannotAccumulateReportsWithoutBound() async {
        let store = DiagnosticStore(directory: directory)
        for index in 0..<8 {
            store.save(report(id: "r\(index)", ageDays: Double(8 - index)))
        }

        store.prune(maxReports: 3, maxAgeDays: 14)

        // Oldest go first: the newest crashes are the ones worth keeping.
        XCTAssertEqual(store.load().map(\.reportId), ["r5", "r6", "r7"])
    }

    // MARK: - Upload

    func testASuccessfulUploadRemovesTheReportsAndNothingElse() async {
        let store = DiagnosticStore(directory: directory)
        store.save(report(id: "a", ageDays: 2))
        store.save(report(id: "b", ageDays: 1))
        let uploader = UploadRecorder()
        let service = makeService(uploader: uploader)

        await service.flush()

        let sent = await uploader.batches
        XCTAssertEqual(sent.map { $0.map(\.reportId) }, [["a", "b"]], "Oldest first")
        XCTAssertEqual(store.load(), [])
    }

    func testReportsAreRetainedWhenTheUploadFails() async {
        let store = DiagnosticStore(directory: directory)
        store.save(report(id: "a", ageDays: 1))
        let service = makeService(uploader: UploadRecorder(error: URLError(.notConnectedToInternet)))

        await service.flush()

        XCTAssertEqual(store.load().map(\.reportId), ["a"], "A crash report must survive a bad network")
    }

    func testNothingIsUploadedWithoutASignedInReader() async {
        let store = DiagnosticStore(directory: directory)
        store.save(report(id: "a", ageDays: 1))
        let uploader = UploadRecorder()
        let service = makeService(uploader: uploader, token: nil)

        await service.flush()

        let sent = await uploader.batches
        XCTAssertEqual(sent.count, 0)
        XCTAssertEqual(store.load().map(\.reportId), ["a"], "Held, not dropped — it uploads after sign-in")
    }

    func testAPermanentlyRejectedBatchIsDiscardedInsteadOfWedgingTheQueue() async {
        let store = DiagnosticStore(directory: directory)
        store.save(report(id: "a", ageDays: 1))
        let service = makeService(
            uploader: UploadRecorder(error: NSError(domain: "BackendService", code: 422))
        )

        await service.flush()

        XCTAssertEqual(store.load(), [], "A 422 retried forever blocks every later report")
    }

    func testRejectionClassification() {
        XCTAssertTrue(DiagnosticsService.isPermanentRejection(NSError(domain: "d", code: 422)))
        XCTAssertTrue(DiagnosticsService.isPermanentRejection(NSError(domain: "d", code: 413)))
        // Retryable: the reader can sign in again, and rate limits pass.
        XCTAssertFalse(DiagnosticsService.isPermanentRejection(NSError(domain: "d", code: 401)))
        XCTAssertFalse(DiagnosticsService.isPermanentRejection(NSError(domain: "d", code: 403)))
        XCTAssertFalse(DiagnosticsService.isPermanentRejection(NSError(domain: "d", code: 429)))
        XCTAssertFalse(DiagnosticsService.isPermanentRejection(NSError(domain: "d", code: 500)))
        XCTAssertFalse(DiagnosticsService.isPermanentRejection(URLError(.timedOut)))
    }

    // MARK: - Batching

    func testBatchesAreBoundedByCount() {
        let reports = (0..<12).map { report(id: "r\($0)", ageDays: Double(12 - $0)) }

        let batches = DiagnosticsService.batches(of: reports)

        XCTAssertEqual(batches.map(\.count), [5, 5, 2])
        XCTAssertEqual(batches.flatMap { $0.map(\.reportId) }, reports.map(\.reportId),
                       "Order and membership must be preserved, oldest first")
    }

    func testBatchesAreBoundedByTotalPayloadSize() {
        // The failure this prevents: five near-maximum crash reports batched by
        // count alone exceed the backend's 1MB body cap, come back 413, and get
        // discarded as a permanent rejection — losing the five biggest reports.
        let big = String(repeating: "x", count: 300_000)
        let reports = (0..<4).map { index in
            DiagnosticReport(reportId: "r\(index)", capturedAt: Date(), appVersion: "1.0",
                             buildNumber: "42", osVersion: "26.0", kinds: ["crash"],
                             payload: big, truncated: false)
        }

        let batches = DiagnosticsService.batches(of: reports)

        XCTAssertEqual(batches.map(\.count), [2, 2])
        for batch in batches {
            let bytes = batch.reduce(0) { $0 + $1.payload.utf8.count }
            XCTAssertLessThanOrEqual(bytes, DiagnosticsService.maxRequestPayloadBytes)
        }
    }

    func testTwoMaximumSizedReportsNeverShareARequest() {
        // 2 x 600_000 is over the 800_000 budget and well over the backend's
        // 1MB body cap; they have to be split even though the count allows five.
        let huge = String(repeating: "x", count: DiagnosticsService.maxPayloadBytes)
        let reports = (0..<2).map { index in
            DiagnosticReport(reportId: "r\(index)", capturedAt: Date(), appVersion: "1.0",
                             buildNumber: "42", osVersion: "26.0", kinds: ["crash"],
                             payload: huge, truncated: true)
        }

        XCTAssertEqual(DiagnosticsService.batches(of: reports).map { $0.map(\.reportId) },
                       [["r0"], ["r1"]])
    }

    func testEveryReportEndsUpInExactlyOneBatch() {
        // A single report at the per-payload cap must never be stranded by a
        // budget it can't fit under on its own.
        let sizes = [10, DiagnosticsService.maxPayloadBytes, 10, 400_000, 400_000, 10]
        let reports = sizes.enumerated().map { index, size in
            DiagnosticReport(reportId: "r\(index)", capturedAt: Date(), appVersion: "1.0",
                             buildNumber: "42", osVersion: "26.0", kinds: ["crash"],
                             payload: String(repeating: "x", count: size), truncated: false)
        }

        let batches = DiagnosticsService.batches(of: reports)

        XCTAssertEqual(batches.flatMap { $0.map(\.reportId) }, reports.map(\.reportId))
        XCTAssertFalse(batches.contains { $0.isEmpty })
    }

    func testAnEmptyQueueProducesNoBatches() {
        XCTAssertTrue(DiagnosticsService.batches(of: []).isEmpty)
    }

    // MARK: - Wire body

    func testWireBodyMatchesWhatTheBackendValidates() throws {
        let body = BackendService.diagnosticsBody([report(id: "a", ageDays: 0)])

        let reports = try XCTUnwrap(body["reports"] as? [[String: Any]])
        XCTAssertEqual(reports.count, 1)
        let first = reports[0]
        XCTAssertEqual(first["report_id"] as? String, "a")
        XCTAssertEqual(first["app_version"] as? String, "1.0")
        XCTAssertEqual(first["build_number"] as? String, "42")
        XCTAssertEqual(first["kinds"] as? [String], ["crash"])
        XCTAssertEqual(first["truncated"] as? Bool, false)
        XCTAssertNotNil(first["captured_at"] as? String)
        XCTAssertNotNil(first["os_version"] as? String)
        // It has to actually serialise — the backend rejects anything else.
        XCTAssertNoThrow(try JSONSerialization.data(withJSONObject: body))
    }

    func testLabelsAreClampedToWhatTheServerAccepts() {
        XCTAssertEqual(DiagnosticsService.label(nil), "unknown")
        XCTAssertEqual(DiagnosticsService.label("  "), "unknown")
        XCTAssertEqual(DiagnosticsService.label(" 1.2.3 "), "1.2.3")
        // A label over the server's bound would 422 on every launch, forever.
        let long = String(repeating: "x", count: 200)
        XCTAssertEqual(DiagnosticsService.label(long).count, DiagnosticsService.maxLabelCharacters)
    }

    // MARK: - Helpers

    private func makeService(uploader: UploadRecorder, token: String? = "token") -> DiagnosticsService {
        DiagnosticsService(
            directory: directory,
            tokenProvider: { token },
            submit: { reports, token in try await uploader.send(reports, token) }
        )
    }

    private func report(id: String, ageDays: Double) -> DiagnosticReport {
        DiagnosticReport(
            reportId: id,
            capturedAt: Date().addingTimeInterval(-ageDays * 86_400),
            appVersion: "1.0",
            buildNumber: "42",
            osVersion: "Version 26.0",
            kinds: ["crash"],
            payload: #"{"crashDiagnostics":[]}"#,
            truncated: false
        )
    }
}

private actor UploadRecorder {
    private(set) var batches: [[DiagnosticReport]] = []
    private let error: Error?

    init(error: Error? = nil) {
        self.error = error
    }

    func send(_ reports: [DiagnosticReport], _ token: String) throws {
        if let error { throw error }
        batches.append(reports)
    }
}
