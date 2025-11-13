//
//  OnboardingChatView.swift
//  Daily
//
//  Full-screen onboarding chat for collecting user interests.
//

import SwiftUI
import UIKit

struct OnboardingChatView: View {
    @StateObject private var viewModel = OnboardingChatViewModel()
    @Environment(\.dismiss) private var dismiss
    
    /// Called after preferences are successfully saved.
    var onCompleted: (() -> Void)?
    
    init(onCompleted: (() -> Void)? = nil) {
        self.onCompleted = onCompleted
    }
    
    var body: some View {
        NavigationView {
            ZStack {
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
                                            
                                            Image(systemName: "slider.horizontal.3")
                                                .font(.system(size: 36, weight: .light))
                                                .foregroundColor(BrandColors.primary)
                                        }
                                        
                                        VStack(spacing: AppSpacing.xs) {
                                            Text("Personalize your Daily")
                                                .font(AppTypography.title3)
                                                .foregroundColor(BrandColors.textPrimary)
                                            Text("Tell me what kind of news you care about and what you want to avoid.")
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
                                            Text("Thinking about your feed...")
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
                    HStack(spacing: AppSpacing.sm) {
                        TextField("Type your interests...", text: $viewModel.inputText, axis: .vertical)
                            .font(AppTypography.body)
                            .padding(.horizontal, AppSpacing.md)
                            .padding(.vertical, AppSpacing.sm)
                            .background(BrandColors.secondaryBackground)
                            .cornerRadius(AppCornerRadius.large)
                            .lineLimit(1...5)
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
            .navigationTitle("Your Daily preferences")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Close") {
                        dismiss()
                    }
                    .font(AppTypography.body)
                }
                
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Save") {
                        let impactFeedback = UIImpactFeedbackGenerator(style: .medium)
                        impactFeedback.impactOccurred()
                        
                        Task {
                            do {
                                try await viewModel.saveOnboardingPreferences()
                                NotificationCenter.default.post(name: .onboardingCompleted, object: nil)
                                onCompleted?()
                                dismiss()
                            } catch {
                                // error is already surfaced via viewModel.errorMessage
                            }
                        }
                    }
                    .disabled(viewModel.messages.isEmpty || viewModel.isSaving)
                }
            }
        }
    }
}

// MARK: - Notifications

extension Notification.Name {
    static let onboardingCompleted = Notification.Name("OnboardingCompleted")
}



