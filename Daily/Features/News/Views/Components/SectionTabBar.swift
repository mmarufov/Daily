//
//  SectionTabBar.swift
//  Daily
//
//  Horizontal scrollable section tabs for the news feed.
//

import SwiftUI

struct SectionTabBar: View {
    let topics: [String]
    @Binding var selectedSection: FeedSection

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: AppSpacing.sm) {
                chip(section: .general)
                chip(section: .all)

                ForEach(topics, id: \.self) { topic in
                    chip(section: .category(topic))
                }
            }
            .padding(.horizontal, AppSpacing.lg)
        }
    }

    private func chip(section: FeedSection) -> some View {
        let isSelected = selectedSection == section

        return Button {
            withAnimation(.easeInOut(duration: 0.2)) {
                selectedSection = section
            }
        } label: {
            Text(section.displayName)
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(isSelected ? .white : BrandColors.textPrimary)
                .padding(.horizontal, AppSpacing.md)
                .padding(.vertical, AppSpacing.sm)
                .background(
                    Capsule()
                        .fill(isSelected ? BrandColors.primary : Color(.secondarySystemGroupedBackground))
                )
                .overlay(
                    Capsule()
                        .stroke(
                            isSelected ? Color.clear : Color(.separator).opacity(0.3),
                            lineWidth: 0.5
                        )
                )
        }
    }
}
