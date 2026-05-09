//
//  TuneView.swift
//  Daily
//
//  The Tune surface. Composer at top, the user's live feed below, ephemeral
//  diff toast and 10-min Undo pill as overlays. No conversation bubbles —
//  the chat is the input, the feed is the artifact.
//
//  Per DESIGN.md "Tune": "The chat is the tuner. The conversation must
//  visibly change the feed. Diff is an ephemeral 2-second toast with Undo.
//  Never persistent."
//

import SwiftUI

struct TuneView: View {
    @ObservedObject var viewModel: TuneViewModel
    @Binding var selectedTab: MainTabView.AppTab
    @Environment(\.dismiss) private var dismiss
    @State private var presentedSourceArticle: NewsArticle?
    var presentedAsSheet: Bool = false

    private static let suggestedPrompts: [String] = [
        "Less national news",
        "More startups",
        "More long-reads"
    ]

    var body: some View {
        NavigationStack {
            ZStack(alignment: .top) {
                VStack(spacing: 0) {
                    TuneComposer(
                        text: $viewModel.inputText,
                        isStreaming: viewModel.isStreaming,
                        onSend: { Task { await viewModel.sendComposerMessage() } }
                    )

                    if viewModel.showSuggestedChips && viewModel.currentThread?.kind != .article {
                        suggestedChipsRow
                    }

                    if viewModel.isStreaming {
                        streamStatusPill
                    } else if let errorMessage = viewModel.errorMessage {
                        errorBanner(message: errorMessage)
                    }

                    Rectangle()
                        .fill(EditionPalette.sepia)
                        .frame(height: EditionPalette.hairlineWidth)

                    ScrollView(.vertical, showsIndicators: false) {
                        if let currentThread = viewModel.currentThread, currentThread.kind == .article {
                            articleContextSection(thread: currentThread)
                        } else {
                            LiveFeedPeek(articles: viewModel.articles) { article in
                                presentedSourceArticle = article
                            }
                            .padding(.top, AppSpacing.sm)
                        }
                    }
                }

                if let diff = viewModel.pendingDiff {
                    DiffToast(
                        summary: diff.summary,
                        onUndo: { Task { await viewModel.tapUndo() } }
                    )
                    .padding(.horizontal, AppSpacing.md)
                    .padding(.top, AppSpacing.sm)
                    .transition(.move(edge: .top).combined(with: .opacity))
                }

                if let undo = viewModel.persistedUndo {
                    HStack {
                        Spacer()
                        UndoPill(label: undo.label) {
                            Task { await viewModel.tapUndo() }
                        }
                        .padding(.trailing, AppSpacing.md)
                    }
                    .padding(.top, AppSpacing.sm)
                    .transition(.opacity)
                }
            }
            .animation(.easeOut(duration: 0.25), value: viewModel.pendingDiff != nil)
            .animation(.easeOut(duration: 0.25), value: viewModel.persistedUndo != nil)
            .background(EditionPalette.paper)
            .navigationTitle(navigationTitle)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    leadingToolbarButton
                }
            }
            .task {
                await viewModel.loadHomeIfNeeded()
                await viewModel.loadInitialFeed()
            }
            .sheet(item: $presentedSourceArticle) { article in
                ArticleDetailView(article: article)
            }
        }
    }

    // MARK: - Pieces

    private var navigationTitle: String {
        if let currentThread = viewModel.currentThread, currentThread.kind == .article {
            return "Tune for this story"
        }
        return "Tune your feed"
    }

    @ViewBuilder
    private var leadingToolbarButton: some View {
        if presentedAsSheet {
            Button("Done") { dismiss() }
                .font(AppTypography.bodyMedium)
                .foregroundStyle(EditionPalette.inkBlue)
        } else if viewModel.currentThread?.kind == .article {
            Button {
                HapticService.impact(.light)
                viewModel.goHome()
            } label: {
                HStack(spacing: AppSpacing.xs) {
                    Image(systemName: "chevron.left")
                        .font(AppTypography.navIcon)
                    Text("Tune")
                        .font(AppTypography.bodyMedium)
                }
                .foregroundStyle(EditionPalette.inkBlue)
            }
        }
    }

    private var suggestedChipsRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: AppSpacing.sm) {
                ForEach(Self.suggestedPrompts, id: \.self) { prompt in
                    SuggestedPromptChip(title: prompt) {
                        viewModel.inputText = prompt
                        Task { await viewModel.sendComposerMessage() }
                    }
                }
            }
            .padding(.horizontal, AppSpacing.md)
            .padding(.vertical, AppSpacing.sm)
        }
    }

    private var streamStatusPill: some View {
        HStack(spacing: AppSpacing.sm) {
            ProgressView()
                .scaleEffect(0.8)
                .tint(EditionPalette.inkBlue)
            Text(viewModel.displayedStreamStatus)
                .font(AppTypography.metaCaps)
                .tracking(0.8)
                .textCase(.uppercase)
                .foregroundStyle(EditionPalette.ink60)
        }
        .padding(.horizontal, AppSpacing.md)
        .padding(.vertical, AppSpacing.sm)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private func errorBanner(message: String) -> some View {
        HStack(spacing: AppSpacing.sm) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(AppTypography.navIcon)
                .foregroundStyle(EditionPalette.error)
            Text(message)
                .font(AppTypography.bodySmall)
                .foregroundStyle(EditionPalette.ink)
                .fixedSize(horizontal: false, vertical: true)
            Spacer()
            Button {
                HapticService.impact(.light)
                viewModel.errorMessage = nil
            } label: {
                Image(systemName: "xmark")
                    .font(AppTypography.sourceLabel)
                    .foregroundStyle(EditionPalette.ink60)
            }
        }
        .padding(.horizontal, AppSpacing.md)
        .padding(.vertical, AppSpacing.sm)
        .background(EditionPalette.paperSecondary)
    }

    @ViewBuilder
    private func articleContextSection(thread: ChatThread) -> some View {
        if let articleID = thread.articleID,
           let article = articleFromThread(articleID: articleID, articleTitle: thread.articleTitle) {
            ArticleContextHeader(article: article)
        } else {
            EmptyView()
        }
    }

    /// Build a minimal NewsArticle stub from thread metadata so the context
    /// header can render even if the originating article isn't in the
    /// current feed list. The full article is only needed for navigation
    /// (which we don't trigger from this context).
    private func articleFromThread(articleID: String, articleTitle: String?) -> NewsArticle? {
        if let inFeed = viewModel.articles.first(where: { $0.id == articleID }) {
            return inFeed
        }
        guard let title = articleTitle else { return nil }
        return NewsArticle(
            id: articleID,
            title: title,
            summary: nil,
            content: nil,
            author: nil,
            source: nil,
            imageURL: nil,
            publishedAt: nil,
            category: nil,
            url: nil
        )
    }
}

#Preview {
    TuneView(
        viewModel: TuneViewModel(),
        selectedTab: .constant(.tune)
    )
}
