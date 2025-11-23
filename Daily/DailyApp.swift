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
        // Initialize image cache service early so images can be preloaded and cached
        _ = ImageCacheService.shared
        
        // Configure Google Sign-In if SDK is available
        #if canImport(GoogleSignIn)
        if let path = Bundle.main.path(forResource: "GoogleService-Info", ofType: "plist"),
           let plist = NSDictionary(contentsOfFile: path),
           let clientId = plist["CLIENT_ID"] as? String {
            GIDSignIn.sharedInstance.configuration = GIDConfiguration(clientID: clientId)
        }
        #endif
    }
    
    var body: some Scene {
        WindowGroup {
            ContentView()
                .onOpenURL { url in
                    // Handle Google Sign-In URL callback
                    #if canImport(GoogleSignIn)
                    GIDSignIn.sharedInstance.handle(url)
                    #endif
                }
        }
    }
}
