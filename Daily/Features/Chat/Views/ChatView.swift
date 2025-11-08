//
//  ChatView.swift
//  Daily
//
//  Created by Muhammadjon on 11/4/25.
//

import SwiftUI

struct ChatView: View {
    @StateObject private var viewModel = ChatViewModel()
    @FocusState private var isInputFocused: Bool
    
    var body: some View {
        NavigationView {
            ZStack {
                // Background
                BrandColors.background
                    .ignoresSafeArea()
                
                VStack(spacing: 0) {
                    // Messages list
                    ScrollViewReader { proxy in
                        ScrollView {
                            LazyVStack(spacing: AppSpacing.md) {
                                if viewModel.messages.isEmpty {
                                    VStack(spacing: AppSpacing.lg) {
                                        ZStack {
                                            Circle()
                                                .fill(AppGradients.primary.opacity(0.15))
                                                .frame(width: 100, height: 100)
                                            
                                            Image(systemName: "bubble.left.and.bubble.right.fill")
                                                .font(.system(size: 45, weight: .medium))
                                                .foregroundColor(BrandColors.primary)
                                        }
                                        
                                        VStack(spacing: AppSpacing.sm) {
                                            Text("Start a conversation")
                                                .font(AppTypography.headlineLarge)
                                                .foregroundColor(BrandColors.textPrimary)
                                            Text("Ask me anything about the news!")
                                                .font(AppTypography.bodyMedium)
                                                .foregroundColor(BrandColors.textSecondary)
                                                .multilineTextAlignment(.center)
                                        }
                                    }
                                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                                    .padding(AppSpacing.xl)
                                } else {
                                    ForEach(viewModel.messages) { message in
                                        ChatBubbleView(message: message)
                                            .padding(.horizontal, AppSpacing.md)
                                    }
                                    
                                    if viewModel.isLoading {
                                        HStack(spacing: AppSpacing.sm) {
                                            ProgressView()
                                                .tint(BrandColors.primary)
                                                .padding(AppSpacing.sm)
                                            Text("AI is thinking...")
                                                .font(AppTypography.bodySmall)
                                                .foregroundColor(BrandColors.textSecondary)
                                            Spacer()
                                        }
                                        .padding(.horizontal, AppSpacing.md)
                                        .padding(.vertical, AppSpacing.sm)
                                    }
                                }
                            }
                            .padding(.vertical, AppSpacing.md)
                        }
                        .onChange(of: viewModel.messages.count) { _ in
                            if let lastMessage = viewModel.messages.last {
                                withAnimation(.easeInOut(duration: 0.3)) {
                                    proxy.scrollTo(lastMessage.id, anchor: .bottom)
                                }
                            }
                        }
                    }
                    
                    // Error message
                    if let errorMessage = viewModel.errorMessage {
                        HStack(spacing: AppSpacing.sm) {
                            Image(systemName: "exclamationmark.circle.fill")
                                .foregroundColor(BrandColors.error)
                            Text(errorMessage)
                                .font(AppTypography.bodySmall)
                                .foregroundColor(BrandColors.error)
                        }
                        .padding(AppSpacing.sm)
                        .background(BrandColors.error.opacity(0.1))
                        .cornerRadius(AppCornerRadius.small)
                        .padding(.horizontal, AppSpacing.md)
                        .padding(.vertical, AppSpacing.sm)
                    }
                    
                    // Input area
                    HStack(spacing: AppSpacing.md) {
                        TextField("Type a message...", text: $viewModel.inputText, axis: .vertical)
                            .font(AppTypography.bodyMedium)
                            .padding(AppSpacing.md)
                            .background(BrandColors.secondaryBackground)
                            .cornerRadius(AppCornerRadius.medium)
                            .overlay(
                                RoundedRectangle(cornerRadius: AppCornerRadius.medium)
                                    .stroke(isInputFocused ? BrandColors.primary : Color.clear, lineWidth: 2)
                            )
                            .lineLimit(1...5)
                            .focused($isInputFocused)
                            .onSubmit {
                                Task {
                                    await viewModel.sendMessage()
                                }
                            }
                        
                        Button(action: {
                            Task {
                                await viewModel.sendMessage()
                            }
                        }) {
                            ZStack {
                                Circle()
                                    .fill(
                                        viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading
                                        ? BrandColors.textTertiary
                                        : AppGradients.primary
                                    )
                                    .frame(width: 44, height: 44)
                                    .shadow(
                                        color: viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading
                                        ? Color.clear
                                        : BrandColors.primary.opacity(0.3),
                                        radius: 8,
                                        x: 0,
                                        y: 4
                                    )
                                
                                if viewModel.isLoading {
                                    ProgressView()
                                        .progressViewStyle(CircularProgressViewStyle(tint: .white))
                                } else {
                                    Image(systemName: "arrow.up")
                                        .font(.system(size: 16, weight: .bold))
                                        .foregroundColor(.white)
                                }
                            }
                        }
                        .disabled(viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading)
                    }
                    .padding(.horizontal, AppSpacing.md)
                    .padding(.vertical, AppSpacing.md)
                    .background(BrandColors.cardBackground)
                    .overlay(
                        Rectangle()
                            .frame(height: 1)
                            .foregroundColor(BrandColors.secondaryBackground),
                        alignment: .top
                    )
                }
            }
            .navigationTitle("AI Chat")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    if !viewModel.messages.isEmpty {
                        Button(action: {
                            viewModel.clearChat()
                        }) {
                            HStack(spacing: AppSpacing.xs) {
                                Image(systemName: "trash")
                                    .font(.system(size: 14, weight: .medium))
                                Text("Clear")
                                    .font(AppTypography.labelMedium)
                            }
                            .foregroundColor(BrandColors.error)
                        }
                    }
                }
            }
        }
    }
}

struct ChatBubbleView: View {
    let message: ChatMessage
    
    var body: some View {
        HStack(alignment: .bottom, spacing: AppSpacing.sm) {
            if message.isUser {
                Spacer(minLength: 60)
            }
            
            VStack(alignment: message.isUser ? .trailing : .leading, spacing: AppSpacing.xs) {
                Text(message.content)
                    .font(AppTypography.bodyMedium)
                    .padding(AppSpacing.md)
                    .background(
                        message.isUser
                        ? AppGradients.primary
                        : BrandColors.secondaryBackground
                    )
                    .foregroundColor(message.isUser ? .white : BrandColors.textPrimary)
                    .cornerRadius(AppCornerRadius.medium)
                    .overlay(
                        RoundedRectangle(cornerRadius: AppCornerRadius.medium)
                            .stroke(
                                message.isUser
                                ? Color.clear
                                : BrandColors.primary.opacity(0.1),
                                lineWidth: 1
                            )
                    )
                
                Text(message.timestamp, style: .time)
                    .font(AppTypography.labelSmall)
                    .foregroundColor(BrandColors.textTertiary)
                    .padding(.horizontal, AppSpacing.xs)
            }
            
            if !message.isUser {
                Spacer(minLength: 60)
            }
        }
    }
}

#Preview {
    ChatView()
}

