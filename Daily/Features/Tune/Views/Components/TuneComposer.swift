//
//  TuneComposer.swift
//  Daily
//
//  Top-pinned composer for the Tune surface. Rounded text input with 1pt
//  sepia border, italic ink60 placeholder, 46pt circle send button
//  (ink-blue, white up-arrow icon).
//

import SwiftUI

struct TuneComposer: View {
    @Binding var text: String
    var isStreaming: Bool = false
    var onSend: () -> Void

    @FocusState private var isFocused: Bool

    private var sendDisabled: Bool {
        text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isStreaming
    }

    var body: some View {
        HStack(alignment: .center, spacing: AppSpacing.sm) {
            inputField
            sendButton
        }
        .padding(.horizontal, AppSpacing.md)
        .padding(.vertical, AppSpacing.sm)
    }

    private var inputField: some View {
        ZStack(alignment: .topLeading) {
            if text.isEmpty {
                Text("Tell me what to read more or less of.")
                    .font(AppTypography.composer)
                    .italic()
                    .foregroundStyle(EditionPalette.ink60)
                    .padding(.horizontal, AppSpacing.smLg)
                    .padding(.vertical, AppSpacing.sm + 2)
                    .allowsHitTesting(false)
            }
            TextField("", text: $text, axis: .vertical)
                .font(AppTypography.composer)
                .foregroundStyle(EditionPalette.ink)
                .lineLimit(1...4)
                .padding(.horizontal, AppSpacing.smLg)
                .padding(.vertical, AppSpacing.sm)
                .focused($isFocused)
                .onSubmit { onSend() }
        }
        .background(
            RoundedRectangle(cornerRadius: AppCornerRadius.button, style: .continuous)
                .fill(EditionPalette.paper)
                .overlay(
                    RoundedRectangle(cornerRadius: AppCornerRadius.button, style: .continuous)
                        .stroke(EditionPalette.sepia, lineWidth: 1)
                )
        )
    }

    private var sendButton: some View {
        Button(action: {
            HapticService.impact(.medium)
            onSend()
        }) {
            ZStack {
                Circle()
                    .fill(EditionPalette.inkBlue)
                Image(systemName: "arrow.up")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(.white)
            }
            .frame(width: 46, height: 46)
        }
        .disabled(sendDisabled)
        .opacity(sendDisabled ? 0.5 : 1.0)
        .accessibilityLabel("Send tuning instruction")
    }
}

#Preview("Empty") {
    @Previewable @State var text = ""
    return VStack {
        TuneComposer(text: $text, onSend: {})
        Spacer()
    }
    .background(EditionPalette.paper)
}

#Preview("Filled") {
    @Previewable @State var text = "less national news, more startups"
    return VStack {
        TuneComposer(text: $text, onSend: {})
        Spacer()
    }
    .background(EditionPalette.paper)
}
