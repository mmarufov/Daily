//
//  PersonalizationSettingsView.swift
//  Daily
//
//  Structured personalization settings with topic chips, content style,
//  expertise level, and exclusions. Raw prompt behind Advanced toggle.
//

import SwiftUI

struct PersonalizationSettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var viewModel = NewsPersonalizationViewModel()
    @State private var showAIChat = false
    @State private var showAdvanced = false
    @State private var confirmsReset = false
    @State private var newTopic = ""
    @State private var newCurrentInterest = ""
    @State private var newLocation = ""
    @State private var newExclusion = ""
    @State private var newEntityPin = ""
    @State private var contentStyle: Double = 1 // 0=Breaking, 1=Balanced, 2=Deep
    @State private var expertiseLevel: Double = 1 // 0=Casual, 1=Intermediate, 2=Expert

    private let contentStyleLabels = ["Breaking News", "Balanced", "Deep Analysis"]
    private let expertiseLabels = ["Casual", "Intermediate", "Expert"]
    private let utilityPriorityOptions = ["Work", "Money", "Health", "Local", "Travel", "Family"]

    var body: some View {
        NavigationStack {
            ScrollView(.vertical, showsIndicators: false) {
                VStack(alignment: .leading, spacing: AppSpacing.xl) {
                    if let reader = viewModel.reader {
                        if reader.needsReview {
                            Text("These interests were imported from your previous profile. Review them before enabling the new reader model.")
                                .font(AppTypography.footnote)
                            Toggle("I reviewed my interests and exclusions", isOn: $viewModel.confirmsMigration)
                        }
                        Button("Reset learned preferences") { confirmsReset = true }
                            .disabled(viewModel.isSaving)
                        Text("Keeps your explicit interests and exclusions; clears learned influence.")
                            .font(AppTypography.caption1)
                        if !reader.profile.policies.filter({ $0.kind != "lexical" && !viewModel.removedPolicyIDs.contains($0.id) }).isEmpty {
                            sectionBlock(title: "Other Reader Rules") {
                                ForEach(reader.profile.policies.filter { $0.kind != "lexical" && !viewModel.removedPolicyIDs.contains($0.id) }) { policy in
                                    HStack {
                                        Text("\(policy.kind): \(policy.value)").font(AppTypography.caption1)
                                        Spacer()
                                        Button("Remove") { viewModel.removedPolicyIDs.insert(policy.id) }
                                    }
                                }
                            }
                        }
                    }
                    // Your Interests
                    sectionBlock(title: "Your Interests") {
                        ChipFlowView(
                            items: viewModel.topics,
                            onRemove: { item in viewModel.topics.removeAll { $0 == item } }
                        )

                        HStack(spacing: AppSpacing.sm) {
                            TextField("Add topic...", text: $newTopic)
                                .font(AppTypography.body)
                                .textFieldStyle(.roundedBorder)
                                .onSubmit { addTopic() }

                            Button("Add") { addTopic() }
                                .font(AppTypography.labelMedium)
                                .foregroundColor(BrandColors.primary)
                                .disabled(newTopic.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                    }

                    sectionBlock(title: "Current Focus") {
                        if !viewModel.currentInterests.isEmpty {
                            ChipFlowView(
                                items: viewModel.currentInterests,
                                onRemove: { item in viewModel.currentInterests.removeAll { $0 == item } }
                            )
                        }

                        HStack(spacing: AppSpacing.sm) {
                            TextField("What matters right now?", text: $newCurrentInterest)
                                .font(AppTypography.body)
                                .textFieldStyle(.roundedBorder)
                                .onSubmit { addCurrentInterest() }

                            Button("Add") { addCurrentInterest() }
                                .font(AppTypography.labelMedium)
                                .foregroundColor(BrandColors.primary)
                                .disabled(newCurrentInterest.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                    }

                    // S10 batch E: reachable for the first time -- the
                    // backend and BackendService methods already existed.
                    // Legacy-serving only (see viewModel.load()).
                    if viewModel.reader == nil {
                        sectionBlock(title: "Pinned People & Companies") {
                            Text("A pinned entity gets a boost whenever it appears in a story's title or summary.")
                                .font(AppTypography.caption1)
                                .foregroundColor(BrandColors.textTertiary)
                            if !viewModel.entityPins.isEmpty {
                                ChipFlowView(
                                    items: viewModel.entityPins.map(\.name),
                                    onRemove: { name in
                                        guard let pin = viewModel.entityPins.first(where: { $0.name == name }) else { return }
                                        Task { await viewModel.removeEntityPin(pin) }
                                    }
                                )
                            }
                            HStack(spacing: AppSpacing.sm) {
                                TextField("Add a person or company...", text: $newEntityPin)
                                    .font(AppTypography.body)
                                    .textFieldStyle(.roundedBorder)
                                    .onSubmit { addEntityPin() }

                                Button("Add") { addEntityPin() }
                                    .font(AppTypography.labelMedium)
                                    .foregroundColor(BrandColors.primary)
                                    .disabled(newEntityPin.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                        || viewModel.entityPins.count >= 20)
                            }
                            if let entityError = viewModel.entityPinErrorMessage {
                                Text(entityError)
                                    .font(AppTypography.caption1)
                                    .foregroundColor(BrandColors.error)
                            }
                        }

                        if !viewModel.interestSuggestions.isEmpty {
                            sectionBlock(title: "Noticed a pattern") {
                                Text("Based on what you've been reading. Add it, or dismiss if it's not a real interest.")
                                    .font(AppTypography.caption1)
                                    .foregroundColor(BrandColors.textTertiary)
                                ForEach(viewModel.interestSuggestions) { suggestion in
                                    HStack {
                                        Text(suggestion.topic)
                                            .font(AppTypography.body)
                                            .foregroundColor(BrandColors.textPrimary)
                                        Spacer()
                                        Button("Dismiss") { Task { await viewModel.dismissInterestSuggestion(suggestion) } }
                                            .font(AppTypography.caption1)
                                            .foregroundColor(BrandColors.textTertiary)
                                        Button("Add") { Task { await viewModel.acceptInterestSuggestion(suggestion) } }
                                            .font(AppTypography.labelMedium)
                                            .foregroundColor(BrandColors.primary)
                                    }
                                    .padding(.vertical, AppSpacing.xs)
                                }
                            }
                        }
                    }

                    sectionBlock(title: "Life Priorities") {
                        FlowLayout(spacing: AppSpacing.sm) {
                            ForEach(utilityPriorityOptions, id: \.self) { option in
                                let isSelected = viewModel.utilityPriorities.contains(option)
                                Button {
                                    toggleUtilityPriority(option)
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
                    }

                    // Content Style
                    sectionBlock(title: "Content Style") {
                        VStack(spacing: AppSpacing.sm) {
                            Slider(value: $contentStyle, in: 0...2, step: 1)
                                .tint(BrandColors.primary)

                            HStack {
                                ForEach(contentStyleLabels, id: \.self) { label in
                                    Text(label)
                                        .font(AppTypography.caption1)
                                        .foregroundColor(BrandColors.textTertiary)
                                        .frame(maxWidth: .infinity)
                                }
                            }
                        }
                    }

                    sectionBlock(title: "Location Relevance") {
                        if !viewModel.locations.isEmpty {
                            ChipFlowView(
                                items: viewModel.locations,
                                onRemove: { item in viewModel.locations.removeAll { $0 == item } }
                            )
                        }

                        HStack(spacing: AppSpacing.sm) {
                            TextField("Add city, country, or region...", text: $newLocation)
                                .font(AppTypography.body)
                                .textFieldStyle(.roundedBorder)
                                .onSubmit { addLocation() }

                            Button("Add") { addLocation() }
                                .font(AppTypography.labelMedium)
                                .foregroundColor(BrandColors.primary)
                                .disabled(newLocation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                    }

                    sectionBlock(title: "Life Context") {
                        TextEditor(text: $viewModel.lifeContext)
                            .font(AppTypography.body)
                            .foregroundColor(BrandColors.textPrimary)
                            .frame(minHeight: 96, maxHeight: 160)
                            .padding(AppSpacing.sm)
                            .background(Color(.secondarySystemGroupedBackground))
                            .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous))
                    }

                    // Expertise Level
                    sectionBlock(title: "Expertise Level") {
                        VStack(spacing: AppSpacing.sm) {
                            Slider(value: $expertiseLevel, in: 0...2, step: 1)
                                .tint(BrandColors.primary)

                            HStack {
                                ForEach(expertiseLabels, id: \.self) { label in
                                    Text(label)
                                        .font(AppTypography.caption1)
                                        .foregroundColor(BrandColors.textTertiary)
                                        .frame(maxWidth: .infinity)
                                }
                            }
                        }
                    }

                    // Excluded Topics
                    sectionBlock(title: viewModel.reader == nil ? "Excluded Topics" : "Hidden Phrases") {
                        if viewModel.reader != nil {
                            Text("Hides titles and summaries containing these exact phrases. This is not a semantic topic ban.")
                                .font(AppTypography.caption1)
                        }
                        if !viewModel.exclusions.isEmpty {
                            ChipFlowView(
                                items: viewModel.exclusions,
                                onRemove: { item in viewModel.exclusions.removeAll { $0 == item } }
                            )
                        }

                        HStack(spacing: AppSpacing.sm) {
                            TextField("Add exclusion...", text: $newExclusion)
                                .font(AppTypography.body)
                                .textFieldStyle(.roundedBorder)
                                .onSubmit { addExclusion() }

                            Button("Add") { addExclusion() }
                                .font(AppTypography.labelMedium)
                                .foregroundColor(BrandColors.primary)
                                .disabled(newExclusion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                        }
                    }

                    // Advanced — raw prompt
                    if viewModel.reader == nil { VStack(alignment: .leading, spacing: AppSpacing.sm) {
                        Button {
                            withAnimation(.easeInOut(duration: 0.2)) {
                                showAdvanced.toggle()
                            }
                        } label: {
                            HStack(spacing: AppSpacing.xs) {
                                Image(systemName: showAdvanced ? "chevron.down" : "chevron.right")
                                    .font(AppTypography.caption1)
                                Text("Advanced")
                                    .font(AppTypography.labelMedium)
                            }
                            .foregroundColor(BrandColors.textSecondary)
                        }

                        if showAdvanced {
                            Text("Raw AI prompt — edits here override the structured controls above.")
                                .font(AppTypography.caption1)
                                .foregroundColor(BrandColors.textTertiary)

                            TextEditor(text: $viewModel.promptText)
                                .font(AppTypography.body)
                                .foregroundColor(BrandColors.textPrimary)
                                .frame(minHeight: 160, maxHeight: 280)
                                .padding(AppSpacing.sm)
                                .background(Color(.secondarySystemGroupedBackground))
                                .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous))
                        }
                    } }

                    // Refine with AI
                    Button {
                        HapticService.impact(.light)
                        showAIChat = true
                    } label: {
                        HStack(spacing: AppSpacing.sm) {
                            Image(systemName: "bubble.left.and.bubble.right.fill")
                                .font(AppTypography.actionIcon)
                            Text("Refine with AI conversation")
                                .font(AppTypography.labelLarge)
                        }
                        .foregroundColor(BrandColors.primary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, AppSpacing.md)
                        .background(BrandColors.primary.opacity(0.08))
                        .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.button, style: .continuous))
                    }

                    if let error = viewModel.errorMessage {
                        HStack(spacing: AppSpacing.sm) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundColor(BrandColors.error)
                            Text(error)
                                .font(AppTypography.footnote)
                                .foregroundColor(BrandColors.error)
                        }
                    }
                }
                .padding(.horizontal, AppSpacing.lg)
                .padding(.top, AppSpacing.md)
                .padding(.bottom, AppSpacing.xxl)
            }
            .background(Color(.systemBackground))
            .navigationTitle("Personalization")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Cancel") { dismiss() }
                }

                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        Task {
                            composePromptFromStructuredInputs()
                            let success = await viewModel.save()
                            if success {
                                // Trigger source re-discovery + feed rebuild (not just cache reload)
                                if viewModel.reader == nil {
                                    NotificationCenter.default.post(name: .preferencesChanged, object: nil)
                                }
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
                    .disabled(viewModel.isSaving || viewModel.isLoading)
                }
            }
            .overlay {
                if viewModel.isLoading {
                    ProgressView("Loading...")
                        .padding()
                        .background(Color(.secondarySystemGroupedBackground))
                        .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous))
                }
            }
        }
        .task {
            await viewModel.load()
            parseStructuredInputsFromPrompt()
        }
        .sheet(isPresented: $showAIChat) {
            OnboardingChatView {
                Task { await viewModel.load() }
            }
        }
        .confirmationDialog("Reset learned preferences?", isPresented: $confirmsReset, titleVisibility: .visible) {
            Button("Reset learned preferences", role: .destructive) { Task { await viewModel.resetLearning() } }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Your explicit interests and rules stay. Learned feedback and reading history used for personalization will be cleared.")
        }
    }

    // MARK: - Helpers

    private func sectionBlock<Content: View>(title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: AppSpacing.md) {
            Text(title)
                .font(AppTypography.headline)
                .foregroundColor(BrandColors.textPrimary)
            content()
        }
    }

    private func addTopic() {
        let trimmed = newTopic.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !viewModel.topics.contains(trimmed) else { return }
        viewModel.topics.append(trimmed)
        newTopic = ""
    }

    private func addExclusion() {
        let trimmed = newExclusion.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !viewModel.exclusions.contains(trimmed) else { return }
        viewModel.exclusions.append(trimmed)
        newExclusion = ""
    }

    private func addEntityPin() {
        let trimmed = newEntityPin.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        newEntityPin = ""
        Task { await viewModel.addEntityPin(name: trimmed) }
    }

    private func composePromptFromStructuredInputs() {
        viewModel.contentDepth = ["breaking", "balanced", "deep"][Int(contentStyle)]
        if viewModel.reader != nil { return }
        guard !showAdvanced else { return } // If advanced is open, user edits prompt directly
        var parts: [String] = []

        if !viewModel.topics.isEmpty {
            parts.append("Interested in: \(viewModel.topics.joined(separator: ", "))")
        }
        if !viewModel.currentInterests.isEmpty {
            parts.append("Current focus: \(viewModel.currentInterests.joined(separator: ", "))")
        }
        if !viewModel.utilityPriorities.isEmpty {
            parts.append("This matters to my life: \(viewModel.utilityPriorities.joined(separator: ", "))")
        }
        if !viewModel.locations.isEmpty {
            parts.append("Location relevance: \(viewModel.locations.joined(separator: ", "))")
        }
        parts.append("Content preference: \(contentStyleLabels[Int(contentStyle)])")
        parts.append("Expertise level: \(expertiseLabels[Int(expertiseLevel)])")
        if !viewModel.exclusions.isEmpty {
            parts.append("Exclude: \(viewModel.exclusions.joined(separator: ", "))")
        }
        if !viewModel.lifeContext.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            parts.append("Context: \(viewModel.lifeContext.trimmingCharacters(in: .whitespacesAndNewlines))")
        }
        viewModel.promptText = parts.joined(separator: ". ") + "."
        viewModel.contentDepth = ["breaking", "balanced", "deep"][Int(contentStyle)]
    }

    private func parseStructuredInputsFromPrompt() {
        let text = viewModel.promptText.lowercased()
        // Simple heuristic: detect content style
        if text.contains("breaking") { contentStyle = 0 }
        else if text.contains("deep") || text.contains("analysis") { contentStyle = 2 }
        else { contentStyle = 1 }

        // Detect expertise
        if text.contains("expert") || text.contains("technical") { expertiseLevel = 2 }
        else if text.contains("casual") || text.contains("beginner") { expertiseLevel = 0 }
        else { expertiseLevel = 1 }

        switch viewModel.contentDepth {
        case "breaking": contentStyle = 0
        case "deep": contentStyle = 2
        default: contentStyle = 1
        }
    }

    private func addCurrentInterest() {
        let trimmed = newCurrentInterest.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !viewModel.currentInterests.contains(trimmed) else { return }
        viewModel.currentInterests.append(trimmed)
        newCurrentInterest = ""
    }

    private func addLocation() {
        let trimmed = newLocation.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, !viewModel.locations.contains(trimmed) else { return }
        viewModel.locations.append(trimmed)
        newLocation = ""
    }

    private func toggleUtilityPriority(_ option: String) {
        if let index = viewModel.utilityPriorities.firstIndex(of: option) {
            viewModel.utilityPriorities.remove(at: index)
        } else {
            viewModel.utilityPriorities.append(option)
        }
    }
}

