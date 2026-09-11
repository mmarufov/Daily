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
    @Published private(set) var reader: ReaderEnvelope?
    @Published var confirmsMigration = false
    // S10 batch E: both endpoints and BackendService methods have existed
    // since before this batch; nothing in the app ever called them from a
    // view. Legacy-serving only -- S5 write-blocks pins with 409 and
    // check_interest_evolution() returns 0 unconditionally when S5 is on
    // (interest_evolution.py:21-25), so these are hidden whenever `reader`
    // is set. See tasks/s10-learning-audit.md and -implementation-plan.md batch E.
    @Published private(set) var entityPins: [BackendService.EntityPin] = []
    @Published private(set) var interestSuggestions: [BackendService.InterestSuggestion] = []
    @Published var entityPinErrorMessage: String?
    private var loadedSession: UInt64?
    private var originalLegacyProfile: [String: Any] = [:]
    private var pendingMutation: ReaderMutation?
    private var pendingResetID: String?
    @Published var removedPolicyIDs = Set<String>()
    private var subscriptions = Set<AnyCancellable>()

    private let backendService = BackendService.shared
    private let authService = AuthService.shared

    init() {
        authService.$currentUser.dropFirst().sink { [weak self] _ in
            guard let self else { return }
            self.reader = nil
            self.loadedSession = nil
            self.pendingMutation = nil
            self.pendingResetID = nil
            self.removedPolicyIDs = []
            self.originalLegacyProfile = [:]
            self.promptText = ""
            self.topics = []; self.currentInterests = []; self.locations = []
            self.exclusions = []; self.utilityPriorities = []; self.lifeContext = ""
            self.entityPins = []; self.interestSuggestions = []; self.entityPinErrorMessage = nil
        }.store(in: &subscriptions)
    }

    func load() async {
        guard !isLoading else { return }
        guard let token = authService.getAccessToken() else {
            errorMessage = "Authentication required"
            return
        }

        isLoading = true
        let session = authService.sessionGeneration
        errorMessage = nil
        defer { isLoading = false }

        do {
            do {
                let result = try await ReaderService.shared.fetch(token: token)
                guard session == authService.sessionGeneration else { return }
                guard result.profile.schemaVersion == 3 else { throw ReaderClientError.invalidResponse }
                reader = result
                loadedSession = session
                pendingMutation = nil
                pendingResetID = nil
                removedPolicyIDs = []
                install(result.profile)
                return
            } catch ReaderClientError.unavailable {
                reader = nil // Only a disabled/absent capability permits the legacy adapter.
            }
            let prefs = try await backendService.fetchUserPreferences(accessToken: token)
            guard session == authService.sessionGeneration else { return }
            loadedSession = session
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
            originalLegacyProfile = profile
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
            // Legacy-serving only: the S5 branch above always `return`s before
            // reaching this point, so this never runs once S5 is on.
            async let pins = backendService.fetchEntityPins(accessToken: token)
            async let suggestions = backendService.fetchInterestSuggestions(accessToken: token)
            let (loadedPins, loadedSuggestions) = try await (pins, suggestions)
            guard session == authService.sessionGeneration else { return }
            entityPins = loadedPins
            interestSuggestions = loadedSuggestions.filter { $0.confidence.isFinite }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    /// Best-effort: entity pins failing to load must not block the rest of
    /// personalization settings from being usable. Kept separate from
    /// `errorMessage` (the save/load-critical path) for the same reason.
    func addEntityPin(name: String, type: String = "topic") async {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, let token = authService.getAccessToken() else { return }
        let session = authService.sessionGeneration
        entityPinErrorMessage = nil
        do {
            let pin = try await backendService.createEntityPin(name: trimmed, type: type, accessToken: token)
            guard session == authService.sessionGeneration else { return }
            guard !entityPins.contains(where: { $0.id == pin.id }) else { return }
            entityPins.append(pin)
        } catch {
            guard session == authService.sessionGeneration else { return }
            entityPinErrorMessage = error.localizedDescription
        }
    }

    func removeEntityPin(_ pin: BackendService.EntityPin) async {
        guard let token = authService.getAccessToken() else { return }
        let session = authService.sessionGeneration
        let previous = entityPins
        entityPins.removeAll { $0.id == pin.id }  // optimistic; restore on failure
        do {
            try await backendService.deleteEntityPin(id: pin.id, accessToken: token)
        } catch {
            guard session == authService.sessionGeneration else { return }
            entityPins = previous
            entityPinErrorMessage = error.localizedDescription
        }
    }

    func acceptInterestSuggestion(_ suggestion: BackendService.InterestSuggestion) async {
        guard let token = authService.getAccessToken() else { return }
        let session = authService.sessionGeneration
        do {
            try await backendService.acceptInterestSuggestion(id: suggestion.id, accessToken: token)
            guard session == authService.sessionGeneration else { return }
            interestSuggestions.removeAll { $0.id == suggestion.id }
            // Acceptance appends to interests server-side; reflect it without
            // a full reload so the reader sees the topic land immediately.
            if !topics.contains(suggestion.topic) { topics.append(suggestion.topic) }
        } catch {
            guard session == authService.sessionGeneration else { return }
            entityPinErrorMessage = error.localizedDescription
        }
    }

    func dismissInterestSuggestion(_ suggestion: BackendService.InterestSuggestion) async {
        guard let token = authService.getAccessToken() else { return }
        let session = authService.sessionGeneration
        let previous = interestSuggestions
        interestSuggestions.removeAll { $0.id == suggestion.id }  // optimistic; restore on failure
        do {
            try await backendService.dismissInterestSuggestion(id: suggestion.id, accessToken: token)
        } catch {
            guard session == authService.sessionGeneration else { return }
            interestSuggestions = previous
            entityPinErrorMessage = error.localizedDescription
        }
    }

    func save() async -> Bool {
        guard !isSaving else { return false }
        guard let token = authService.getAccessToken() else {
            errorMessage = "Authentication required"
            return false
        }
        
        isSaving = true
        let session = authService.sessionGeneration
        errorMessage = nil
        defer { isSaving = false }

        do {
            guard loadedSession == authService.sessionGeneration else { throw ReaderClientError.authenticationRequired }
            if let reader {
                guard !reader.needsReview || confirmsMigration else {
                    errorMessage = "Review the imported interests and exclusions, then confirm them before saving."
                    return false
                }
                let patch = ReaderPatch(
                    intents: ReaderEditor.intents(base: pendingMutation?.patch.intents ?? reader.profile.intents, topics: topics, current: currentInterests, places: locations, utilities: utilityPriorities),
                    policies: ReaderEditor.policies(base: pendingMutation?.patch.policies ?? reader.profile.policies, exclusions: exclusions)
                        .filter { !removedPolicyIDs.contains($0.id) },
                    depth: contentDepth, context: lifeContext
                )
                if pendingMutation?.patch != patch {
                    pendingMutation = ReaderMutation(baseGeneration: reader.generation, baseRevision: reader.revision, patch: patch, confirmMigration: confirmsMigration)
                }
                let committed = try await ReaderService.shared.apply(pendingMutation!, token: token)
                guard session == authService.sessionGeneration else { throw CancellationError() }
                self.reader = committed
                pendingMutation = nil
                NotificationCenter.default.post(name: .readerPreferencesCommitted, object: nil)
                return true
            }
            let existingPreferences = try await backendService.fetchUserPreferences(accessToken: token)
            guard session == authService.sessionGeneration else { throw CancellationError() }
            let profileV2 = buildUserProfileV2()
            var interests = existingPreferences.interestsDictionary
            interests["topics"] = topics
            interests["locations"] = locations
            interests["excluded_topics"] = exclusions

            _ = try await backendService.saveUserPreferences(
                accessToken: token,
                interests: interests,
                aiProfile: promptText,
                userProfileV2: profileV2,
                completed: true
            )
            guard session == authService.sessionGeneration else { throw CancellationError() }
            return true
        } catch {
            guard session == authService.sessionGeneration else { return false }
            errorMessage = error.localizedDescription
            return false
        }
    }

    func buildUserProfileV2() -> [String: Any] {
        originalLegacyProfile.merging([
            "stable_interests": topics,
            "current_interests": currentInterests,
            "locations": locations,
            "excluded_topics": exclusions,
            "utility_priorities": utilityPriorities,
            "content_depth": contentDepth,
            "tone_preferences": tonePreferences,
            "life_context": lifeContext
        ]) { _, edited in edited }
    }

    private func install(_ profile: ReaderProfile) {
        topics = profile.intents.filter { $0.kind == "topic" && $0.priority <= 1 }.map(\.label)
        currentInterests = profile.intents.filter { $0.kind == "topic" && $0.priority > 1 }.map(\.label)
        locations = profile.intents.filter { $0.kind == "place" }.map(\.label)
        utilityPriorities = profile.intents.filter { $0.kind == "utility" }.map(\.label)
        exclusions = profile.policies.filter { $0.kind == "lexical" }.map(\.value)
        contentDepth = profile.depth
        lifeContext = profile.context
    }

    func resetLearning() async {
        guard !isSaving, let reader, let token = authService.getAccessToken(), loadedSession == authService.sessionGeneration else { return }
        let session = authService.sessionGeneration
        isSaving = true
        defer { isSaving = false }
        do {
            if pendingResetID == nil { pendingResetID = UUID().uuidString }
            let result = try await ReaderService.shared.resetLearning(base: reader, operationID: pendingResetID!, token: token)
            guard session == authService.sessionGeneration else { return }
            self.reader = result
            pendingResetID = nil
            pendingMutation = nil
            ReaderFeedbackStore.shared.clear()
            ReadingEventTracker.shared.discardPending()
            NotificationCenter.default.post(name: .readerPreferencesCommitted, object: nil)
        } catch {
            guard session == authService.sessionGeneration else { return }
            errorMessage = error.localizedDescription
        }
    }
}
