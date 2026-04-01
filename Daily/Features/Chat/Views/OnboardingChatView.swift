//
//  OnboardingChatView.swift
//  Daily
//
//  Full-screen onboarding chat for collecting user interests.
//

import SwiftUI

struct OnboardingChatView: View {
    @StateObject private var viewModel = OnboardingChatViewModel()
    @Environment(\.dismiss) private var dismiss
    @FocusState private var isInputFocused: Bool
    @State private var newLocation = ""
    @State private var newCurrentInterest = ""

    /// Called after preferences are successfully saved.
    var onCompleted: (() -> Void)?

    init(onCompleted: (() -> Void)? = nil) {
        self.onCompleted = onCompleted
    }

    private let suggestionChips: [(icon: String, text: String)] = [
        ("cpu", "Tech & AI"),
        ("chart.line.uptrend.xyaxis", "Business & Finance"),
        ("globe", "World News"),
        ("sportscourt", "Sports"),
    ]
    private let utilityOptions = ["Work", "Money", "Health", "Local", "Travel"]
    private let depthOptions: [(label: String, value: String)] = [("Quick", "breaking"), ("Balanced", "balanced"), ("Deep", "deep")]

    var body: some View {
        NavigationStack {
            ZStack {
                Color(.systemBackground).ignoresSafeArea()

                VStack(spacing: 0) {
                    ScrollViewReader { proxy in
                        ScrollView(.vertical, showsIndicators: false) {
                            LazyVStack(spacing: AppSpacing.md) {
                                introCard

                                if !viewModel.messages.isEmpty {
                                    ForEach(viewModel.messages) { message in
                                        ChatBubbleView(message: message)
                                            .padding(.horizontal, AppSpacing.md)
                                    }
                                }

                                if viewModel.messages.count <= 1 {
                                    chipSuggestions
                                }

                                quickContextCard

                                if viewModel.isLoading {
                                    HStack(spacing: AppSpacing.sm) {
                                        ProgressView()
                                            .tint(BrandColors.primary)
                                        Text("Thinking about your feed...")
                                            .font(AppTypography.bodySmall)
                                            .foregroundColor(BrandColors.textSecondary)
                                        Spacer()
                                    }
                                    .padding(.horizontal, AppSpacing.md)
                                    .padding(.vertical, AppSpacing.sm)
                                }
                            }
                            .padding(.top, AppSpacing.lg)
                            .padding(.bottom, AppSpacing.xl)
                        }
                        .onChange(of: viewModel.messages.count) { _, _ in
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

                    // Show save CTA after enough conversation
                    if viewModel.messages.count >= 2 && !viewModel.isSaving {
                        saveCTA
                    }

                    inputArea
                }
            }
            .navigationTitle("Welcome to Daily")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Close") {
                        dismiss()
                    }
                    .font(AppTypography.body)
                }
            }
            .task {
                viewModel.startConversation()
            }
        }
    }
}

private extension OnboardingChatView {
    var introCard: some View {
        VStack(spacing: AppSpacing.md) {
            Text("Personalize your feed")
                .font(AppTypography.title3)
                .foregroundColor(BrandColors.textPrimary)

            Text("Tell me what you're interested in and I'll curate news that actually matters to you.")
                .font(AppTypography.subheadline)
                .foregroundColor(BrandColors.textSecondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, AppSpacing.lg)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, AppSpacing.xxl)
        .padding(.horizontal, AppSpacing.lg)
    }

