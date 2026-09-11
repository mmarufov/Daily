import Foundation
import UIKit
import ImageIO

/// Public, uncredentialed publisher images. Account changes synchronously fence
/// callbacks already in flight; lazy card tasks own the viewport request window.
nonisolated final class ImageCacheService: @unchecked Sendable {
    static let shared = ImageCacheService()
    static let maximumBytes = 5 * 1024 * 1024
    static let maximumPixels = 40_000_000
    private let lock = NSLock()
    private var generation: UInt64 = 0
    private let pipeline: ArticleImagePipeline

    init(configuration: URLSessionConfiguration = .ephemeral) {
        configuration.urlCache = URLCache(memoryCapacity: 8 * 1024 * 1024, diskCapacity: 0)
        configuration.requestCachePolicy = .useProtocolCachePolicy
        configuration.timeoutIntervalForRequest = 8
        configuration.timeoutIntervalForResource = 15
        configuration.waitsForConnectivity = false
        configuration.httpCookieStorage = nil
        configuration.urlCredentialStorage = nil
        pipeline = ArticleImagePipeline(configuration: configuration)
    }

    private func epoch() -> UInt64 { lock.withLock { generation } }

    func image(url: URL, pixelSize: Int) async throws -> UIImage {
        let owner = epoch()
        let image = try await pipeline.image(url: url, pixels: pixelSize, generation: owner)
        try Task.checkCancellation()
        guard owner == epoch() else { throw CancellationError() }
        return image
    }

    /// Compatibility only: never prefetch an entire edition.
    func preloadImages(for articles: [NewsArticle]) {}

    func clearCache() {
        let next = lock.withLock { generation &+= 1; return generation }
        Task { await pipeline.clear(before: next) }
    }

    static func downsample(_ data: Data, pixels: Int) throws -> UIImage {
        guard data.count <= maximumBytes,
              let source = CGImageSourceCreateWithData(data as CFData, [kCGImageSourceShouldCache: false] as CFDictionary),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? NSNumber,
              let height = properties[kCGImagePropertyPixelHeight] as? NSNumber,
              width.doubleValue > 0, height.doubleValue > 0,
              width.doubleValue * height.doubleValue <= Double(maximumPixels),
              let thumbnail = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: min(max(pixels, 1), 2048),
                kCGImageSourceShouldCacheImmediately: true
              ] as CFDictionary) else { throw URLError(.cannotDecodeContentData) }
        return UIImage(cgImage: thumbnail)
    }

    /// Only explicitly fresh HTTP responses get a decoded shortcut. Everything
    /// else returns to URLSession so its normal validators/cache policy apply.
    static func decodedFreshness(response: HTTPURLResponse, now: Date = Date()) -> TimeInterval {
        let directives = (response.value(forHTTPHeaderField: "Cache-Control") ?? "")
            .lowercased().split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }
        guard !directives.contains(where: { $0.hasPrefix("no-cache") || $0.hasPrefix("no-store") }),
              let rawAge = directives.first(where: { $0.hasPrefix("max-age=") })?.dropFirst(8),
              let maxAge = Double(rawAge.trimmingCharacters(in: CharacterSet(charactersIn: "\""))),
              maxAge.isFinite, maxAge > 0 else { return 0 }
        let ageHeader = Double(response.value(forHTTPHeaderField: "Age") ?? "0") ?? maxAge
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"
        // Without origin time, do not invent a fresh lifetime for a cached response.
        guard let dateValue = response.value(forHTTPHeaderField: "Date"),
              let date = formatter.date(from: dateValue), ageHeader.isFinite else { return 0 }
        return max(0, min(300, maxAge - max(0, ageHeader, now.timeIntervalSince(date))))
    }
}

