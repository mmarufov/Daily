//
//  ChatView.swift
//  Daily
//
//  Created by Muhammadjon on 11/4/25.
//

import SwiftUI

struct ChatView: View {
    @ObservedObject var viewModel: ChatViewModel
    @FocusState private var isInputFocused: Bool

    private let generalPrompts = [
        "Summarize today's top headlines",
        "Why does this story matter?",
        "Give me a positive news highlight"
    ]

    private let articlePrompts = [
        "Break this down for me",
        "Why does this matter?",
        "What's the other side?",
        "What should I watch next?"
    ]

    var body: some View {
        NavigationStack {
            ZStack {
                Color(.systemBackground).ignoresSafeArea()

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
                                    }

                                    if viewModel.isLoading {
                                        HStack(spacing: AppSpacing.sm) {
                                            ProgressView()
                                                .tint(BrandColors.primary)
                                            Text("Thinking...")
                                                .font(AppTypography.bodySmall)
                                                .foregroundColor(BrandColors.textSecondary)
                                            Spacer()
                                        }
                                        .padding(.horizontal, AppSpacing.md)
                                        .padding(.vertical, AppSpacing.sm)
                                    }
                                }
                            }
                            .padding(.top, AppSpacing.lg)
                            .padding(.bottom, AppSpacing.xl)
                        }
                        .onChange(of: viewModel.messages.count) { _ in
                            if let lastMessage = viewModel.messages.last {
                                withAnimation(.easeInOut(duration: 0.25)) {
                                    proxy.scrollTo(lastMessage.id, anchor: .bottom)
                                }
                            }
                        }
                    }

                    if let errorMessage = viewModel.errorMessage {
                        HStack(spacing: AppSpacing.sm) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundColor(BrandColors.error)
                            Text(errorMessage)
                                .font(AppTypography.bodySmall)
                                .foregroundColor(BrandColors.error)
                            Spacer()
                        }
                        .padding(AppSpacing.md)
                        .background(BrandColors.error.opacity(0.12))
                        .cornerRadius(AppCornerRadius.medium)
                        .padding(.horizontal, AppSpacing.md)
                        .padding(.bottom, AppSpacing.sm)
                    }

                    inputArea
                }
            }
            .navigationTitle(viewModel.hasArticleContext ? "Discuss Article" : "AI Briefing")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    if !viewModel.messages.isEmpty || viewModel.hasArticleContext {
                        Button(action: {
                            HapticService.impact(.medium)
                            viewModel.clearChat()
                        }) {
                            HStack(spacing: AppSpacing.xs) {
                                Image(systemName: "trash")
                                    .font(.system(size: 13, weight: .medium))
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
                    .font(.system(size: 36, weight: .light))
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
        .padding(.horizontal, AppSpacing.lg)
    }

    var articleContextCard: some View {
        VStack(alignment: .leading, spacing: AppSpacing.sm) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 4) {
                    if let source = viewModel.articleContext?.displaySource {
                        Text(source.uppercased())
                            .font(.system(size: 11, weight: .semibold))
                            .tracking(0.6)
                            .foregroundColor(BrandColors.primary)
                    }
                    Text(viewModel.articleContext?.title ?? "")
                        .font(.system(size: 16, weight: .semibold, design: .serif))
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
                        .font(.system(size: 20))
                        .foregroundColor(BrandColors.textTertiary)
                }
            }
        }
        .padding(AppSpacing.md)
        .background(
            RoundedRectangle(cornerRadius: AppCornerRadius.medium)
                .fill(Color(.secondarySystemGroupedBackground))
        )
        .overlay(
            RoundedRectangle(cornerRadius: AppCornerRadius.medium)
                .stroke(BrandColors.primary.opacity(0.15), lineWidth: 1)
        )
        .padding(.horizontal, AppSpacing.md)
    }

    var suggestionChips: some View {
        let prompts = viewModel.hasArticleContext ? articlePrompts : generalPrompts
        return ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: AppSpacing.sm) {
                ForEach(prompts, id: \.self) { prompt in
                    Button(action: {
                        HapticService.impact(.light)
                        sendPrompt(prompt)
                    }) {
                        Text(prompt)
                            .font(AppTypography.caption1)
                            .fontWeight(.medium)
                            .foregroundColor(BrandColors.textPrimary)
                            .padding(.horizontal, AppSpacing.md)
                            .padding(.vertical, AppSpacing.sm + 2)
                            .background(
                                Capsule()
                                    .fill(Color(.secondarySystemGroupedBackground))
                            )
                            .overlay(
                                Capsule()
                                    .stroke(Color(.separator).opacity(0.3), lineWidth: 0.5)
                            )
                            .clipShape(Capsule())
                    }
                }
            }
            .padding(.horizontal, AppSpacing.lg)
        }
    }

    var inputArea: some View {
        VStack(spacing: AppSpacing.sm) {
            HStack(spacing: AppSpacing.sm) {
                TextField("Type a message...", text: $viewModel.inputText, axis: .vertical)
                    .font(AppTypography.body)
                    .padding(.horizontal, AppSpacing.md)
                    .padding(.vertical, AppSpacing.sm + 2)
                    .background(
                        RoundedRectangle(cornerRadius: AppCornerRadius.large)
                            .fill(Color(.secondarySystemGroupedBackground))
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: AppCornerRadius.large)
                            .stroke(
                                isInputFocused
                                ? BrandColors.primary.opacity(0.4)
                                : Color.black.opacity(0.08),
                                lineWidth: isInputFocused ? 1.5 : 1
                            )
                    )
                    .lineLimit(1...5)
                    .focused($isInputFocused)
                    .onSubmit {
                        submitMessage()
                    }
                    .animation(.easeInOut(duration: 0.2), value: isInputFocused)

                Button(action: {
                    HapticService.impact(.light)
                    submitMessage()
                }) {
                    ZStack {
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading
                                    ? [
                                        BrandColors.textTertiary,
                                        BrandColors.textTertiary.opacity(0.8)
                                    ]
                                    : [
                                        BrandColors.primary,
                                        BrandColors.primaryDark
                                    ],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                            .frame(width: 44, height: 44)
                            .shadow(
                                color: viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading
                                ? Color.clear
                                : BrandColors.primary.opacity(0.3),
                                radius: 10,
                                x: 0,
                                y: 4
                            )

                        if viewModel.isLoading {
                            ProgressView()
                                .progressViewStyle(CircularProgressViewStyle(tint: .white))
                        } else {
                            Image(systemName: "arrow.up")
                                .font(.system(size: 15, weight: .semibold))
                                .foregroundColor(.white)
                        }
                    }
                }
                .disabled(viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading)
                .scaleEffect(viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading ? 0.95 : 1.0)
                .animation(.easeInOut(duration: 0.2), value: viewModel.inputText.isEmpty)
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

struct ChatBubbleView: View {
    let message: ChatMessage

    var body: some View {
        HStack(alignment: .bottom, spacing: AppSpacing.sm) {
            if message.isUser {
                Spacer(minLength: 50)
            }

            VStack(alignment: message.isUser ? .trailing : .leading, spacing: 4) {
                Text(message.content)
                    .font(AppTypography.body)
                    .padding(.horizontal, AppSpacing.md)
                    .padding(.vertical, AppSpacing.sm + 2)
                    .background(bubbleBackground)
                    .foregroundColor(message.isUser ? .white : BrandColors.textPrimary)
                    .cornerRadius(AppCornerRadius.large)
                    .overlay(
                        RoundedRectangle(cornerRadius: AppCornerRadius.large)
                            .stroke(
                                message.isUser
                                ? Color.white.opacity(0.25)
                                : Color.black.opacity(0.06),
                                lineWidth: 0.5
                            )
                    )
                    .shadow(
                        color: message.isUser
                            ? BrandColors.primary.opacity(0.2)
                            : Color.black.opacity(0.06),
                        radius: 10,
                        x: 0,
                        y: 4
                    )
                    .shadow(
                        color: message.isUser
                            ? Color.clear
                            : Color.black.opacity(0.02),
                        radius: 4,
                        x: 0,
                        y: 2
                    )

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

    private var bubbleBackground: some View {
        Group {
            if message.isUser {
                LinearGradient(
                    colors: [BrandColors.primaryLight, BrandColors.primaryDark],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
            } else {
                Color(.secondarySystemGroupedBackground)
            }
        }
    }
}

#Preview {
    ChatView(viewModel: ChatViewModel())
}
