//
//  ChatView.swift
//  Daily
//
//  Created by Muhammadjon on 11/4/25.
//

import SwiftUI
import UIKit

struct ChatView: View {
    @StateObject private var viewModel = ChatViewModel()
    @FocusState private var isInputFocused: Bool
    private let quickPrompts = [
        "Summarize today’s top headlines",
        "Why does this story matter?",
        "Give me a positive news highlight"
    ]
    
    var body: some View {
        NavigationStack {
            ZStack {
                AppleBackgroundView()
                
                VStack(spacing: 0) {
                    ScrollViewReader { proxy in
                        ScrollView(.vertical, showsIndicators: false) {
                            LazyVStack(spacing: AppSpacing.md) {
                                if viewModel.messages.isEmpty {
                                    introCard
                                    suggestionChips
                                } else {
                                    ForEach(viewModel.messages) { message in
                                        ChatBubbleView(message: message)
                                            .padding(.horizontal, AppSpacing.md)
                                    }
                                    
                                    if viewModel.isLoading {
                                        HStack(spacing: AppSpacing.sm) {
                                            ProgressView()
                                                .tint(BrandColors.primary)
                                            Text("Thinking…")
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
            .navigationTitle("AI Briefing")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(.ultraThinMaterial, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.light, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    if !viewModel.messages.isEmpty {
                        Button(action: {
                            let impactFeedback = UIImpactFeedbackGenerator(style: .medium)
                            impactFeedback.impactOccurred()
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
                    .fill(
                        LinearGradient(
                            colors: [
                                BrandColors.primary.opacity(0.18),
                                BrandColors.primary.opacity(0.10)
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 90, height: 90)
                
                Image(systemName: "bubble.left.and.bubble.right.fill")
                    .font(.system(size: 42, weight: .light))
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
        .glassCard()
        .padding(.horizontal, AppSpacing.lg)
    }
    
    var suggestionChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: AppSpacing.sm) {
                ForEach(quickPrompts, id: \.self) { prompt in
                    Button(action: {
                        let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                        impactFeedback.impactOccurred()
                        sendPrompt(prompt)
                    }) {
                        Text(prompt)
                            .font(AppTypography.caption1)
                            .fontWeight(.medium)
                            .foregroundColor(BrandColors.textPrimary)
                            .padding(.horizontal, AppSpacing.md)
                            .padding(.vertical, AppSpacing.sm + 2)
                            .background(
                                ZStack {
                                    Capsule()
                                        .fill(BrandColors.cardBackground.opacity(0.9))
                                    Capsule()
                                        .fill(.white.opacity(0.3))
                                        .blur(radius: 10)
                                }
                            )
                            .overlay(
                                Capsule()
                                    .stroke(Color.black.opacity(0.06), lineWidth: 0.5)
                            )
                            .clipShape(Capsule())
                            .shadow(color: Color.black.opacity(0.06), radius: 8, x: 0, y: 4)
                    }
                }
            }
            .padding(.horizontal, AppSpacing.lg)
        }
    }
    
    var inputArea: some View {
        VStack(spacing: AppSpacing.sm) {
            HStack(spacing: AppSpacing.sm) {
                TextField("Type a message…", text: $viewModel.inputText, axis: .vertical)
                    .font(AppTypography.body)
                    .padding(.horizontal, AppSpacing.md)
                    .padding(.vertical, AppSpacing.sm + 2)
                    .background(
                        ZStack {
                            RoundedRectangle(cornerRadius: AppCornerRadius.large)
                                .fill(BrandColors.cardBackground.opacity(0.95))
                            RoundedRectangle(cornerRadius: AppCornerRadius.large)
                                .fill(.white.opacity(0.3))
                                .blur(radius: 10)
                        }
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
                    let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                    impactFeedback.impactOccurred()
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
                ZStack {
                    BrandColors.cardBackground.opacity(0.9)
                    BrandColors.cardBackground.opacity(0.5)
                        .blur(radius: 10)
                }
            }
        }
    }
}

#Preview {
    ChatView()
}