    var chipSuggestions: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: AppSpacing.sm) {
                ForEach(suggestionChips, id: \.text) { chip in
                    Button {
                        HapticService.impact(.light)
                        viewModel.inputText = "I'm interested in \(chip.text.lowercased())"
                        submit()
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: chip.icon)
                                .font(AppTypography.chipIcon)
                                .foregroundColor(BrandColors.primary)
                            Text(chip.text)
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

    var saveCTA: some View {
        Button {
            HapticService.impact(.medium)
            Task { await saveAndComplete() }
        } label: {
            HStack(spacing: AppSpacing.sm) {
                Image(systemName: "checkmark.circle.fill")
                    .font(AppTypography.headlineMedium)
                Text("That's all, show me my feed")
                    .font(AppTypography.labelLarge)
            }
            .foregroundColor(.white)
            .frame(maxWidth: .infinity)
            .padding(.vertical, AppSpacing.md)
            .background(BrandColors.primary)
            .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.button, style: .continuous))
        }
        .padding(.horizontal, AppSpacing.md)
        .padding(.bottom, AppSpacing.xs)
        .transition(.move(edge: .bottom).combined(with: .opacity))
        .animation(.easeInOut(duration: 0.3), value: viewModel.messages.count)
    }

    var quickContextCard: some View {
        VStack(alignment: .leading, spacing: AppSpacing.md) {
            Text("Fine-tune what matters")
                .font(AppTypography.headline)
                .foregroundColor(BrandColors.textPrimary)

            FlowLayout(spacing: AppSpacing.sm) {
                ForEach(utilityOptions, id: \.self) { option in
                    let isSelected = viewModel.utilityPriorities.contains(option)
                    Button {
                        if let index = viewModel.utilityPriorities.firstIndex(of: option) {
                            viewModel.utilityPriorities.remove(at: index)
                        } else {
                            viewModel.utilityPriorities.append(option)
                        }
                    } label: {
                        Text(option)
                            .font(AppTypography.caption1)
                            .foregroundColor(isSelected ? .white : BrandColors.textPrimary)
                            .padding(.horizontal, AppSpacing.md)
                            .padding(.vertical, AppSpacing.sm)
                            .background(isSelected ? BrandColors.primary : BrandColors.cardBackground.opacity(0.9))
                            .clipShape(Capsule())
                    }
                }
            }

            Picker("Depth", selection: $viewModel.contentDepth) {
                ForEach(depthOptions, id: \.value) { option in
                    Text(option.label).tag(option.value)
                }
            }
            .pickerStyle(.segmented)

            HStack(spacing: AppSpacing.sm) {
                TextField("Current focus", text: $newCurrentInterest)
                    .textFieldStyle(.roundedBorder)
                Button("Add") {
                    let trimmed = newCurrentInterest.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !trimmed.isEmpty, !viewModel.currentInterests.contains(trimmed) else { return }
                    viewModel.currentInterests.append(trimmed)
                    newCurrentInterest = ""
                }
                .disabled(newCurrentInterest.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }

            if !viewModel.currentInterests.isEmpty {
                ChipFlowView(items: viewModel.currentInterests) { item in
                    viewModel.currentInterests.removeAll { $0 == item }
                }
            }

            HStack(spacing: AppSpacing.sm) {
                TextField("Location relevance", text: $newLocation)
                    .textFieldStyle(.roundedBorder)
                Button("Add") {
                    let trimmed = newLocation.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !trimmed.isEmpty, !viewModel.locations.contains(trimmed) else { return }
                    viewModel.locations.append(trimmed)
                    newLocation = ""
                }
                .disabled(newLocation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }

            if !viewModel.locations.isEmpty {
                ChipFlowView(items: viewModel.locations) { item in
                    viewModel.locations.removeAll { $0 == item }
                }
            }

            TextField("Anything about your life or work we should consider?", text: $viewModel.lifeContext, axis: .vertical)
                .textFieldStyle(.roundedBorder)
                .lineLimit(2...4)
        }
        .padding(.horizontal, AppSpacing.md)
    }

    var inputArea: some View {
        HStack(spacing: AppSpacing.sm) {
            TextField("Type your interests...", text: $viewModel.inputText, axis: .vertical)
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
                HapticService.impact(.light)
                submit()
            }) {
                ZStack {
                    Circle()
                        .fill(
                            viewModel.inputText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || viewModel.isLoading
                            ? BrandColors.textTertiary
                            : BrandColors.primary
                        )
                        .frame(width: 44, height: 44)

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

    func saveAndComplete() async {
        do {
            try await viewModel.saveOnboardingPreferences()
            // Post notification so NewsViewModel starts the discovery → build flow
            // instead of dismissing immediately. The feed tab will show BuildingFeedView.
            NotificationCenter.default.post(name: .onboardingCompleted, object: nil)
            onCompleted?()
            dismiss()
        } catch {
            viewModel.errorMessage = "Couldn't save your preferences — please try again."
        }
    }
}

// MARK: - Notifications

extension Notification.Name {
    static let onboardingCompleted = Notification.Name("OnboardingCompleted")
    static let preferencesChanged = Notification.Name("PreferencesChanged")
}
