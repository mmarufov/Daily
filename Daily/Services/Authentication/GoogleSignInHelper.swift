//
//  GoogleSignInHelper.swift
//  Daily
//
//  Created by Assistant on 11/4/25.
//

import Foundation
#if canImport(GoogleSignIn)
import GoogleSignIn
import UIKit

class GoogleSignInHelper {
    static func signIn() async throws -> String {
        guard let windowScene = await UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let rootViewController = await windowScene.windows.first?.rootViewController else {
            throw NSError(domain: "GoogleSignIn", code: -1, userInfo: [NSLocalizedDescriptionKey: "Could not find root view controller"])
        }
        
        let result = try await GIDSignIn.sharedInstance.signIn(withPresenting: rootViewController)
        
        guard let idToken = result.user.idToken?.tokenString else {
            throw NSError(domain: "GoogleSignIn", code: -1, userInfo: [NSLocalizedDescriptionKey: "Failed to get ID token from Google"])
        }
        
        return idToken
    }
}
#else
// Placeholder when GoogleSignIn SDK is not available
class GoogleSignInHelper {
    static func signIn() async throws -> String {
        throw NSError(domain: "GoogleSignIn", code: -1, userInfo: [NSLocalizedDescriptionKey: "Google Sign-In SDK not added. Please add it via Swift Package Manager: https://github.com/google/GoogleSignIn-iOS"])
    }
}
#endif

