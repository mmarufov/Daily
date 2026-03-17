//
//  CategoryFilterBar.swift
//  Daily
//

import SwiftUI

struct CategoryFilterBar: View {
    let categories: [String]
    @Binding var selectedCategory: String?

    var body: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: AppSpacing.sm) {
                chip(title: "All", isSelected: selectedCategory == nil) {
                    HapticService.selection()
                    withAnimation(.easeInOut(duration: 0.2)) {
                        selectedCategory = nil
                    }
                }

                ForEach(categories, id: \.self) { category in
                    chip(title: category.capitalized, isSelected: selectedCategory == category) {
                        HapticService.selection()
                        withAnimation(.easeInOut(duration: 0.2)) {
                            selectedCategory = (selectedCategory == category) ? nil : category
                        }
                    }
                }
            }
            .padding(.horizontal, AppSpacing.lg)
        }
    }

    private func chip(title: String, isSelected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
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
