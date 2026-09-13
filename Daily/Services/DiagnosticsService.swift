//
//  DiagnosticsService.swift
//  Daily
//
//  Crash, hang and resource-exception reporting, built on MetricKit.
//
//  Why MetricKit rather than Crashlytics or Sentry: this app has exactly one
//  direct package dependency (GoogleSignIn, 7 transitive pins) and no privacy
//  manifest. firebase-ios-sdk would roughly triple that graph and add a dSYM
//  upload build phase; Sentry is lighter but still a real SDK with its own
//  network stack, symbol upload and vendor account. MXMetricManager is in the
//  SDK, needs no availability guard at this deployment target, reports crashes
//  the app cannot observe from inside its own process (signals, watchdog
//  terminations, OOM-adjacent hangs) — which is most of them, given the app
//  contains exactly one force-unwrap-class trap site — and costs nothing.
//
//  The trade MetricKit makes: payloads arrive on a later launch rather than at
//  crash time, only on real devices, and stack frames come back as addresses
//  that need the build's dSYM to read. For a three-reader app that is the right
//  trade; what matters is knowing a crash happened, in which build, and how
//  often.
//

import Foundation
import MetricKit
import os

/// One report as it is stored on disk and sent to the backend.
struct DiagnosticReport: Codable, Equatable {
    let reportId: String
    let capturedAt: Date
    let appVersion: String
    let buildNumber: String
    let osVersion: String
    /// `crash`, `hang`, `cpu_exception`, `disk_write_exception`, or `unknown`.
    let kinds: [String]
    /// MetricKit's own JSON, verbatim where it fits. See `payloadOrSummary`.
    let payload: String
    let truncated: Bool
}

@MainActor
final class DiagnosticsService {
    static let shared = DiagnosticsService()

    /// The backend caps request bodies at 1MB. A crash payload carrying a full
    /// call-stack tree can exceed that on its own, and a 413 would mean the
    /// report is simply lost. Anything larger than this is replaced by a
    /// summary that still identifies the build, the kind and the counts.
    static let maxPayloadBytes = 600_000

    /// Keep the on-disk queue small enough that a device stuck offline can't
    /// accumulate reports indefinitely. Oldest are dropped first.
    static let maxStoredReports = 20

    /// Reports older than this are dropped unsent: a crash in a build that
    /// shipped a month ago is not worth a request.
    static let maxReportAgeDays = 14

    private let store: DiagnosticStore
    private let tokenProvider: @MainActor () -> String?
    private let submit: ([DiagnosticReport], String) async throws -> Void
    private let logger = Logger(subsystem: "com.daily.app", category: "diagnostics")
    private var subscriber: DiagnosticsSubscriber?
    private var isFlushing = false

    init(
        directory: URL? = nil,
        tokenProvider: @escaping @MainActor () -> String? = { AuthService.shared.getAccessToken() },
        submit: @escaping ([DiagnosticReport], String) async throws -> Void = {
            try await BackendService.shared.submitDiagnostics($0, accessToken: $1)
        }
    ) {
        let base = directory ?? FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("DailyDiagnostics", isDirectory: true)
        self.store = DiagnosticStore(directory: base)
        self.tokenProvider = tokenProvider
        self.submit = submit
    }

    /// Begin receiving payloads. Safe to call more than once.
    func start() {
        guard subscriber == nil else { return }
        let subscriber = DiagnosticsSubscriber { [weak self] payloads in
            Task { @MainActor in
                guard let self else { return }
                payloads.forEach(self.record)
                await self.flush()
            }
        }
        self.subscriber = subscriber
        MXMetricManager.shared.add(subscriber)
    }

