//
//  ChatView.swift
//  Daily
//

import SwiftUI
import UIKit

struct ChatView: View {
    @ObservedObject var viewModel: ChatViewModel
    @Binding var selectedTab: MainTabView.AppTab
    @Environment(\.dismiss) private var dismiss
    @FocusState private var isInputFocused: Bool
    @State private var presentedSourceArticle: NewsArticle?
    var presentedAsSheet: Bool = false

    var body: some View {
        NavigationStack {
            ZStack {
                chatBackground
                    .ignoresSafeArea()

                VStack(spacing: 0) {
                    if viewModel.currentThread == nil {
                        ChatHomeContent(viewModel: viewModel)
                    } else if viewModel.isPreparingThread {
                        threadLoadingState
                    } else {
                        ChatThreadContent(
                            viewModel: viewModel,
                            onOpenSource: { article in presentedSourceArticle = article }
                        )
                    }

                    if let errorMessage = viewModel.errorMessage {
                        errorBanner(message: errorMessage)
                    }

                    composer
                }
            }
            .navigationTitle(navigationTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    leadingToolbarButton
                }

                ToolbarItem(placement: .navigationBarTrailing) {
                    trailingToolbarButton
                }
            }
            .task {
                await viewModel.loadHomeIfNeeded()
            }
            .sheet(item: $presentedSourceArticle) { article in
                ArticleDetailView(article: article)
            }
        }
    }

    private var navigationTitle: String {
        if let currentThread = viewModel.currentThread {
            return currentThread.title
        }
        return "Daily Copilot"
    }

    private var leadingToolbarButton: some View {
        Group {
            if presentedAsSheet {
                Button("Done") {
                    dismiss()
                }
                .font(AppTypography.bodyMedium)
            } else if viewModel.currentThread != nil {
                Button {
                    HapticService.impact(.light)
                    viewModel.goHome()
                } label: {
                    HStack(spacing: AppSpacing.xs) {
                        Image(systemName: "chevron.left")
                            .font(AppTypography.navIcon)
                        Text("Copilot")
                            .font(AppTypography.bodyMedium)
                    }
                    .foregroundColor(BrandColors.primary)
                }
            }
        }
    }

    private var trailingToolbarButton: some View {
        Group {
            if !presentedAsSheet, viewModel.currentThread == nil {
                Button {
                    HapticService.impact(.light)
                    selectedTab = .news
                } label: {
                    Image(systemName: "newspaper")
                        .font(AppTypography.toolbarIcon)
                        .foregroundColor(BrandColors.primary)
                }
            } else if !presentedAsSheet, viewModel.currentThread != nil {
                Button("Home") {
                    HapticService.impact(.light)
                    viewModel.goHome()
                }
                .font(AppTypography.bodySmall)
                .foregroundColor(BrandColors.primary)
            }
        }
    }

    private var composer: some View {
        VStack(spacing: AppSpacing.sm) {
            if let currentThread = viewModel.currentThread, currentThread.kind == .article {
                articleContextHeader(thread: currentThread)
            }

            HStack(spacing: AppSpacing.sm) {
                TextField(composerPlaceholder, text: $viewModel.inputText, axis: .vertical)
                    .font(AppTypography.body)
                    .padding(.horizontal, AppSpacing.md)
                    .padding(.vertical, AppSpacing.smPlus)
                    .background(
                        RoundedRectangle(cornerRadius: AppCornerRadius.large, style: .continuous)
                            .fill(Color(.secondarySystemGroupedBackground))
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: AppCornerRadius.large, style: .continuous)
                            .stroke(
                                isInputFocused ? BrandColors.primary.opacity(0.35) : Color(.separator),
                                lineWidth: isInputFocused ? 1.5 : 1
                            )
                    )
                    .lineLimit(1...6)
                    .focused($isInputFocused)
                    .onSubmit {
                        submitComposer()
                    }

                Button {
                    HapticService.impact(.light)
                    submitComposer()
                } label: {
                    ZStack {
                        Circle()
                            .fill(canSend ? BrandColors.primary : BrandColors.textTertiary.opacity(0.55))
                            .frame(width: 46, height: 46)

                        if viewModel.isStreaming {
                            ProgressView()
                                .progressViewStyle(CircularProgressViewStyle(tint: .white))
                        } else {
                            Image(systemName: "arrow.up")
                                .font(AppTypography.actionLabel)
                                .foregroundColor(.white)
                        }
                    }
                }
                .disabled(!canSend)
            }
            .padding(.horizontal, AppSpacing.md)
            .padding(.top, AppSpacing.sm)
            .padding(.bottom, AppSpacing.smPlus)
            .background(.ultraThinMaterial)
            .overlay(alignment: .top) {
                Rectangle()
                    .fill(BrandColors.textQuaternary.opacity(0.15))
                    .frame(height: 0.5)
            }
        }
    }

    private var canSend: Bool {
        !viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !viewModel.isStreaming
    }

    private var composerPlaceholder: String {
        viewModel.currentThread?.kind == .article ? "Ask about this story..." : "Ask Daily anything about your news..."
    }

    private var chatBackground: some View {
        LinearGradient(
            colors: [
                BrandColors.background,
                BrandColors.primary.opacity(0.035),
                BrandColors.background
            ],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    private var threadLoadingState: some View {
        VStack(spacing: AppSpacing.md) {
            ProgressView()
                .scaleEffect(1.1)
            Text("Loading conversation...")
                .font(AppTypography.subheadline)
                .foregroundColor(BrandColors.textSecondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func articleContextHeader(thread: ChatThread) -> some View {
        HStack(spacing: AppSpacing.sm) {
            Image(systemName: "doc.text")
                .font(AppTypography.metaLabel)
                .foregroundColor(BrandColors.primary)
            Text(thread.articleTitle ?? thread.title)
                .font(AppTypography.caption1)
                .foregroundColor(BrandColors.textSecondary)
                .lineLimit(1)
            Spacer()
        }
        .padding(.horizontal, AppSpacing.md)
        .padding(.top, AppSpacing.sm)
    }

    private func errorBanner(message: String) -> some View {
        HStack(spacing: AppSpacing.sm) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundColor(BrandColors.error)
            Text(message)
                .font(AppTypography.bodySmall)
                .foregroundColor(BrandColors.error)
                .lineLimit(2)
            Spacer()

            Button("Retry") {
                Task { await viewModel.retryLastUserPrompt() }
            }
            .font(AppTypography.labelSmall)
            .foregroundColor(BrandColors.primary)
        }
        .padding(AppSpacing.md)
        .background(BrandColors.error.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous))
        .padding(.horizontal, AppSpacing.md)
        .padding(.bottom, AppSpacing.xs)
    }

    private func submitComposer() {
        guard canSend else { return }
        Task { await viewModel.sendComposerMessage() }
    }
}

private struct ChatHomeContent: View {
    @ObservedObject var viewModel: ChatViewModel

    var body: some View {
        ScrollView(.vertical, showsIndicators: false) {
            VStack(alignment: .leading, spacing: AppSpacing.lg) {
                intro

                if let todayThread = viewModel.todayThread {
                    todayCard(thread: todayThread)
                }

                intentSection

                if !viewModel.recentThreads.isEmpty {
                    recentSection
                }
            }
            .padding(.top, AppSpacing.md)
            .padding(.bottom, AppSpacing.xl)
        }
    }

    private var intro: some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm) {
            Text("Your news, with context")
                .font(AppTypography.articleTitle)
                .foregroundColor(BrandColors.textPrimary)

            Text("Daily Copilot turns your feed into a clean briefing, deeper analysis, and fast follow-up conversations grounded in the stories you already follow.")
                .font(AppTypography.subheadline)
                .foregroundColor(BrandColors.textSecondary)
                .lineSpacing(3)
        }
        .padding(.horizontal, AppSpacing.lg)
    }

    private func todayCard(thread: ChatThread) -> some View {
        Button {
            HapticService.impact(.light)
            Task {
                await viewModel.openThread(thread)
                if thread.messageCount == 0 {
                    await viewModel.sendIntent(.yourBriefing)
                }
            }
        } label: {
            VStack(alignment: .leading, spacing: AppSpacing.md) {
                Text("TODAY")
                    .font(AppTypography.metaLabel)
                    .tracking(0.8)
                    .foregroundColor(BrandColors.sourceText)

                Text(thread.title)
                    .font(AppTypography.feedHeroTitle)
                    .foregroundColor(BrandColors.textPrimary)

                Text(thread.lastMessagePreview ?? "Open your saved briefing workspace and let Daily synthesize the strongest signal across your feed.")
                    .font(AppTypography.bodyMedium)
                    .foregroundColor(BrandColors.textSecondary)
                    .lineLimit(3)

                HStack(spacing: AppSpacing.sm) {
                    Label("Open Today", systemImage: "sparkles")
                        .font(AppTypography.labelMedium)
                        .foregroundColor(BrandColors.primary)
                    Spacer()
                    if let updatedAt = thread.updatedAt {
                        Text(updatedAt.formatted(.relative(presentation: .named)))
                            .font(AppTypography.caption2)
                            .foregroundColor(BrandColors.textTertiary)
                    }
                }
            }
            .padding(AppSpacing.lg)
            .frame(maxWidth: .infinity, alignment: .leading)
            .glassEffect(.regular, in: RoundedRectangle(cornerRadius: AppCornerRadius.xlarge, style: .continuous))
        }
        .buttonStyle(.plain)
        .padding(.horizontal, AppSpacing.lg)
    }

    private var intentSection: some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm) {
            Text("Quick Takes")
                .font(AppTypography.sectionTitle)
                .foregroundColor(BrandColors.sectionHeader)
                .tracking(0.8)
                .padding(.horizontal, AppSpacing.lg)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: AppSpacing.sm) {
                    ForEach(viewModel.homeIntents) { intent in
                        Button {
                            HapticService.impact(.light)
                            Task { await viewModel.sendIntent(intent) }
                        } label: {
                            HStack(spacing: AppSpacing.xs) {
                                Image(systemName: intent.icon)
                                    .font(AppTypography.chipIcon)
                                    .foregroundColor(BrandColors.primary)
                                Text(intent.title)
                                    .font(AppTypography.caption1)
                                    .foregroundColor(BrandColors.textPrimary)
                            }
                            .padding(.horizontal, AppSpacing.md)
                            .padding(.vertical, AppSpacing.smPlus)
                            .glassEffect(.regular.interactive(), in: .capsule)
                        }
                    }
                }
                .padding(.horizontal, AppSpacing.lg)
            }
        }
    }

    private var recentSection: some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm) {
            Text("Recent")
                .font(AppTypography.sectionTitle)
                .foregroundColor(BrandColors.sectionHeader)
                .tracking(0.8)
                .padding(.horizontal, AppSpacing.lg)

            VStack(spacing: AppSpacing.sm) {
                ForEach(viewModel.recentThreads) { thread in
                    Button {
                        HapticService.impact(.light)
                        Task { await viewModel.openThread(thread) }
                    } label: {
                        HStack(alignment: .top, spacing: AppSpacing.md) {
                            Image(systemName: thread.kind == .article ? "doc.text" : "bubble.left.and.bubble.right")
                                .font(AppTypography.iconButton)
                                .foregroundColor(BrandColors.primary)
                                .frame(width: 22)

                            VStack(alignment: .leading, spacing: 4) {
                                Text(thread.title)
                                    .font(AppTypography.headline)
                                    .foregroundColor(BrandColors.textPrimary)
                                    .lineLimit(2)
                                if let preview = thread.lastMessagePreview {
                                    Text(preview)
                                        .font(AppTypography.bodySmall)
                                        .foregroundColor(BrandColors.textSecondary)
                                        .lineLimit(2)
                                }
                            }

                            Spacer()
                        }
                        .padding(AppSpacing.md)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color(.secondarySystemGroupedBackground))
                        .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.large, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, AppSpacing.lg)
        }
    }
}

