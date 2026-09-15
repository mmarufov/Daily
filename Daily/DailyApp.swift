//
//  DailyApp.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI
import Foundation
import UIKit
#if canImport(GoogleSignIn)
import GoogleSignIn
#endif

// MARK: - AppDelegate for background URLSession handling

class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        handleEventsForBackgroundURLSession identifier: String,
        completionHandler: @escaping () -> Void
    ) {
        // Forward the completion handler to our background fetcher so it can
        // call it when all background events have been processed.
        BackgroundNewsFetcher.shared.registerBackgroundCompletionHandler(completionHandler)
    }
}

@main
struct DailyApp: App {
    // Bridge UIKit lifecycle for background URLSession
    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    
    init() {
        #if DEBUG
        if ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil { return }
        #endif
        // Initialize shared services before SwiftUI begins evaluating view
        // bodies. Auth restoration can publish state immediately when no
        // credential exists, which must not happen reentrantly from a view
        // update (for example when ArticleDetailView creates TuneViewModel).
        _ = ImageCacheService.shared
        _ = AuthService.shared

        // Subscribe to MetricKit before anything else can crash. Payloads are
        // delivered on a launch *after* the crash, so starting here is what
        // makes the previous run's crash reachable at all.
        DiagnosticsService.shared.start()
        
        // Configure Google Sign-In if SDK is available
        #if canImport(GoogleSignIn)
        if let path = Bundle.main.path(forResource: "GoogleService-Info", ofType: "plist"),
           let plist = NSDictionary(contentsOfFile: path),
           let clientId = plist["CLIENT_ID"] as? String {
            GIDSignIn.sharedInstance.configuration = GIDConfiguration(clientID: clientId)
        }
        #endif
    }
    
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            rootView
                .onOpenURL { url in
                    // Handle Google Sign-In URL callback
                    #if canImport(GoogleSignIn)
                    GIDSignIn.sharedInstance.handle(url)
                    #endif
                }
                .onChange(of: scenePhase) { _, newPhase in
                    if newPhase == .background {
                        // Flush reading events when app goes to background
                        Task { await ReadingEventTracker.shared.flush() }
                        // Any crash report MetricKit delivered this session is
                        // already on disk; this is the chance to ship it.
                        Task { await DiagnosticsService.shared.flush() }
                    }
                }
        }
    }

    @ViewBuilder
    private var rootView: some View {
        #if DEBUG
        if ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil {
            Color.clear // Unit tests must not restore credentials or start production requests.
        } else if let scenario = S2ReaderUITestScenario.current {
            S2ArticleReaderUITestHost(scenario: scenario)
        } else {
            ContentView()
        }
        #else
        ContentView()
        #endif
    }
}

#if DEBUG
private enum S2ReaderUITestScenario: String {
    case native
    case source
    case noToken = "no-token"
    case offline
    case timeout
    case invalid

    static var current: Self? {
        let arguments = ProcessInfo.processInfo.arguments
        guard let flag = arguments.firstIndex(of: "--s2-reader-ui-test"),
              arguments.indices.contains(flag + 1) else {
            return nil
        }
        return Self(rawValue: arguments[flag + 1])
    }
}

private struct S2ArticleReaderUITestHost: View {
    let scenario: S2ReaderUITestScenario

    var body: some View {
        NavigationStack {
            ArticleDetailView(
                article: feedArticle,
                tracksOpenAutomatically: false,
                fetchArticle: fetchArticle,
                accessTokenProvider: { scenario == .noToken ? nil : "ui-test-token" },
                userIDProvider: { nil },
                fetchRelatedArticles: { _, _, _ in [] }
            )
            .navigationTitle("Reader test")
        }
    }

    private var feedArticle: NewsArticle {
        switch scenario {
        case .source:
            return makeArticle(mode: .sourceWeb, accessHint: "subscription_may_be_required")
        case .invalid:
            return makeArticle(mode: .unavailable, originalURL: "http://127.0.0.1/private")
        default:
            return makeArticle(mode: .nativeFullText)
        }
    }

    private var fetchArticle: ArticleReaderModel.FetchArticle {
        { _, _ in
            switch scenario {
            case .offline:
                throw URLError(.notConnectedToInternet)
            case .timeout:
                throw URLError(.timedOut)
            default:
                return makeArticle(
                    mode: .nativeFullText,
                    body: "A verified publisher paragraph for the native reader UI test."
                )
            }
        }
    }

    private func makeArticle(
        mode: ArticlePresentationMode,
        body: String? = nil,
        originalURL: String? = "https://publisher.com/story",
        accessHint: String? = nil
    ) -> NewsArticle {
        var article = NewsArticle(
            id: "s2-ui-article",
            title: "S2 Reader Test Story",
            summary: "The story metadata remains visible in every reader state.",
            content: nil,
            author: "Reporter",
            source: "Publisher",
            imageURL: nil,
            publishedAt: nil,
            category: "Test",
            url: originalURL
        )
        article.presentation = ArticlePresentation(
            mode: mode,
            originalURL: originalURL,
            body: body,
            bodyState: body == nil ? .none : .verifiedFull,
            accessHint: accessHint,
            reason: "ui_test_fixture",
            provenance: ArticleContentProvenance(
                kind: "origin_extract",
                sourceURL: originalURL,
                rightsPolicy: "publisher_permission",
                completeness: "complete",
                contentVersion: 1,
                policyVersion: 1
            )
        )
        return article
    }
}
#endif
