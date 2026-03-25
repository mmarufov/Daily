//
//  ChatView.swift
//  Daily
//
//  Created by Muhammadjon on 11/4/25.
//

import SwiftUI

struct ChatView: View {
    @ObservedObject var viewModel: ChatViewModel
    @Binding var selectedTab: MainTabView.AppTab
    @FocusState private var isInputFocused: Bool

    private let generalPrompts: [(icon: String, text: String)] = [
        ("list.bullet.clipboard", "Summarize today's top headlines"),
        ("lightbulb", "Why does this story matter?"),
        ("sun.max", "Give me a positive news highlight")
    ]

    private let articlePrompts: [(icon: String, text: String)] = [
        ("rectangle.3.group", "Break this down for me"),
        ("lightbulb", "Why does this matter?"),
        ("arrow.left.arrow.right", "What's the other side?"),
        ("eye", "What should I watch next?")
    ]

    var body: some View {
        NavigationStack {
            ZStack {
                ChatBackgroundView()

                VStack(spacing: 0) {
                    ScrollViewReader { proxy in
                        ScrollView(.vertical, showsIndicators: false) {
                            LazyVStack(spacing: AppSpacing.md) {
                                if viewModel.messages.isEmpty {
                                    if viewModel.hasArticleContext {
                                        articleContextCard
                                    } else {
                                        introCard
                                    }
                                    suggestionChips
                                } else {
                                    if viewModel.hasArticleContext {
                                        articleContextCard
                                    }

                                    ForEach(viewModel.messages) { message in
                                        ChatBubbleView(message: message)
                                            .padding(.horizontal, AppSpacing.md)
                                            .transition(.asymmetric(
                                                insertion: .move(edge: .bottom).combined(with: .opacity),
                                                removal: .opacity
                                            ))
                                    }
                                    .animation(.spring(response: 0.35, dampingFraction: 0.8), value: viewModel.messages.count)

                                    if viewModel.isLoading {
                                        TypingIndicatorView()
                                            .transition(.asymmetric(
                                                insertion: .scale(scale: 0.8).combined(with: .opacity),
                                                removal: .opacity
                                            ))
                                    }
                                }
                            }
                            .padding(.top, AppSpacing.lg)
                            .padding(.bottom, AppSpacing.xl)
                        }
                        .scrollDismissesKeyboard(.interactively)
                        .onChange(of: viewModel.messages.count) { _, _ in
                            scrollToBottom(proxy: proxy)
                        }
                        .onChange(of: viewModel.isLoading) { _, isLoading in
                            if isLoading {
                                scrollToBottom(proxy: proxy)
                            }
                        }
                    }

                    if let errorMessage = viewModel.errorMessage {
                        errorBanner(message: errorMessage)
                            .transition(.move(edge: .bottom).combined(with: .opacity))
                    }

                    inputArea
                }
                .animation(.easeInOut(duration: 0.3), value: viewModel.errorMessage != nil)
            }
            .navigationTitle(viewModel.hasArticleContext ? "Discuss Article" : "AI Briefing")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button {
                        HapticService.impact(.light)
                        withAnimation { selectedTab = .news }
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "chevron.left")
                                .font(AppTypography.navIcon)
                            Text("News")
                                .font(AppTypography.bodyMedium)
                        }
                        .foregroundColor(BrandColors.primary)
                    }
                }

                ToolbarItem(placement: .navigationBarTrailing) {
                    if !viewModel.messages.isEmpty || viewModel.hasArticleContext {
                        Button(action: {
                            HapticService.impact(.medium)
                            viewModel.clearChat()
                        }) {
                            HStack(spacing: AppSpacing.xs) {
                                Image(systemName: "trash")
                                    .font(AppTypography.labelSmall)
                                Text("Clear")
                                    .font(AppTypography.labelSmall)
                            }
                            .foregroundColor(BrandColors.error)
                        }
                    }
                }
            }
        }
    }

    private func scrollToBottom(proxy: ScrollViewProxy) {
        if let lastMessage = viewModel.messages.last {
            withAnimation(.easeInOut(duration: 0.3)) {
                proxy.scrollTo(lastMessage.id, anchor: .bottom)
            }
        }
    }
}

// MARK: - Private builders