private struct ChatThreadContent: View {
    @ObservedObject var viewModel: ChatViewModel
    let onOpenSource: (NewsArticle) -> Void

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView(.vertical, showsIndicators: false) {
                LazyVStack(alignment: .leading, spacing: AppSpacing.md) {
                    if viewModel.currentThread?.kind == .article {
                        articleIntentRow
                    }

                    ForEach(viewModel.turns) { turn in
                        if turn.isUser {
                            userTurn(turn)
                        } else {
                            assistantTurn(turn)
                        }
                    }

                    if viewModel.isStreaming, let status = viewModel.streamStatus {
                        streamingStatus(status: status)
                    }
                }
                .padding(.horizontal, AppSpacing.md)
                .padding(.top, AppSpacing.md)
                .padding(.bottom, AppSpacing.xl)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: viewModel.turns.count) { _, _ in
                scrollToBottom(with: proxy)
            }
            .onChange(of: viewModel.isStreaming) { _, _ in
                scrollToBottom(with: proxy)
            }
        }
    }

    private var articleIntentRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: AppSpacing.sm) {
                ForEach(viewModel.threadIntents) { intent in
                    Button {
                        HapticService.impact(.light)
                        Task { await viewModel.sendIntent(intent) }
                    } label: {
                        HStack(spacing: AppSpacing.xs) {
                            Image(systemName: intent.icon)
                                .font(AppTypography.chipIcon)
                                .foregroundColor(BrandColors.primary)
                            Text(intent.title)
                                .font(AppTypography.caption1)
                                .foregroundColor(BrandColors.textPrimary)
                        }
                        .padding(.horizontal, AppSpacing.md)
                        .padding(.vertical, AppSpacing.smPlus)
                        .glassEffect(.regular.interactive(), in: .capsule)
                    }
                }
            }
        }
    }

    private func userTurn(_ turn: ChatTurn) -> some View {
        HStack {
            Spacer(minLength: 48)

            VStack(alignment: .trailing, spacing: 4) {
                Text(turn.plainText)
                    .font(AppTypography.body)
                    .foregroundColor(.white)
                    .padding(.horizontal, AppSpacing.md)
                    .padding(.vertical, AppSpacing.smPlus)
                    .background(BrandColors.primary)
                    .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.large, style: .continuous))

                if let createdAt = turn.createdAt {
                    Text(createdAt, style: .time)
                        .font(AppTypography.caption2)
                        .foregroundColor(BrandColors.textTertiary)
                }
            }
        }
        .id(turn.id)
    }

    private func assistantTurn(_ turn: ChatTurn) -> some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm) {
            ForEach(turn.blocks) { block in
                AssistantBlockView(block: block)
            }

            if !turn.sources.isEmpty {
                SourceRailView(sources: turn.sources) { source in
                    onOpenSource(source.asNewsArticle)
                }
            }

            if !turn.followUps.isEmpty {
                FollowUpChipsView(followUps: turn.followUps) { followUp in
                    viewModel.inputText = followUp
                    Task { await viewModel.sendComposerMessage() }
                }
            }

            HStack(spacing: AppSpacing.md) {
                Button("Copy") {
                    UIPasteboard.general.string = turn.plainText
                }
                .font(AppTypography.caption1)
                .foregroundColor(BrandColors.textSecondary)

                ShareLink(item: turn.plainText) {
                    Text("Share")
                        .font(AppTypography.caption1)
                        .foregroundColor(BrandColors.textSecondary)
                }

                Button("Regenerate") {
                    Task { await viewModel.regenerateLastResponse() }
                }
                .font(AppTypography.caption1)
                .foregroundColor(BrandColors.textSecondary)

                Spacer()

                if turn.degraded {
                    Text("Fallback")
                        .font(AppTypography.caption2)
                        .foregroundColor(BrandColors.textTertiary)
                }
            }
            .padding(.top, AppSpacing.xs)
        }
        .padding(AppSpacing.md)
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.xlarge, style: .continuous))
        .id(turn.id)
    }

    private func streamingStatus(status: String) -> some View {
        HStack(spacing: AppSpacing.sm) {
            ProgressView()
                .tint(BrandColors.primary)
            Text(status)
                .font(AppTypography.bodySmall)
                .foregroundColor(BrandColors.textSecondary)
            Spacer()
        }
        .padding(AppSpacing.md)
        .background(Color(.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.large, style: .continuous))
    }

    private func scrollToBottom(with proxy: ScrollViewProxy) {
        if let lastTurn = viewModel.turns.last {
            withAnimation(.easeInOut(duration: 0.25)) {
                proxy.scrollTo(lastTurn.id, anchor: .bottom)
            }
        }
    }
}

