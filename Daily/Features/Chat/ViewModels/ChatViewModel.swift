//
//  ChatViewModel.swift
//  Daily
//
//  Created by Muhammadjon on 11/4/25.
//

import Foundation
import Combine

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var isLoading: Bool = false
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
        
        // Get AI response
        guard let token = authService.getAccessToken() else {
            errorMessage = "Authentication required"
            isLoading = false
            return
        }
        
        do {
            let response = try await backendService.sendChatMessage(
                message: messageText,
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
}

