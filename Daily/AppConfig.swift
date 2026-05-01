//
//  AppConfig.swift
//  Daily
//
//  Centralized app configuration. Single source of truth for the backend URL
//  so a typo can't crash one service while leaving others working.
//

import Foundation

enum AppConfig {
    /// Production backend. If a deploy needs a different host, override via
    /// the `DAILY_BACKEND_URL` Info.plist key (set with `INFOPLIST_KEY_DAILY_BACKEND_URL`)
    /// or in scheme env vars during development.
    static let backendURL: URL = {
        if let override = Bundle.main.object(forInfoDictionaryKey: "DAILY_BACKEND_URL") as? String,
           let url = URL(string: override) {
            return url
        }
        // Hardcoded fallback. Not force-unwrapped — if the literal ever becomes
        // invalid we crash with a clear message instead of `!` site noise.
        guard let url = URL(string: "https://daily-backend.fly.dev") else {
            preconditionFailure("AppConfig.backendURL: invalid URL literal")
        }
        return url
    }()
}
