//
//  BackgroundNewsFetcher.swift
//  Daily
//
//  Created by AI on 11/14/25.
//

import Foundation
import Combine
import UIKit

/// Singleton responsible for fetching feed using a background URLSession
/// so the request can continue even when the app is in the background.
final class BackgroundNewsFetcher: NSObject, ObservableObject {
    static let shared = BackgroundNewsFetcher()

    // MARK: - Published state

    @Published private(set) var lastFeedArticles: [NewsArticle] = []
    @Published private(set) var isFetching: Bool = false
    @Published private(set) var lastErrorMessage: String?

    // MARK: - Private

    private enum StorageKeys {
        static let feedArticles = "BackgroundNewsFetcher.feedArticles"
        static let lastFetchDate = "BackgroundNewsFetcher.lastFetchDate"
    }

    private let sessionIdentifier = "com.daily.news.feed.background"
    private lazy var backgroundSession: URLSession = {
        let config = URLSessionConfiguration.background(withIdentifier: sessionIdentifier)
        config.sessionSendsLaunchEvents = true
        config.isDiscretionary = false
        config.waitsForConnectivity = true
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()

    private var backgroundCompletionHandler: (() -> Void)?
    private let baseURL = URL(string: "https://daily-backend.fly.dev")!

    // MARK: - Initialization

    private override init() {
        super.init()
        loadCachedArticles()
    }

    // MARK: - Public API

    func registerBackgroundCompletionHandler(_ handler: @escaping () -> Void) {
        backgroundCompletionHandler = handler
    }

    /// Start a background feed refresh using POST /feed/refresh.
    func startFeedRefresh(accessToken: String, limit: Int = 20) {
        if isFetching { return }

        var components = URLComponents(url: baseURL.appendingPathComponent("/feed/refresh"), resolvingAgainstBaseURL: false)
        components?.queryItems = [
            URLQueryItem(name: "limit", value: "\(limit)")
        ]

        guard let url = components?.url else {
            lastErrorMessage = "Invalid URL"
            return
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        isFetching = true
        lastErrorMessage = nil

        let task = backgroundSession.downloadTask(with: request)
        task.resume()
    }

    func loadCachedArticles() {
        let defaults = UserDefaults.standard
        guard let data = defaults.data(forKey: StorageKeys.feedArticles) else { return }

        do {
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            let articles = try decoder.decode([NewsArticle].self, from: data)
            lastFeedArticles = articles
        } catch {
            print("BackgroundNewsFetcher: Failed to decode cached articles: \(error)")
        }
    }

    // MARK: - Private helpers

    private func handleCompletedData(_ data: Data, response: URLResponse?) {
        guard let http = response as? HTTPURLResponse else {
            DispatchQueue.main.async {
                self.lastErrorMessage = "Invalid response"
                self.isFetching = false
            }
            return
        }

        guard (200..<300).contains(http.statusCode) else {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Request failed with status \(http.statusCode)"
            DispatchQueue.main.async {
                self.lastErrorMessage = errorMessage
                self.isFetching = false
            }
            return
        }

        do {
            let response = try BackendService.iso8601Decoder.decode(BackendService.FeedResponse.self, from: data)
            guard response.status == .ready else {
                DispatchQueue.main.async {
                    self.lastErrorMessage = "Feed is not ready yet"
                    self.isFetching = false
                }
                return
            }

            let articles = response.articles.map { $0.normalizedForDisplay() }

            let encoded = try JSONEncoder().encode(articles)
            let defaults = UserDefaults.standard
            defaults.set(encoded, forKey: StorageKeys.feedArticles)
            defaults.set(Date(), forKey: StorageKeys.lastFetchDate)

            DispatchQueue.main.async {
                self.lastFeedArticles = articles
                self.isFetching = false
                self.lastErrorMessage = nil

                ImageCacheService.shared.preloadImages(for: articles)

                NotificationCenter.default.post(name: .feedReady, object: nil)
            }
        } catch {
            print("BackgroundNewsFetcher: Failed to decode feed: \(error)")
            DispatchQueue.main.async {
                self.lastErrorMessage = "Failed to parse response: \(error.localizedDescription)"
                self.isFetching = false
            }
        }
    }
}

// MARK: - URLSessionDelegate & URLSessionDownloadDelegate

extension BackgroundNewsFetcher: URLSessionDelegate, URLSessionDownloadDelegate {
    func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask, didFinishDownloadingTo location: URL) {
        do {
            let data = try Data(contentsOf: location)
            handleCompletedData(data, response: downloadTask.response)
        } catch {
            print("BackgroundNewsFetcher: Failed to read downloaded data: \(error)")
            DispatchQueue.main.async {
                self.lastErrorMessage = "Failed to read downloaded data: \(error.localizedDescription)"
                self.isFetching = false
            }
        }
    }

    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error = error {
            print("BackgroundNewsFetcher: Background task failed: \(error)")
            DispatchQueue.main.async {
                self.lastErrorMessage = error.localizedDescription
                self.isFetching = false
            }
        }
    }

    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        DispatchQueue.main.async {
            self.backgroundCompletionHandler?()
            self.backgroundCompletionHandler = nil
        }
    }
}

// MARK: - Notifications

extension Notification.Name {
    static let feedReady = Notification.Name("BackgroundNewsFetcher.feedReady")
    // Keep old name for backward compatibility during transition
    static let curatedNewsReady = Notification.Name("BackgroundNewsFetcher.feedReady")
}
