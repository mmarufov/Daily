//
//  TuneViewModel.swift
//  Daily
//
//  Renamed from ChatViewModel. Drives the Tune surface: streaming turn
//  orchestration + a live feed below the composer + DiffToast/Undo state.
//
//  Per DESIGN.md, no conversation bubbles are rendered — the streaming
//  pipeline still runs (the backend produces a turn), but the UI consumes
//  only `streamStatus`, `pendingDiff`, and the refreshed `articles` list.
//

import Foundation
import Combine

@MainActor
final class TuneViewModel: ObservableObject {
    // MARK: Existing chat state (preserved from ChatViewModel)

    @Published var threads: [ChatThread] = []
    @Published var currentThread: ChatThread?
    @Published var turns: [ChatTurn] = []
    @Published var inputText: String = ""
    @Published var isLoadingHome: Bool = false
    @Published var isPreparingThread: Bool = false
    @Published var isStreaming: Bool = false
    @Published var streamStatus: String?
    @Published var errorMessage: String?

    // MARK: New Tune state (Phase 4)

    /// Live feed shown below the composer. Populated by `loadInitialFeed()`
    /// and refreshed after every streaming turn completes.
    @Published var articles: [NewsArticle] = []

    /// Set when a `.weightDiff` event arrives. Drives `DiffToast`. Auto-cleared
    /// after 2.3s (slide 200ms + hold 2000ms + fade 300ms).
    @Published var pendingDiff: WeightDiffPayload?

    /// Held for 10 minutes after a diff toast clears. Drives the UndoPill.
    /// Tapping invokes `tapUndo()` which is a no-op until the backend ships
    /// an Undo endpoint.
    @Published var persistedUndo: PersistedUndo?

    /// Hides the suggested-prompt chips after the first turn.
    @Published var showSuggestedChips: Bool = true

    @Published var isLoadingFeed: Bool = false

    // MARK: Private

    private let backendService = BackendService.shared
    private let authService = AuthService.shared
    private var hasLoadedHome = false
    private var hasLoadedInitialFeed = false
    private var diffToastTask: Task<Void, Never>?
    private var undoExpiryTask: Task<Void, Never>?

    private static let diffToastDurationSeconds: Double = 2.3
    private static let undoPillDurationSeconds: Double = 600  // 10 minutes

    var todayThread: ChatThread? {
        threads.first(where: { $0.kind == .today })
    }

    var recentThreads: [ChatThread] {
        threads.filter { $0.kind != .today }
    }

    var homeIntents: [ChatIntent] {
        ChatIntent.homeIntents
    }

    var threadIntents: [ChatIntent] {
        currentThread?.kind == .article ? ChatIntent.articleIntents : []
    }

    /// Default streaming label when the backend hasn't pushed a `.status` yet.
    var displayedStreamStatus: String {
        if let streamStatus, !streamStatus.isEmpty {
            return streamStatus
        }
        return "Reading your feed…"
    }

    // MARK: - Loading

    func loadHomeIfNeeded() async {
        guard !hasLoadedHome else { return }
        await refreshHome()
        hasLoadedHome = true
    }

    func loadInitialFeed() async {
        guard !hasLoadedInitialFeed else { return }
        await refreshLiveFeed()
        hasLoadedInitialFeed = true
    }

    func refreshHome() async {
        guard let token = authService.getAccessToken() else {
            errorMessage = "Authentication required"
            return
        }

        isLoadingHome = true
        errorMessage = nil

        do {
            _ = try await ensureTodayThread(accessToken: token)
            threads = try await backendService.fetchChatThreads(accessToken: token)
            isLoadingHome = false
        } catch {
            isLoadingHome = false
            errorMessage = error.localizedDescription
        }
    }

    private func refreshLiveFeed() async {
        guard let token = authService.getAccessToken() else { return }
        isLoadingFeed = true
        defer { isLoadingFeed = false }
        do {
            let response = try await backendService.refreshFeedStatus(accessToken: token, limit: 20)
            articles = response.articles
        } catch {
            // Silent — leave the existing list in place. The composer remains usable.
        }
    }

    // MARK: - Threads

    func openThread(_ thread: ChatThread) async {
        guard let token = authService.getAccessToken() else {
            errorMessage = "Authentication required"
            return
        }

        isPreparingThread = true
        errorMessage = nil

        do {
            let detail = try await backendService.fetchChatThread(id: thread.id, accessToken: token)
            currentThread = detail.thread
            turns = detail.messages
            isPreparingThread = false
        } catch {
            isPreparingThread = false
            errorMessage = error.localizedDescription
        }
    }

