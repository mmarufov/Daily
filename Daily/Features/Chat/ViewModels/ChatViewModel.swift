//
//  ChatViewModel.swift
//  Daily
//
//  Created by Muhammadjon on 11/4/25.
//

import Foundation
import SwiftUI
import Combine

@MainActor
final class ChatViewModel: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var isLoading: Bool = false
    @Published var errorMessage: String?
    @Published var inputText: String = ""
    @Published var articleContext: NewsArticle?

    var hasArticleContext: Bool { articleContext != nil }

    private let backendService = BackendService.shared
    private let authService = AuthService.shared

    func sendMessage() async {
        let messageText = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !messageText.isEmpty else { return }

        let userMessage = ChatMessage(content: messageText, isUser: true)
        messages.append(userMessage)

        inputText = ""
        isLoading = true
        errorMessage = nil

        guard let token = authService.getAccessToken() else {
            errorMessage = "Authentication required"
            isLoading = false
            return
        }

        do {
            let response = try await backendService.sendChatMessage(
                message: messageText,
                accessToken: token,
                history: buildHistory(),
                articleContext: buildArticleContext()
            )

            let aiMessage = ChatMessage(content: response, isUser: false)
            messages.append(aiMessage)
            isLoading = false
        } catch {
            errorMessage = error.localizedDescription
            isLoading = false

            let failedMessage = error.localizedDescription
            Task {
                try? await Task.sleep(for: .seconds(5))
                if self.errorMessage == failedMessage {
                    withAnimation(.easeOut(duration: 0.3)) {
                        self.errorMessage = nil
                    }
                }
            }
        }
    }

    func retryLastMessage() async {
        guard let lastUserMessage = messages.last(where: { $0.isUser }) else { return }
        errorMessage = nil
        if messages.last?.isUser == true {
            messages.removeLast()
        }
        inputText = lastUserMessage.content
        await sendMessage()
    }

    func startArticleDiscussion(_ article: NewsArticle) {
        messages = []
        errorMessage = nil
        articleContext = article
    }

    func clearChat() {
        messages = []
        errorMessage = nil
        articleContext = nil
    }

    // MARK: - Private

    private func buildHistory() -> [[String: String]]? {
        // Send all messages except the last one (which is the current user message
        // we just appended — the backend receives it as the `message` param).
        let prior = messages.dropLast()
        guard !prior.isEmpty else { return nil }

        return prior.map { msg in
            ["role": msg.isUser ? "user" : "assistant", "content": msg.content]
        }
    }

    private func buildArticleContext() -> [String: String]? {
        guard let article = articleContext else { return nil }

        var ctx: [String: String] = ["title": article.title]
        if let source = article.source { ctx["source"] = source }
        if let summary = article.summary { ctx["summary"] = summary }
        if let content = article.content {
            ctx["content"] = String(content.prefix(3000))
        }
        return ctx
    }
}
