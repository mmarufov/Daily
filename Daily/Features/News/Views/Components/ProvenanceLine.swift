//
//  ProvenanceLine.swift
//  Daily
//
//  The "FROM YOUR INTRO / BECAUSE YOU TUNED FOR" line — the user-authored signal made visible.
//  See DESIGN.md "Provenance Rules".
//

import SwiftUI

/// Small-caps ochre line shown only on the hero story (high confidence) or the
/// long-press "Why this story?" sheet. Truncates at 64 chars with ellipsis.
///
/// **Sanitization rules (non-negotiable, per DESIGN.md):**
/// - Never quote raw user input verbatim — always map to canonical topic via the taste model.
/// - Profanity, names, freeform text never appear in provenance strings.
/// - Recency labels are buckets only ("recently", "this month", "earlier"), never clock time.
///
/// TODO (post-Phase-1): Move sanitization into a `ProvenanceFormatter` once the taste model
/// exposes canonical-topic and confidence APIs. For now, callers pass already-sanitized strings.
struct ProvenanceLine: View {
    let text: String

    private static let maxLength = 64

    private var displayText: String {
        guard text.count > Self.maxLength else { return text }
        return String(text.prefix(Self.maxLength - 1)) + "…"
    }

    var body: some View {
        Text(displayText)
            .font(AppTypography.signatureCaps)
            .tracking(1.0)
            .textCase(.uppercase)
            .foregroundStyle(EditionPalette.ochre)
            .lineLimit(1)
            .accessibilityLabel("Why this story: \(displayText)")
    }
}

#Preview("Cold start — light") {
    ProvenanceLine(text: "FROM YOUR INTRO: TECH AND WORK")
        .padding()
        .background(EditionPalette.paper)
}

#Preview("Earned — light") {
    ProvenanceLine(text: "BECAUSE YOU TUNED FOR ERLANG TUE")
        .padding()
        .background(EditionPalette.paper)
}

#Preview("Truncation") {
    ProvenanceLine(text: "BECAUSE YOU TUNED FOR ERLANG, DISTRIBUTED SYSTEMS, AND VERY LONG TOPICS")
        .padding()
        .background(EditionPalette.paper)
}

#Preview("Earned — dark") {
    ProvenanceLine(text: "BECAUSE YOU TUNED FOR ERLANG TUE")
        .padding()
        .background(EditionPalette.paper)
        .preferredColorScheme(.dark)
}
