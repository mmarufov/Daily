//
//  PersonalizationSettingsViewModel.swift
//  Daily
//
//  View model for editing the per-user AI prompt used to filter news.
//

import Foundation
import Combine

@MainActor
final class NewsPersonalizationViewModel: ObservableObject {
    @Published var promptText: String = ""
    @Published var topics: [String] = []
    @Published var currentInterests: [String] = []
    @Published var utilityPriorities: [String] = []
    @Published var locations: [String] = []
    @Published var exclusions: [String] = []
    @Published var lifeContext: String = ""
    @Published var contentDepth: String = "balanced"
    @Published var tonePreferences: [String] = ["neutral"]
    @Published var isLoading: Bool = false
    @Published var isSaving: Bool = false
    @Published var errorMessage: String?

    private let backendService = BackendService.shared
    private let authService = AuthService.shared

    func load() async {
        guard !isLoading else { return }
        guard let token = authService.getAccessToken() else {
            errorMessage = "Authentication required"
            return
        }

        isLoading = true
        errorMessage = nil

        do {
            let prefs = try await backendService.fetchUserPreferences(accessToken: token)
            promptText = prefs.aiProfile ?? ""
            // Parse topics from interests if available
            let interests = prefs.interestsDictionary
            if let topicsList = interests["topics"] as? [String] {
                topics = topicsList
            }
            if let locationList = interests["locations"] as? [String] {
                locations = locationList
            }
            if let excludedTopics = interests["excluded_topics"] as? [String] {
                exclusions = excludedTopics
            }
            let profile = prefs.userProfileV2Dictionary
            if let current = profile["current_interests"] as? [String] {
                currentInterests = current
            }
            if let priorities = profile["utility_priorities"] as? [String] {
                utilityPriorities = priorities
            }
            if let depth = profile["content_depth"] as? String, !depth.isEmpty {
                contentDepth = depth
            }
            if let tone = profile["tone_preferences"] as? [String], !tone.isEmpty {
                tonePreferences = tone
            }
            if let context = profile["life_context"] as? String {
                lifeContext = context
            }
            isLoading = false
        } catch {
            errorMessage = error.localizedDescription
            isLoading = false
        }
    }
    
    func save() async -> Bool {
        guard !promptText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            errorMessage = "Prompt cannot be empty."
            return false
        }
        guard let token = authService.getAccessToken() else {
            errorMessage = "Authentication required"
            return false
        }
        
        isSaving = true
        errorMessage = nil
        
        do {
            let existingPreferences = try await backendService.fetchUserPreferences(accessToken: token)
            let profileV2 = buildUserProfileV2()

            _ = try await backendService.saveUserPreferences(
                accessToken: token,
                interests: existingPreferences.interestsDictionary,
                aiProfile: promptText,
                userProfileV2: profileV2,
                completed: true
            )
            isSaving = false
            return true
        } catch {
            errorMessage = error.localizedDescription
            isSaving = false
            return false
        }
    }

    func buildUserProfileV2() -> [String: Any] {
        [
            "stable_interests": topics,
            "current_interests": currentInterests.isEmpty ? Array(topics.prefix(4)) : currentInterests,
            "locations": locations,
            "excluded_topics": exclusions,
            "utility_priorities": utilityPriorities,
            "content_depth": contentDepth,
            "tone_preferences": tonePreferences,
            "life_context": lifeContext
        ]
    }
}