    func goHome() {
        currentThread = nil
        turns = []
        streamStatus = nil
        errorMessage = nil
    }

    func startArticleDiscussion(_ article: NewsArticle) async {
        guard let token = authService.getAccessToken() else {
            errorMessage = "Authentication required"
            return
        }

        isPreparingThread = true
        errorMessage = nil

        do {
            let thread = try await backendService.createChatThread(
                CreateThreadRequest(
                    kind: .article,
                    title: article.title,
                    articleID: article.id,
                    articleTitle: article.title,
                    localDay: nil
                ),
                accessToken: token
            )
            threads = upsertThread(thread)
            await openThread(thread)
        } catch {
            isPreparingThread = false
            errorMessage = error.localizedDescription
        }
    }

    // MARK: - Sending

    func sendComposerMessage() async {
        let text = inputText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }

        inputText = ""
        showSuggestedChips = false
        await sendMessage(content: text, intent: nil)
    }

    func sendIntent(_ intent: ChatIntent) async {
        showSuggestedChips = false
        await sendMessage(content: intent.requestText, intent: intent)
    }

    func retryLastUserPrompt() async {
        guard let lastUser = turns.last(where: { $0.isUser }) else { return }
        inputText = lastUser.plainText
        await sendComposerMessage()
    }

    func regenerateLastResponse() async {
        guard let lastUser = turns.last(where: { $0.isUser }) else { return }
        await sendMessage(content: lastUser.plainText, intent: nil)
    }

    // MARK: - DiffToast / Undo

    func dismissDiffToast() {
        guard let diff = pendingDiff else { return }
        pendingDiff = nil
        let undo = PersistedUndo(
            id: UUID(),
            label: "Undo",
            diff: diff,
            expiresAt: Date().addingTimeInterval(Self.undoPillDurationSeconds)
        )
        persistedUndo = undo
        scheduleUndoExpiry(for: undo)
    }

    func tapUndo() async {
        // TODO(backend): call a real "reverse last weight-diff" endpoint here.
        // For now, just clear the pill so the user feels the action.
        persistedUndo = nil
        undoExpiryTask?.cancel()
    }

    private func scheduleDiffToastDismiss() {
        diffToastTask?.cancel()
        diffToastTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(Self.diffToastDurationSeconds))
            guard !Task.isCancelled else { return }
            await MainActor.run {
                self?.dismissDiffToast()
            }
        }
    }

    private func scheduleUndoExpiry(for undo: PersistedUndo) {
        undoExpiryTask?.cancel()
        undoExpiryTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(Self.undoPillDurationSeconds))
            guard !Task.isCancelled else { return }
            await MainActor.run {
                if self?.persistedUndo?.id == undo.id {
                    self?.persistedUndo = nil
                }
            }
        }
    }

    // MARK: - Streaming

    private func sendMessage(content: String, intent: ChatIntent?) async {
        guard let token = authService.getAccessToken() else {
            errorMessage = "Authentication required"
            return
        }

        do {
            let thread = try await ensureThreadForSending(accessToken: token, intent: intent)
            currentThread = thread

            let optimisticUser = ChatTurn.optimisticUser(threadID: thread.id, text: content)
            let optimisticAssistant = ChatTurn.optimisticAssistant(threadID: thread.id)
            turns.append(optimisticUser)
            turns.append(optimisticAssistant)

            isStreaming = true
            streamStatus = nil  // displayedStreamStatus falls back to "Reading your feed…"
            errorMessage = nil

            let stream = try await backendService.streamChatMessage(
                threadID: thread.id,
                request: StreamMessageRequest(content: content, intent: intent?.rawValue),
                accessToken: token
            )

            for try await event in stream {
                handle(event: event, optimisticAssistantID: optimisticAssistant.id)
            }

            isStreaming = false
            streamStatus = nil
            try await refreshCurrentThread(accessToken: token)
            threads = try await backendService.fetchChatThreads(accessToken: token)

            // Tune surface: refresh the live feed so the user sees the new edition
            // immediately, regardless of whether a weight-diff event arrived.
            await refreshLiveFeed()
        } catch {
            isStreaming = false
            streamStatus = nil
            errorMessage = error.localizedDescription
            if let token = authService.getAccessToken() {
                try? await refreshCurrentThread(accessToken: token)
                if let refreshedThreads = try? await backendService.fetchChatThreads(accessToken: token) {
                    threads = refreshedThreads
                }
            }
        }
    }

    private func ensureThreadForSending(
        accessToken: String,
        intent: ChatIntent?
    ) async throws -> ChatThread {
        if let currentThread {
            return currentThread
        }

        if intent?.group == .home {
            let thread = try await ensureTodayThread(accessToken: accessToken)
            threads = upsertThread(thread)
            return thread
        }

        let thread = try await backendService.createChatThread(
            CreateThreadRequest(
                kind: .manual,
                title: nil,
                articleID: nil,
                articleTitle: nil,
                localDay: nil
            ),
            accessToken: accessToken
        )
        threads = upsertThread(thread)
        return thread
    }

    private func ensureTodayThread(accessToken: String) async throws -> ChatThread {
        let formatter = DateFormatter()
        formatter.calendar = Calendar(identifier: .gregorian)
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"

        let thread = try await backendService.createChatThread(
            CreateThreadRequest(
                kind: .today,
                title: "Today",
                articleID: nil,
                articleTitle: nil,
                localDay: formatter.string(from: Date())
            ),
            accessToken: accessToken
        )
        return thread
    }

    private func refreshCurrentThread(accessToken: String) async throws {
        guard let currentThread else { return }
        let detail = try await backendService.fetchChatThread(id: currentThread.id, accessToken: accessToken)
        self.currentThread = detail.thread
        self.turns = detail.messages
    }

    private func handle(event: StreamingEvent, optimisticAssistantID: String) {
        switch event {
        case .meta(let payload):
            currentThread = payload.thread
            threads = upsertThread(payload.thread)
        case .status(let payload):
            streamStatus = payload.label
        case .sectionOpen(let payload):
            appendStreamingBlock(
                optimisticAssistantID: optimisticAssistantID,
                index: payload.index,
                kind: payload.kind,
                heading: payload.heading
            )
        case .sectionDelta(let payload):
            appendStreamingDelta(
                optimisticAssistantID: optimisticAssistantID,
                index: payload.index,
                kind: payload.kind,
                delta: payload.delta
            )
        case .sources(let payload):
            mutateAssistantTurn(id: optimisticAssistantID) { turn in
                turn.sources = payload.sources
            }
        case .followUps(let payload):
            mutateAssistantTurn(id: optimisticAssistantID) { turn in
                turn.followUps = payload.followUps
            }
        case .done(let payload):
            if let index = turns.firstIndex(where: { $0.id == optimisticAssistantID }) {
                turns[index] = payload.message
            }
        case .error(let payload):
            errorMessage = payload.detail
        case .weightDiff(let payload):
            pendingDiff = payload
            scheduleDiffToastDismiss()
        }
    }

    private func appendStreamingBlock(
        optimisticAssistantID: String,
        index: Int,
        kind: AssistantBlockKind,
        heading: String?
    ) {
        mutateAssistantTurn(id: optimisticAssistantID) { turn in
            guard !turn.blocks.contains(where: { $0.id == streamingBlockID(index: index) }) else { return }
            turn.blocks.append(
                AssistantBlock(
                    id: streamingBlockID(index: index),
                    kind: kind,
                    heading: heading,
                    text: "",
                    items: nil
                )
            )
        }
    }

    private func appendStreamingDelta(
        optimisticAssistantID: String,
        index: Int,
        kind: AssistantBlockKind,
        delta: String
    ) {
        mutateAssistantTurn(id: optimisticAssistantID) { turn in
            if !turn.blocks.contains(where: { $0.id == streamingBlockID(index: index) }) {
                turn.blocks.append(
                    AssistantBlock(
                        id: streamingBlockID(index: index),
                        kind: kind,
                        heading: nil,
                        text: "",
                        items: nil
                    )
                )
            }

            if let blockIndex = turn.blocks.firstIndex(where: { $0.id == streamingBlockID(index: index) }) {
                turn.blocks[blockIndex].text = (turn.blocks[blockIndex].text ?? "") + delta
            }
            turn.plainText += delta
        }
    }

    private func mutateAssistantTurn(id: String, _ mutate: (inout ChatTurn) -> Void) {
        guard let index = turns.firstIndex(where: { $0.id == id }) else { return }
        mutate(&turns[index])
    }

    private func upsertThread(_ thread: ChatThread) -> [ChatThread] {
        var updated = threads
        if let index = updated.firstIndex(where: { $0.id == thread.id }) {
            updated[index] = thread
        } else {
            updated.insert(thread, at: 0)
        }
        return updated.sorted { lhs, rhs in
            if lhs.kind == .today && rhs.kind != .today { return true }
            if lhs.kind != .today && rhs.kind == .today { return false }
            return (lhs.updatedAt ?? .distantPast) > (rhs.updatedAt ?? .distantPast)
        }
    }

    private func streamingBlockID(index: Int) -> String {
        "stream-\(index)"
    }
}
