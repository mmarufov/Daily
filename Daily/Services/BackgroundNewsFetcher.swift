//
//  BackgroundNewsFetcher.swift
//  Daily
//
//  Created by AI on 11/14/25.
//

import Foundation
import Combine
import UIKit

/// Singleton responsible for fetching curated news using a background URLSession
/// so the request can continue even when the app is in the background.
final class BackgroundNewsFetcher: NSObject, ObservableObject {
    static let shared = BackgroundNewsFetcher()
    
    // MARK: - Published state
    
    /// Latest curated articles fetched in foreground or background.
    @Published private(set) var lastCuratedArticles: [NewsArticle] = []
    
    /// Indicates whether a curated fetch is in progress (foreground or background).
    @Published private(set) var isCurating: Bool = false
    
    /// Optional last error description from background fetch.
    @Published private(set) var lastErrorMessage: String?
    
    // MARK: - Private
    
    private enum StorageKeys {
        static let curatedArticles = "BackgroundNewsFetcher.curatedArticles"
        static let lastFetchDate = "BackgroundNewsFetcher.lastFetchDate"
    }
    
    private let sessionIdentifier = "com.daily.news.curate.background"
    private lazy var backgroundSession: URLSession = {
        let config = URLSessionConfiguration.background(withIdentifier: sessionIdentifier)
        config.sessionSendsLaunchEvents = true
        config.isDiscretionary = false
        config.waitsForConnectivity = true
        return URLSession(configuration: config, delegate: self, delegateQueue: nil)
    }()
    
    /// Completion handler provided by AppDelegate when the system wakes us up
    /// to handle background URLSession events.
    private var backgroundCompletionHandler: (() -> Void)?
    
    /// Backend base URL (must match `BackendService`).
    private let baseURL = URL(string: "https://daily-backend.fly.dev")!
    
    // MARK: - Initialization
    
    private override init() {
        super.init()
        loadCachedCuratedArticles()
    }
    
    // MARK: - Public API
    
    /// Register the system-provided completion handler for background URLSession events.
    func registerBackgroundCompletionHandler(_ handler: @escaping () -> Void) {
        backgroundCompletionHandler = handler
    }
    
    /// Start a curated news fetch that is allowed to continue in the background.
    /// This mirrors `BackendService.curateNews` but uses a background URLSession.
    func startCuratedNewsFetch(accessToken: String, topic: String = "", limit: Int = 10) {
        // Avoid starting multiple parallel curated fetches
        if isCurating {
            return
        }
        
        var components = URLComponents(url: baseURL.appendingPathComponent("/news/curate"), resolvingAgainstBaseURL: false)
        components?.queryItems = [
            URLQueryItem(name: "limit", value: "\(limit)"),
            URLQueryItem(name: "topic", value: topic)
        ]
        
        guard let url = components?.url else {
            lastErrorMessage = "Invalid URL"
            return
        }
        
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        
        isCurating = true
        lastErrorMessage = nil
        
        let task = backgroundSession.downloadTask(with: request)
        task.resume()
    }
    
    /// Load cached curated articles (if present) into published state.
    func loadCachedCuratedArticles() {
        let defaults = UserDefaults.standard
        guard let data = defaults.data(forKey: StorageKeys.curatedArticles) else {
            return
        }
        
        do {
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            let articles = try decoder.decode([NewsArticle].self, from: data)
            lastCuratedArticles = articles
        } catch {
            print("BackgroundNewsFetcher: Failed to decode cached curated articles: \(error)")
        }
    }
    
    // MARK: - Private helpers
    
    private func handleCompletedData(_ data: Data, response: URLResponse?) {
        guard let http = response as? HTTPURLResponse else {
            DispatchQueue.main.async {
                self.lastErrorMessage = "Invalid response"
                self.isCurating = false
            }
            return
        }
        
        guard (200..<300).contains(http.statusCode) else {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Request failed with status \(http.statusCode)"
            DispatchQueue.main.async {
                self.lastErrorMessage = errorMessage
                self.isCurating = false
            }
            return
        }
        
        do {
            let decoder = JSONDecoder()
            decoder.dateDecodingStrategy = .iso8601
            let articles = try decoder.decode([NewsArticle].self, from: data)
            
            // Persist to UserDefaults for retrieval after background fetch.
            let encoded = try JSONEncoder().encode(articles)
            let defaults = UserDefaults.standard
            defaults.set(encoded, forKey: StorageKeys.curatedArticles)
            defaults.set(Date(), forKey: StorageKeys.lastFetchDate)
            
            DispatchQueue.main.async {
                self.lastCuratedArticles = articles
                self.isCurating = false
                self.lastErrorMessage = nil
                
                // Preload images for the articles so they're available when UI displays them
                ImageCacheService.shared.preloadImages(for: articles)
                
                NotificationCenter.default.post(
                    name: .curatedNewsReady,
                    object: nil
                )
            }
        } catch {
            print("BackgroundNewsFetcher: Failed to decode curated articles from background fetch: \(error)")
            DispatchQueue.main.async {
                self.lastErrorMessage = "Failed to parse response: \(error.localizedDescription)"
                self.isCurating = false
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
                self.isCurating = false
            }
        }
    }
    
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        // For background download tasks, success is handled in didFinishDownloadingTo.
        if let error = error {
            print("BackgroundNewsFetcher: Background task failed: \(error)")
            DispatchQueue.main.async {
                self.lastErrorMessage = error.localizedDescription
                self.isCurating = false
            }
        }
    }

    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        // Called when all background tasks for this session have finished.
        DispatchQueue.main.async {
            self.backgroundCompletionHandler?()
            self.backgroundCompletionHandler = nil
        }
    }
}

// MARK: - Notifications

extension Notification.Name {
    static let curatedNewsReady = Notification.Name("BackgroundNewsFetcher.curatedNewsReady")
}


