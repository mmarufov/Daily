//
//  OnboardingChatViewModel.swift
//  Daily
//
//  Created for personalized news onboarding.
//

import Foundation
import Combine

@MainActor
final class OnboardingChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var isLoading: Bool = false
    @Published var isSaving: Bool = false
    @Published var errorMessage: String?
    @Published var inputText: String = ""
    
    private let backendService = BackendService.shared
    private let authService = AuthService.shared
    
    func sendMessage() async {
        let messageText = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !messageText.isEmpty else { return }
        
        // Add user message
        let userMessage = ChatMessage(content: messageText, isUser: true)
        messages.append(userMessage)
        
        // Clear input
        inputText = ""
        isLoading = true
        errorMessage = nil
        
        // Get AI response (interest-focused chat)
        guard let token = authService.getAccessToken() else {
            errorMessage = "Authentication required"
            isLoading = false
            return
        }
        
        do {
            let historyPayload = messages.map { msg in
                [
                    "role": msg.isUser ? "user" : "assistant",
                    "content": msg.content
                ]
            }
            
            let response = try await backendService.sendInterestChatMessage(
                message: messageText,
                history: historyPayload,
                accessToken: token
            )
            
            // Add AI response
            let aiMessage = ChatMessage(content: response, isUser: false)
            messages.append(aiMessage)
            isLoading = false
        } catch {
            errorMessage = error.localizedDescription
            isLoading = false
        }
    }
    
    func clearChat() {
        messages = []
        errorMessage = nil
    }
    
    /// Summarize the conversation and save the user's preferences to the backend.
    func saveOnboardingPreferences() async throws {
        guard let token = authService.getAccessToken() else {
            errorMessage = "Authentication required"
            return
        }
        
        isSaving = true
        errorMessage = nil
        
        // Build full history for the backend summarizer
        let historyPayload: [[String: String]] = messages.map { msg in
            [
                "role": msg.isUser ? "user" : "assistant",
                "content": msg.content
            ]
        }
        
        do {
            _ = try await backendService.completeUserPreferences(
                accessToken: token,
                history: historyPayload
            )
            isSaving = false
        } catch {
            isSaving = false
            errorMessage = error.localizedDescription
            throw error
        }
    }
}