// MARK: - Chip Flow View

struct ChipFlowView: View {
    let items: [String]
    let onRemove: (String) -> Void

    var body: some View {
        FlowLayout(spacing: AppSpacing.sm) {
            ForEach(items, id: \.self) { item in
                HStack(spacing: AppSpacing.xs) {
                    Text(item)
                        .font(AppTypography.chipLabel)
                        .foregroundColor(BrandColors.textPrimary)

                    Button {
                        HapticService.selection()
                        onRemove(item)
                    } label: {
                        Image(systemName: "xmark")
                            .font(AppTypography.metaLabel)
                            .foregroundColor(BrandColors.textTertiary)
                    }
                }
                .padding(.horizontal, AppSpacing.smLg)
                .padding(.vertical, AppSpacing.sm)
                .background(Color(.secondarySystemGroupedBackground))
                .clipShape(Capsule())
            }
        }
    }
}

// MARK: - Flow Layout

struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let result = layout(proposal: proposal, subviews: subviews)
        return result.size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = layout(proposal: proposal, subviews: subviews)
        for (index, subview) in subviews.enumerated() {
            guard index < result.positions.count else { break }
            subview.place(at: CGPoint(
                x: bounds.minX + result.positions[index].x,
                y: bounds.minY + result.positions[index].y
            ), proposal: .unspecified)
        }
    }

    private func layout(proposal: ProposedViewSize, subviews: Subviews) -> (size: CGSize, positions: [CGPoint]) {
        let maxWidth = proposal.width ?? .infinity
        var positions: [CGPoint] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x + size.width > maxWidth && x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }
            positions.append(CGPoint(x: x, y: y))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
        }

        return (CGSize(width: maxWidth, height: y + rowHeight), positions)
    }
}
