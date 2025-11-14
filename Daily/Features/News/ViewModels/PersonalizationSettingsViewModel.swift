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
            // We only care about updating the ai_profile here.
            // Pass an empty interests object – backend will keep the new prompt.
            _ = try await backendService.saveUserPreferences(
                accessToken: token,
                interests: [:],
                aiProfile: promptText,
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
}