private actor ArticleImagePipeline {
    struct Key: Hashable { let url: URL; let pixels: Int; let generation: UInt64 }
    struct Job {
        let id: UUID
        var waiters: [UUID: CheckedContinuation<UIImage, Error>]
        var task: Task<Void, Never>?
    }
    private let session: URLSession
    private let cache = NSCache<NSString, UIImage>()
    private var jobs: [Key: Job] = [:]
    private var queue: [Key] = []
    private var active = 0
    private var minimumGeneration: UInt64 = 0
    private var cacheDeadlines: [Key: ContinuousClock.Instant] = [:]

    init(configuration: URLSessionConfiguration) {
        session = URLSession(configuration: configuration)
        cache.totalCostLimit = 32 * 1024 * 1024
    }

    func image(url: URL, pixels: Int, generation: UInt64) async throws -> UIImage {
        try Task.checkCancellation()
        guard generation >= minimumGeneration,
              ["https", "http"].contains(url.scheme?.lowercased() ?? ""),
              url.user == nil, url.password == nil else { throw URLError(.unsupportedURL) }
        let key = Key(url: url, pixels: min(max(pixels, 1), 2048), generation: generation)
        if let deadline = cacheDeadlines[key], ContinuousClock.now < deadline,
           let image = cache.object(forKey: cacheKey(key)) { return image }
        evict(key)
        let waiter = UUID()
        return try await withTaskCancellationHandler {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { continuation in
                if jobs[key] != nil {
                    jobs[key]?.waiters[waiter] = continuation
                } else {
                    jobs[key] = Job(id: UUID(), waiters: [waiter: continuation])
                    queue.append(key)
                }
                drain()
            }
        } onCancel: {
            Task { await self.cancel(waiter: waiter, key: key) }
        }
    }

    private func cacheKey(_ key: Key) -> NSString {
        "\(key.generation)|\(key.pixels)|\(key.url.absoluteString)" as NSString
    }

    private func drain() {
        while active < 4, !queue.isEmpty {
            let key = queue.removeFirst()
            guard let jobID = jobs[key]?.id else { continue }
            active += 1
            let session = session
            jobs[key]?.task = Task.detached(priority: .utility) {
                let result: Result<UIImage, Error>
                var freshness: TimeInterval = 0
                do {
                    let (bytes, response) = try await session.bytes(for: URLRequest(url: key.url))
                    guard let http = response as? HTTPURLResponse,
                          (200..<300).contains(http.statusCode),
                          http.mimeType?.lowercased().hasPrefix("image/") == true,
                          response.expectedContentLength <= Int64(ImageCacheService.maximumBytes)
                    else { throw URLError(.badServerResponse) }
                    var data = Data()
                    for try await byte in bytes {
                        try Task.checkCancellation()
                        guard data.count < ImageCacheService.maximumBytes else { throw URLError(.dataLengthExceedsMaximum) }
                        data.append(byte)
                    }
                    freshness = ImageCacheService.decodedFreshness(response: http)
                    result = .success(try ImageCacheService.downsample(data, pixels: key.pixels))
                } catch { result = .failure(error) }
                await self.finish(key, jobID: jobID, result: result, freshness: freshness)
            }
        }
    }

    private func finish(_ key: Key, jobID: UUID, result: Result<UIImage, Error>, freshness: TimeInterval) {
        active -= 1
        if jobs[key]?.id == jobID, let job = jobs.removeValue(forKey: key) {
            if key.generation >= minimumGeneration, !job.waiters.isEmpty,
               freshness > 0, case .success(let image) = result, let cg = image.cgImage {
                cache.setObject(image, forKey: cacheKey(key), cost: cg.bytesPerRow * cg.height)
                cacheDeadlines[key] = .now.advanced(by: .seconds(freshness))
                // Bound bookkeeping independently of NSCache's memory-pressure eviction.
                if cacheDeadlines.count > 128 {
                    for expired in Array(cacheDeadlines.keys) where expired != key { evict(expired) }
                }
            }
            for continuation in job.waiters.values {
                if key.generation < minimumGeneration { continuation.resume(throwing: CancellationError()) }
                else { continuation.resume(with: result) }
            }
        }
        drain()
    }

    private func evict(_ key: Key) {
        cache.removeObject(forKey: cacheKey(key))
        cacheDeadlines.removeValue(forKey: key)
    }

    private func cancel(waiter: UUID, key: Key) {
        guard let continuation = jobs[key]?.waiters.removeValue(forKey: waiter) else { return }
        continuation.resume(throwing: CancellationError())
        if jobs[key]?.waiters.isEmpty == true {
            jobs.removeValue(forKey: key)?.task?.cancel()
            queue.removeAll { $0 == key }
        }
    }

    func clear(before generation: UInt64) {
        minimumGeneration = max(minimumGeneration, generation)
        cache.removeAllObjects()
        cacheDeadlines.removeAll()
        session.configuration.urlCache?.removeAllCachedResponses()
        for key in Array(jobs.keys) where key.generation < minimumGeneration {
            guard let job = jobs[key] else { continue }
            for waiter in job.waiters.values { waiter.resume(throwing: CancellationError()) }
            if let task = job.task {
                jobs[key]?.waiters = [:]
                task.cancel()
            } else { jobs.removeValue(forKey: key) }
        }
        queue.removeAll { $0.generation < minimumGeneration }
    }
}
