//
//  DailyApp.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI
import Foundation
#if canImport(GoogleSignIn)
import GoogleSignIn
#endif

@main
struct DailyApp: App {
    init() {
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
