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
    @Published var utilityPriorities: [String] = []
    @Published var locations: [String] = []
    @Published var currentInterests: [String] = []
    @Published var contentDepth: String = "balanced"
    @Published var lifeContext: String = ""
    
    private let backendService = BackendService.shared
    private let authService = AuthService.shared
    private var pendingReaderMutation: ReaderMutation?
    @Published private(set) var savedCanonicalReader = false
    private var subscriptions = Set<AnyCancellable>()

    init() {
        authService.$currentUser.dropFirst().sink { [weak self] _ in
            guard let self else { return }
            self.messages = []; self.inputText = ""; self.lifeContext = ""
            self.locations = []; self.currentInterests = []; self.utilityPriorities = []
            self.pendingReaderMutation = nil
            self.savedCanonicalReader = false
        }.store(in: &subscriptions)
    }
    
    /// Prepend an AI greeting so the conversation starts warmly.
    func startConversation() {
        guard messages.isEmpty else { return }
        let greeting = ChatMessage(
            content: "Hey! I'm here to help personalize your Daily news feed. Tell me about yourself — what topics, people, or industries are you most interested in?",
            isUser: false
        )
        messages.append(greeting)
    }

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
        let session = authService.sessionGeneration
        
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
            guard session == authService.sessionGeneration else { return }
            
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
            throw ReaderClientError.authenticationRequired
        }
        let generation = authService.sessionGeneration
        
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
            do {
                let base = try await ReaderService.shared.fetch(token: token)
                guard generation == authService.sessionGeneration else { throw CancellationError() }
                guard !currentInterests.isEmpty else {
                    throw NSError(domain: "Onboarding", code: 1, userInfo: [NSLocalizedDescriptionKey: "Add at least one explicit Current focus below. Conversation suggestions are not saved automatically."])
                }
                // Preserve unrelated existing interests when this sheet is used to refine a profile.
                let kept = base.profile.intents.filter { intent in
                    !(intent.kind == "topic" && currentInterests.contains(intent.label)) &&
                    !(intent.kind == "place" && locations.contains(intent.label)) &&
                    !(intent.kind == "utility" && utilityPriorities.contains(intent.label))
                }
                let added = ReaderEditor.intents(base: pendingReaderMutation?.patch.intents ?? base.profile.intents, topics: [], current: currentInterests, places: locations, utilities: utilityPriorities)
                    .filter { $0.kind != "entity" }
                let patch = ReaderPatch(intents: kept + added, depth: contentDepth, context: lifeContext)
                if pendingReaderMutation?.patch != patch {
                    pendingReaderMutation = ReaderMutation(baseGeneration: base.generation, baseRevision: base.revision, patch: patch)
                }
                guard !base.needsReview else {
                    throw NSError(domain: "Onboarding", code: 2, userInfo: [NSLocalizedDescriptionKey: "Review your existing imported preferences in Personalization settings first."])
                }
                _ = try await ReaderService.shared.apply(pendingReaderMutation!, token: token)
                guard generation == authService.sessionGeneration else { throw CancellationError() }
                pendingReaderMutation = nil
                savedCanonicalReader = true
                isSaving = false
                NotificationCenter.default.post(name: .readerPreferencesCommitted, object: nil)
                return
            } catch ReaderClientError.unavailable {
                // Explicit compatibility path; no fallback after a rejected canonical write.
            }
            try await backendService.completeUserPreferences(
                accessToken: token,
                history: historyPayload,
                explicitContext: explicitContextPayload()
            )
            guard authService.sessionGeneration == generation else { throw CancellationError() }
            isSaving = false
        } catch {
            isSaving = false
            errorMessage = error.localizedDescription
            throw error
        }
    }

    private func explicitContextPayload() -> [String: Any] {
        [
            "utility_priorities": utilityPriorities,
            "locations": locations,
            "current_interests": currentInterests,
            "content_depth": contentDepth,
            "life_context": lifeContext
        ]
    }
}
