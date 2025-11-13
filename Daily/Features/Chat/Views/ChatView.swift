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
                                    VStack(spacing: AppSpacing.xl) {
                                        ZStack {
                                            Circle()
                                                .fill(BrandColors.primary.opacity(0.08))
                                                .frame(width: 80, height: 80)
                                            
                                            Image(systemName: "bubble.left.and.bubble.right")
                                                .font(.system(size: 36, weight: .light))
                                                .foregroundColor(BrandColors.primary)
                                        }
                                        
                                        VStack(spacing: AppSpacing.xs) {
                                            Text("Start a conversation")
                                                .font(AppTypography.title3)
                                                .foregroundColor(BrandColors.textPrimary)
                                            Text("Ask me anything about the news!")
                                                .font(AppTypography.subheadline)
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
                    
                    // Input area - Apple style
                    HStack(spacing: AppSpacing.sm) {
                        TextField("Type a message...", text: $viewModel.inputText, axis: .vertical)
                            .font(AppTypography.body)
                            .padding(.horizontal, AppSpacing.md)
                            .padding(.vertical, AppSpacing.sm)
                            .background(BrandColors.secondaryBackground)
                            .cornerRadius(AppCornerRadius.large)
                            .overlay(
                                RoundedRectangle(cornerRadius: AppCornerRadius.large)
                                    .stroke(isInputFocused ? BrandColors.primary.opacity(0.3) : Color.clear, lineWidth: 1.5)
                            )
                            .lineLimit(1...5)
                            .focused($isInputFocused)
                            .onSubmit {
                                if !viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                                    Task {
                                        await viewModel.sendMessage()
                                    }
                                }
                            }
                        
                        Button(action: {
                            let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                            impactFeedback.impactOccurred()
                            
                            Task {
                                await viewModel.sendMessage()
                            }
                        }) {
                            ZStack {
                                Circle()
                                    .fill(
                                        viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading
                                        ? BrandColors.textTertiary
                                        : BrandColors.primary
                                    )
                                    .frame(width: 36, height: 36)
                                    .shadow(
                                        color: viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading
                                        ? Color.clear
                                        : BrandColors.primary.opacity(0.2),
                                        radius: 4,
                                        x: 0,
                                        y: 2
                                    )
                                
                                if viewModel.isLoading {
                                    ProgressView()
                                        .progressViewStyle(CircularProgressViewStyle(tint: .white))
                                        .scaleEffect(0.8)
                                } else {
                                    Image(systemName: "arrow.up")
                                        .font(.system(size: 14, weight: .semibold))
                                        .foregroundColor(.white)
                                }
                            }
                        }
                        .disabled(viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading)
                    }
                    .padding(.horizontal, AppSpacing.md)
                    .padding(.vertical, AppSpacing.sm)
                    .background(.ultraThinMaterial)
                    .overlay(
                        Rectangle()
                            .frame(height: 0.5)
                            .foregroundColor(BrandColors.textQuaternary.opacity(0.3)),
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
                    .padding(.vertical, AppSpacing.sm)
                    .background(
                        message.isUser
                        ? BrandColors.primary
                        : BrandColors.secondaryBackground
                    )
                    .foregroundColor(message.isUser ? .white : BrandColors.textPrimary)
                    .cornerRadius(AppCornerRadius.large)
                    .shadow(
                        color: message.isUser 
                            ? BrandColors.primary.opacity(0.15)
                            : Color.clear,
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
}

#Preview {
    ChatView()
}

