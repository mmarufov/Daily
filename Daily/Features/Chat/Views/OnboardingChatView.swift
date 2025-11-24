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
    @FocusState private var isInputFocused: Bool
    
    /// Called after preferences are successfully saved.
    var onCompleted: (() -> Void)?
    
    init(onCompleted: (() -> Void)? = nil) {
        self.onCompleted = onCompleted
    }
    
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
                                } else {
                                    ForEach(viewModel.messages) { message in
                                        ChatBubbleView(message: message)
                                            .padding(.horizontal, AppSpacing.md)
                                    }
                                    
                                    if viewModel.isLoading {
                                        HStack(spacing: AppSpacing.sm) {
                                            ProgressView()
                                                .tint(BrandColors.primary)
                                            Text("Thinking about your feed…")
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
            .navigationTitle("Your Daily preferences")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(.ultraThinMaterial, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.light, for: .navigationBar)
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
                                // surfaced via error message
                            }
                        }
                    }
                    .disabled(viewModel.messages.isEmpty || viewModel.isSaving)
                }
            }
        }
    }
}

private extension OnboardingChatView {
    var introCard: some View {
        VStack(spacing: AppSpacing.sm) {
            Image(systemName: "slider.horizontal.3")
                .font(.system(size: 48, weight: .light))
                .foregroundColor(BrandColors.primary)
                .padding()
                .background(BrandColors.primary.opacity(0.15))
                .clipShape(Circle())
            
            Text("Personalize your Daily")
                .font(AppTypography.title3)
                .foregroundColor(BrandColors.textPrimary)
            
            Text("Tell us what topics you love, the tone you prefer, and what you’d rather skip.")
                .font(AppTypography.subheadline)
                .foregroundColor(BrandColors.textSecondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, AppSpacing.lg)
        }
        .frame(maxWidth: .infinity)
        .padding(AppSpacing.xl)
        .glassCard()
        .padding(.horizontal, AppSpacing.lg)
    }
    
    var inputArea: some View {
        HStack(spacing: AppSpacing.sm) {
            TextField("Type your interests…", text: $viewModel.inputText, axis: .vertical)
                .font(AppTypography.body)
                .padding(.horizontal, AppSpacing.md)
                .padding(.vertical, AppSpacing.sm)
                .background(BrandColors.cardBackground.opacity(0.9))
                .cornerRadius(AppCornerRadius.large)
                .overlay(
                    RoundedRectangle(cornerRadius: AppCornerRadius.large)
                        .stroke(isInputFocused ? BrandColors.primary.opacity(0.3) : Color.clear, lineWidth: 1)
                )
                .lineLimit(1...5)
                .focused($isInputFocused)
                .onSubmit {
                    submit()
                }
            
            Button(action: {
                let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                impactFeedback.impactOccurred()
                submit()
            }) {
                ZStack {
                    Circle()
                        .fill(
                            viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading
                            ? BrandColors.textTertiary
                            : BrandColors.primary
                        )
                        .frame(width: 42, height: 42)
                    
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
    
    func submit() {
        guard !viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        Task {
            await viewModel.sendMessage()
        }
    }
}

// MARK: - Notifications

extension Notification.Name {
    static let onboardingCompleted = Notification.Name("OnboardingCompleted")
}