    /// Send everything queued on disk, oldest first. Reports are deleted only
    /// once the server has them.
    ///
    /// Upload is deliberately gated on having a token rather than using an
    /// unauthenticated ingest endpoint: an open crash-report sink is an abuse
    /// target, and MetricKit's payloads are historical anyway, so waiting for
    /// the reader to sign in loses nothing but time.
    func flush() async {
        guard !isFlushing, let token = tokenProvider() else { return }
        isFlushing = true
        defer { isFlushing = false }
        store.prune(maxReports: Self.maxStoredReports, maxAgeDays: Self.maxReportAgeDays)
        let pending = store.load()
        guard !pending.isEmpty else { return }
        for batch in Self.batches(of: pending) {
            guard tokenProvider() == token else { return }
            do {
                try await submit(batch, token)
                store.delete(batch.map(\.reportId))
            } catch {
                if Self.isPermanentRejection(error) {
                    // The server will never accept this batch, so retrying it
                    // forever would wedge every later report behind it. Drop it
                    // and keep going -- losing one malformed report is much
                    // cheaper than losing the queue.
                    logger.error("Diagnostics batch rejected permanently; discarding it")
                    store.delete(batch.map(\.reportId))
                    continue
                }
                logger.error("Diagnostics upload failed; reports retained for the next launch")
                return
            }
        }
    }

    /// The most reports one request may carry, independent of size.
    static let maxReportsPerRequest = 5

    /// Total payload budget for one request. The backend's middleware returns
    /// 413 above 1MB and a 413 costs the whole batch, so batching purely by
    /// count would let five large crash reports — the ones most worth having —
    /// exceed the cap together and be discarded as a permanent rejection.
    /// Bounded well under 1MB to leave room for JSON framing and the other
    /// fields.
    static let maxRequestPayloadBytes = 800_000

    /// Split oldest-first, bounded by both count and total payload size. A
    /// single report larger than the budget still goes out alone: the server
    /// accepts up to its own per-payload cap, which the client already respects.
    static func batches(of reports: [DiagnosticReport]) -> [[DiagnosticReport]] {
        var batches: [[DiagnosticReport]] = []
        var current: [DiagnosticReport] = []
        var bytes = 0
        for report in reports {
            let size = report.payload.utf8.count
            if !current.isEmpty,
               current.count >= maxReportsPerRequest || bytes + size > maxRequestPayloadBytes {
                batches.append(current)
                current = []
                bytes = 0
            }
            current.append(report)
            bytes += size
        }
        if !current.isEmpty { batches.append(current) }
        return batches
    }

    /// 4xx other than "sign in again" and "slow down" means the payload itself
    /// is unacceptable; no number of retries changes that.
    static func isPermanentRejection(_ error: Error) -> Bool {
        let status = (error as NSError).code
        guard (400..<500).contains(status) else { return false }
        return status != 401 && status != 403 && status != 429
    }

    /// Convert a MetricKit payload into reports and persist them immediately.
    /// Exposed for tests; production reaches it through the subscriber.
    func record(_ payload: MXDiagnosticPayload) {
        let (json, truncated) = Self.payloadOrSummary(payload)
        let report = DiagnosticReport(
            reportId: UUID().uuidString,
            capturedAt: payload.timeStampEnd,
            appVersion: Self.label(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String),
            buildNumber: Self.label(Bundle.main.infoDictionary?["CFBundleVersion"] as? String),
            osVersion: Self.label(ProcessInfo.processInfo.operatingSystemVersionString),
            kinds: Self.kinds(in: payload),
            payload: json,
            truncated: truncated
        )
        store.save(report)
        store.prune(maxReports: Self.maxStoredReports, maxAgeDays: Self.maxReportAgeDays)
        logger.info("Diagnostic payload stored kinds=\(report.kinds.joined(separator: ","), privacy: .public) truncated=\(truncated, privacy: .public)")
    }

    /// Match the server's per-field bound (`client_diagnostics.MAX_LABEL_CHARS`).
    /// Producing a value it will always 422 would mean a report that retries on
    /// every launch and never lands.
    static let maxLabelCharacters = 64

    static func label(_ value: String?) -> String {
        let trimmed = (value ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return "unknown" }
        return String(trimmed.prefix(maxLabelCharacters))
    }

    static func kinds(in payload: MXDiagnosticPayload) -> [String] {
        var found: [String] = []
        if !(payload.crashDiagnostics ?? []).isEmpty { found.append("crash") }
        if !(payload.hangDiagnostics ?? []).isEmpty { found.append("hang") }
        if !(payload.cpuExceptionDiagnostics ?? []).isEmpty { found.append("cpu_exception") }
        if !(payload.diskWriteExceptionDiagnostics ?? []).isEmpty { found.append("disk_write_exception") }
        return found.isEmpty ? ["unknown"] : found
    }

