//
//  PersonalizationSettingsView.swift
//  Daily
//
//  Sheet that shows and lets the user edit the AI prompt used to personalize news.
//

import SwiftUI

struct PersonalizationSettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var viewModel = NewsPersonalizationViewModel()
    @State private var showAIChat = false
    
    var body: some View {
        NavigationView {
            ZStack {
                BrandColors.background.ignoresSafeArea()
                
                VStack(spacing: AppSpacing.md) {
                    // Description
                    VStack(alignment: .leading, spacing: AppSpacing.xs) {
                        Text("Personalized news prompt")
                            .font(AppTypography.title3)
                            .foregroundColor(BrandColors.textPrimary)
                        Text("This is the instruction the AI uses to pick news for you. You can fine-tune it to change what you see.")
                            .font(AppTypography.subheadline)
                            .foregroundColor(BrandColors.textSecondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, AppSpacing.md)
                    .padding(.top, AppSpacing.md)
                    
                    // Text editor
                    ZStack(alignment: .topLeading) {
                        RoundedRectangle(cornerRadius: AppCornerRadius.medium)
                            .fill(BrandColors.cardBackground)
                            .shadow(
                                color: AppShadows.card.color,
                                radius: AppShadows.card.radius,
                                x: AppShadows.card.x,
                                y: AppShadows.card.y
                            )
                        
                        TextEditor(text: $viewModel.promptText)
                            .font(AppTypography.body)
                            .padding(AppSpacing.md)
                            .foregroundColor(BrandColors.textPrimary)
                    }
                    .frame(maxWidth: .infinity)
                    .frame(minHeight: 200, maxHeight: 320)
                    .padding(.horizontal, AppSpacing.md)
                    
                    // Continue with AI button
                    Button(action: {
                        let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                        impactFeedback.impactOccurred()
                        showAIChat = true
                    }) {
                        HStack(spacing: AppSpacing.sm) {
                            Image(systemName: "bubble.left.and.bubble.right.fill")
                                .font(.system(size: 15, weight: .medium))
                            Text("Refine with AI conversation")
                                .font(AppTypography.labelLarge)
                        }
                        .foregroundColor(BrandColors.primary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, AppSpacing.sm)
                        .padding(.horizontal, AppSpacing.md)
                        .background(BrandColors.primary.opacity(0.08))
                        .cornerRadius(AppCornerRadius.medium)
                    }
                    .padding(.horizontal, AppSpacing.md)
                    
                    if let error = viewModel.errorMessage {
                        HStack(spacing: AppSpacing.sm) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundColor(BrandColors.error)
                            Text(error)
                                .font(AppTypography.footnote)
                                .foregroundColor(BrandColors.error)
                        }
                        .padding(.horizontal, AppSpacing.md)
                    }
                    
                    Spacer()
                }
                
                if viewModel.isLoading {
                    ProgressView("Loading...")
                        .padding()
                        .background(BrandColors.cardBackground)
                        .cornerRadius(AppCornerRadius.medium)
                        .shadow(
                            color: AppShadows.large.color,
                            radius: AppShadows.large.radius,
                            x: AppShadows.large.x,
                            y: AppShadows.large.y
                        )
                }
            }
            .navigationTitle("Personalization")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
                
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        Task {
                            let success = await viewModel.save()
                            if success {
                                // Re-fetch personalized news right away
                                NotificationCenter.default.post(name: .onboardingCompleted, object: nil)
                                dismiss()
                            }
                        }
                    } label: {
                        if viewModel.isSaving {
                            ProgressView()
                                .progressViewStyle(CircularProgressViewStyle(tint: BrandColors.primary))
                        } else {
                            Text("Save")
                                .font(AppTypography.body)
                        }
                    }
                    .disabled(viewModel.isSaving)
                }
            }
        }
        .task {
            await viewModel.load()
        }
        .sheet(isPresented: $showAIChat) {
            OnboardingChatView {
                // When user finishes another AI chat round, update local prompt view
                Task {
                    await viewModel.load()
                }
            }
        }
    }
}