private extension ChatView {
    var introCard: some View {
        VStack(spacing: AppSpacing.lg) {
            ZStack {
                Circle()
                    .fill(BrandColors.primary.opacity(0.08))
                    .frame(width: 80, height: 80)

                Image(systemName: "bubble.left.and.bubble.right.fill")
                    .font(AppTypography.iconLarge)
                    .foregroundColor(BrandColors.primary)
            }

            VStack(spacing: AppSpacing.sm) {
                Text("Start a conversation")
                    .font(AppTypography.title3)
                    .foregroundColor(BrandColors.textPrimary)

                Text("Ask anything about the news, get concise explanations, or let Daily craft a briefing for you.")
                    .font(AppTypography.subheadline)
                    .foregroundColor(BrandColors.textSecondary)
                    .multilineTextAlignment(.center)
                    .lineSpacing(2)
                    .padding(.horizontal, AppSpacing.lg)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(AppSpacing.xl)
        .glassEffect(.regular, in: RoundedRectangle(cornerRadius: AppCornerRadius.xlarge, style: .continuous))
        .padding(.horizontal, AppSpacing.lg)
    }

    var articleContextCard: some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    if let source = viewModel.articleContext?.displaySource {
                        Text(source.uppercased())
                            .font(AppTypography.metaLabel)
                            .tracking(0.6)
                            .foregroundColor(BrandColors.primary)
                    }
                    Text(viewModel.articleContext?.title ?? "")
                        .font(AppTypography.feedCardTitle)
                        .foregroundColor(BrandColors.textPrimary)
                        .lineLimit(2)
                }

                Spacer(minLength: AppSpacing.sm)

                Button {
                    HapticService.impact(.light)
                    withAnimation(.easeInOut(duration: 0.2)) {
                        viewModel.articleContext = nil
                    }
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(AppTypography.closeIcon)
                        .foregroundColor(BrandColors.textTertiary)
                }
            }
        }
        .padding(AppSpacing.md)
        .glassEffect(
            .regular.tint(BrandColors.primary),
            in: RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous)
        )
        .overlay(
            HStack {
                RoundedRectangle(cornerRadius: 2)
                    .fill(BrandColors.primary)
                    .frame(width: 3)
                    .padding(.vertical, AppSpacing.sm)
                Spacer()
            }
            .padding(.leading, 2),
            alignment: .leading
        )
        .padding(.horizontal, AppSpacing.md)
    }

    var suggestionChips: some View {
        let prompts = viewModel.hasArticleContext ? articlePrompts : generalPrompts
        return ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: AppSpacing.sm) {
                ForEach(prompts, id: \.text) { prompt in
                    Button(action: {
                        HapticService.impact(.light)
                        sendPrompt(prompt.text)
                    }) {
                        HStack(spacing: 6) {
                            Image(systemName: prompt.icon)
                                .font(AppTypography.chipIcon)
                                .foregroundColor(BrandColors.primary)
                            Text(prompt.text)
                                .font(AppTypography.caption1)
                                .fontWeight(.medium)
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

    func errorBanner(message: String) -> some View {
        HStack(spacing: AppSpacing.sm) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundColor(BrandColors.error)
            Text(message)
                .font(AppTypography.bodySmall)
                .foregroundColor(BrandColors.error)
                .lineLimit(2)
            Spacer()

            Button {
                HapticService.impact(.light)
                Task { await viewModel.retryLastMessage() }
            } label: {
                Text("Retry")
                    .font(AppTypography.labelSmall)
                    .foregroundColor(BrandColors.primary)
            }

            Button {
                withAnimation { viewModel.errorMessage = nil }
            } label: {
                Image(systemName: "xmark")
                    .font(AppTypography.metaLabel)
                    .foregroundColor(BrandColors.textTertiary)
            }
        }
        .padding(AppSpacing.md)
        .glassEffect(
            .regular.tint(BrandColors.error),
            in: RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous)
        )
        .padding(.horizontal, AppSpacing.md)
        .padding(.bottom, AppSpacing.sm)
    }

    var inputArea: some View {
        VStack(spacing: AppSpacing.sm) {
            HStack(spacing: AppSpacing.sm) {
                TextField("Type a message...", text: $viewModel.inputText, axis: .vertical)
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
                                isInputFocused
                                ? BrandColors.primary.opacity(0.4)
                                : Color(.separator),
                                lineWidth: isInputFocused ? 1.5 : 1
                            )
                    )
                    .lineLimit(1...5)
                    .focused($isInputFocused)
                    .onSubmit {
                        submitMessage()
                    }
                    .animation(.easeInOut(duration: 0.2), value: isInputFocused)

                sendButton
            }
        }
        .padding(.horizontal, AppSpacing.md)
        .padding(.vertical, AppSpacing.sm)
        .background(.ultraThinMaterial)
        .overlay(
            Rectangle()
                .frame(height: 0.5)
                .foregroundColor(BrandColors.textQuaternary.opacity(0.2)),
            alignment: .top
        )
    }

    @ViewBuilder
    var sendButton: some View {
        let canSend = !viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !viewModel.isLoading

        Button(action: {
            HapticService.impact(.light)
            submitMessage()
        }) {
            ZStack {
                if canSend {
                    Circle()
                        .fill(
                            LinearGradient(
                                colors: [BrandColors.primary, BrandColors.primaryDark],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                        .frame(width: 44, height: 44)
                        .shadow(color: BrandColors.primary.opacity(0.3), radius: 10, x: 0, y: 4)
                } else {
                    Circle()
                        .fill(BrandColors.textTertiary.opacity(0.6))
                        .frame(width: 44, height: 44)
                }

                if viewModel.isLoading {
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
        .scaleEffect(canSend ? 1.0 : 0.95)
        .animation(.easeInOut(duration: 0.2), value: canSend)
    }

    func submitMessage() {
        guard !viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        Task {
            await viewModel.sendMessage()
        }
    }

    func sendPrompt(_ prompt: String) {
        viewModel.inputText = prompt
        submitMessage()
    }
}

// MARK: - Typing Indicator

struct TypingIndicatorView: View {
    @State private var animating = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        HStack(alignment: .bottom, spacing: AppSpacing.sm) {
            HStack(spacing: 5) {
                ForEach(0..<3, id: \.self) { index in
                    Circle()
                        .fill(BrandColors.primary)
                        .frame(width: 8, height: 8)
                        .scaleEffect(reduceMotion ? 1.0 : (animating ? 1.0 : 0.5))
                        .opacity(reduceMotion ? 0.6 : (animating ? 1.0 : 0.3))
                        .animation(
                            reduceMotion ? nil :
                            .easeInOut(duration: 0.5)
                            .repeatForever(autoreverses: true)
                            .delay(Double(index) * 0.15),
                            value: animating
                        )
                }
            }
            .padding(.horizontal, AppSpacing.md)
            .padding(.vertical, AppSpacing.smLg)
            .glassEffect(.regular, in: RoundedRectangle(cornerRadius: AppCornerRadius.large, style: .continuous))

            Spacer(minLength: 50)
        }
        .padding(.horizontal, AppSpacing.md)
        .onAppear {
            guard !reduceMotion else { return }
            animating = true
        }
    }
}

// MARK: - Chat Bubble

struct ChatBubbleView: View {
    let message: ChatMessage

    var body: some View {
        HStack(alignment: .bottom, spacing: AppSpacing.sm) {
            if message.isUser {
                Spacer(minLength: 50)
            }

            VStack(alignment: message.isUser ? .trailing : .leading, spacing: 4) {
                if message.isUser {
                    userBubble
                } else {
                    aiBubble
                }

                Text(message.timestamp, style: .time)
                    .font(AppTypography.caption2)
                    .foregroundColor(BrandColors.textTertiary)
                    .padding(.horizontal, AppSpacing.xs)
            }

            if !message.isUser {
                Spacer(minLength: 50)
            }
        }
    }

    private var userBubble: some View {
        Text(message.content)
            .font(AppTypography.body)
            .foregroundColor(.white)
            .padding(.horizontal, AppSpacing.md)
            .padding(.vertical, AppSpacing.smPlus)
            .background(
                LinearGradient(
                    colors: [BrandColors.primaryLight, BrandColors.primaryDark],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
            )
            .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.large, style: .continuous))
            .shadow(color: BrandColors.primary.opacity(0.2), radius: 10, x: 0, y: 4)
    }

    private var aiBubble: some View {
        Text(message.content)
            .font(AppTypography.body)
            .foregroundColor(BrandColors.textPrimary)
            .textSelection(.enabled)
            .padding(.horizontal, AppSpacing.md)
            .padding(.vertical, AppSpacing.smPlus)
            .glassEffect(.clear, in: RoundedRectangle(cornerRadius: AppCornerRadius.large, style: .continuous))
    }
}

#Preview {
    ChatView(viewModel: ChatViewModel(), selectedTab: .constant(.chat))
}