    /// MetricKit's JSON if it fits under the body cap, otherwise a summary.
    ///
    /// Dropping an oversized payload entirely would lose exactly the reports
    /// most worth having — a deep call-stack tree usually means a real crash,
    /// not a hang — so the fallback keeps the parts that identify it.
    static func payloadOrSummary(_ payload: MXDiagnosticPayload) -> (String, Bool) {
        let data = payload.jsonRepresentation()
        if data.count <= maxPayloadBytes, let text = String(data: data, encoding: .utf8) {
            return (text, false)
        }
        let summary: [String: Any] = [
            "truncated_from_bytes": data.count,
            "kinds": kinds(in: payload),
            "crash_count": (payload.crashDiagnostics ?? []).count,
            "hang_count": (payload.hangDiagnostics ?? []).count,
            "exception_types": (payload.crashDiagnostics ?? []).compactMap { $0.exceptionType?.stringValue },
            "termination_reasons": (payload.crashDiagnostics ?? []).compactMap { $0.terminationReason },
            "signals": (payload.crashDiagnostics ?? []).compactMap { $0.signal?.stringValue },
            "time_stamp_begin": ISO8601DateFormatter().string(from: payload.timeStampBegin),
            "time_stamp_end": ISO8601DateFormatter().string(from: payload.timeStampEnd),
        ]
        let encoded = (try? JSONSerialization.data(withJSONObject: summary, options: [.sortedKeys]))
            .flatMap { String(data: $0, encoding: .utf8) }
        return (encoded ?? #"{"truncated":true}"#, true)
    }

}

/// MetricKit calls back on its own queue, and `MXMetricManagerSubscriber` is an
/// Objective-C protocol, so the conformance lives on a plain object that hops
/// onto the main actor rather than on the `@MainActor` service itself.
final class DiagnosticsSubscriber: NSObject, MXMetricManagerSubscriber {
    private let onDiagnostics: @Sendable ([MXDiagnosticPayload]) -> Void

    init(onDiagnostics: @escaping @Sendable ([MXDiagnosticPayload]) -> Void) {
        self.onDiagnostics = onDiagnostics
    }

    func didReceive(_ payloads: [MXDiagnosticPayload]) {
        onDiagnostics(payloads)
    }

    // Daily aggregate metrics are not collected: they carry no crash signal and
    // the app has nowhere to put them. Required by the protocol.
    func didReceive(_ payloads: [MXMetricPayload]) {}
}

/// One JSON file per report. A crash report has to survive the process that
/// produced it, so unlike `ReadingEventTracker`'s in-memory queue this writes
/// through immediately.
struct DiagnosticStore {
    let directory: URL
    private let logger = Logger(subsystem: "com.daily.app", category: "diagnostics")

    func save(_ report: DiagnosticReport) {
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let encoder = JSONEncoder()
            encoder.dateEncodingStrategy = .iso8601
            try encoder.encode(report).write(to: file(for: report.reportId), options: .atomic)
        } catch {
            logger.error("Could not persist a diagnostic report: \(error.localizedDescription, privacy: .private)")
        }
    }

    func load() -> [DiagnosticReport] {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return contents()
            .compactMap { try? decoder.decode(DiagnosticReport.self, from: Data(contentsOf: $0)) }
            .sorted { $0.capturedAt < $1.capturedAt }
    }

    func delete(_ reportIds: [String]) {
        for reportId in reportIds {
            try? FileManager.default.removeItem(at: file(for: reportId))
        }
    }

    func prune(maxReports: Int, maxAgeDays: Int) {
        let cutoff = Date().addingTimeInterval(-Double(maxAgeDays) * 86_400)
        let reports = load()
        let stale = reports.filter { $0.capturedAt < cutoff }.map(\.reportId)
        let fresh = reports.filter { $0.capturedAt >= cutoff }
        let overflow = fresh.count > maxReports ? fresh.prefix(fresh.count - maxReports).map(\.reportId) : []
        delete(stale + overflow)
    }

    private func contents() -> [URL] {
        (try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil))?
            .filter { $0.pathExtension == "json" } ?? []
    }

    private func file(for reportId: String) -> URL {
        directory.appendingPathComponent("\(reportId).json")
    }
}