private struct AssistantBlockView: View {
    let block: AssistantBlock

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm) {
            if let heading = block.heading, !heading.isEmpty {
                Text(heading.uppercased())
                    .font(AppTypography.metaLabel)
                    .tracking(0.8)
                    .foregroundColor(BrandColors.sourceText)
            }

            switch block.kind {
            case .answer:
                Text(block.text ?? "")
                    .font(AppTypography.body)
                    .foregroundColor(BrandColors.textPrimary)
                    .lineSpacing(5)
                    .fixedSize(horizontal: false, vertical: true)
            case .headline:
                Text(block.text ?? "")
                    .font(AppTypography.feedHeroTitle)
                    .foregroundColor(BrandColors.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            case .summary:
                Text(block.text ?? "")
                    .font(AppTypography.body)
                    .foregroundColor(BrandColors.textPrimary)
                    .lineSpacing(4)
            case .whyItMatters:
                Text(block.text ?? "")
                    .font(AppTypography.articleLeadIn)
                    .foregroundColor(BrandColors.textPrimary)
                    .lineSpacing(4)
                    .padding(.leading, AppSpacing.sm)
                    .overlay(alignment: .leading) {
                        Rectangle()
                            .fill(BrandColors.primary.opacity(0.6))
                            .frame(width: 2)
                    }
            case .bulletList, .timeline, .watchlist:
                VStack(alignment: .leading, spacing: AppSpacing.sm) {
                    ForEach(displayItems, id: \.self) { item in
                        HStack(alignment: .top, spacing: AppSpacing.sm) {
                            Circle()
                                .fill(BrandColors.primary)
                                .frame(width: 6, height: 6)
                                .padding(.top, 7)
                            Text(item)
                                .font(AppTypography.bodyMedium)
                                .foregroundColor(BrandColors.textPrimary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            case .body:
                Text(block.text ?? "")
                    .font(AppTypography.body)
                    .foregroundColor(BrandColors.textPrimary)
                    .lineSpacing(4)
            }
        }
    }

    private var displayItems: [String] {
        if let items = block.items, !items.isEmpty {
            return items
        }
        guard let text = block.text else { return [] }
        return text
            .split(separator: "\n")
            .map { line in
                line.replacingOccurrences(of: "^-\\s*", with: "", options: .regularExpression)
                    .trimmingCharacters(in: .whitespacesAndNewlines)
            }
            .filter { !$0.isEmpty }
    }
}

private struct SourceRailView: View {
    let sources: [SourceCard]
    let onOpen: (SourceCard) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm) {
            Text("Sources")
                .font(AppTypography.metaLabel)
                .tracking(0.8)
                .foregroundColor(BrandColors.sourceText)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: AppSpacing.sm) {
                    ForEach(sources) { source in
                        Button {
                            onOpen(source)
                        } label: {
                            VStack(alignment: .leading, spacing: AppSpacing.sm) {
                                Text((source.source ?? "Daily").uppercased())
                                    .font(AppTypography.caption2)
                                    .foregroundColor(BrandColors.sourceText)
                                Text(source.title)
                                    .font(AppTypography.headlineSmall)
                                    .foregroundColor(BrandColors.textPrimary)
                                    .lineLimit(3)
                                if let summary = source.summary {
                                    Text(summary)
                                        .font(AppTypography.caption1)
                                        .foregroundColor(BrandColors.textSecondary)
                                        .lineLimit(3)
                                }
                            }
                            .padding(AppSpacing.md)
                            .frame(width: 240, alignment: .leading)
                            .background(Color(.systemBackground))
                            .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.large, style: .continuous))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }
}

private struct FollowUpChipsView: View {
    let followUps: [String]
    let onTap: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm) {
            Text("Keep Going")
                .font(AppTypography.metaLabel)
                .tracking(0.8)
                .foregroundColor(BrandColors.sourceText)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: AppSpacing.sm) {
                    ForEach(followUps, id: \.self) { followUp in
                        Button {
                            onTap(followUp)
                        } label: {
                            Text(followUp)
                                .font(AppTypography.caption1)
                                .foregroundColor(BrandColors.textPrimary)
                                .padding(.horizontal, AppSpacing.md)
                                .padding(.vertical, AppSpacing.smPlus)
                                .background(Color(.systemBackground))
                                .clipShape(Capsule())
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
        }
    }
}

#Preview {
    ChatView(viewModel: ChatViewModel(), selectedTab: .constant(.chat))
}
