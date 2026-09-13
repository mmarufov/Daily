//
//  ProfileView.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI

struct ProfileView: View {
    @ObservedObject private var auth = AuthService.shared
    @Environment(\.dismiss) private var dismiss
    @State private var showPersonalizationSettings = false
    @State private var showSignOutConfirmation = false
    @State private var showDeleteConfirmation = false
    @State private var isDeleting = false
    @State private var deleteErrorMessage: String?

    var body: some View {
        NavigationStack {
            ScrollView(.vertical, showsIndicators: false) {
                VStack(spacing: AppSpacing.xl) {
                    profileHeader

                    // Settings rows
                    VStack(spacing: 0) {
                        settingsRow(
                            icon: "person.text.rectangle",
                            title: "Personalization",
                            subtitle: "Fine-tune your briefing preferences"
                        ) {
                            HapticService.impact(.light)
                            showPersonalizationSettings = true
                        }

                        HairlineDivider()
                            .padding(.leading, 56)

                        settingsRow(
                            icon: "textformat.size",
                            title: "Text Size",
                            subtitle: "Adjust article reading size"
                        ) {
                            // Handled via ArticleDetailView text size menu
                        }

                        HairlineDivider()
                            .padding(.leading, 56)

                        settingsRow(
                            icon: "bell",
                            title: "Notifications",
                            subtitle: "Coming soon"
                        ) {
                            // Placeholder
                        }
                    }
                    .background(Color(.secondarySystemGroupedBackground))
                    .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous))

                    // Sign out
                    Button {
                        HapticService.impact(.medium)
                        showSignOutConfirmation = true
                    } label: {
                        HStack {
                            Image(systemName: "rectangle.portrait.and.arrow.right")
                                .font(AppTypography.iconButton)
                            Text("Sign Out")
                                .font(AppTypography.body)
                        }
                        .foregroundColor(BrandColors.error)
                        .frame(maxWidth: .infinity)
                        .padding(AppSpacing.md)
                        .background(Color(.secondarySystemGroupedBackground))
                        .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous))
                    }

                    deleteAccountButton

                    // Version
                    Text("Daily v\(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0")")
                        .font(AppTypography.caption2)
                        .foregroundColor(BrandColors.textQuaternary)
                        .padding(.top, AppSpacing.md)
                }
                .padding(.horizontal, AppSpacing.lg)
                .padding(.vertical, AppSpacing.xl)
            }
            .background(Color(.systemGroupedBackground))
            .navigationTitle("Profile")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                    .font(AppTypography.body)
                }
            }
            .sheet(isPresented: $showPersonalizationSettings) {
                PersonalizationSettingsView()
            }
            .alert("Sign Out", isPresented: $showSignOutConfirmation) {
                Button("Cancel", role: .cancel) {}
                Button("Sign Out", role: .destructive) {
                    auth.signOut()
                    dismiss()
                }
            } message: {
                Text("Are you sure you want to sign out?")
            }
            .alert("Delete Account", isPresented: $showDeleteConfirmation) {
                Button("Cancel", role: .cancel) {}
                Button("Delete", role: .destructive) { deleteAccount() }
            } message: {
                Text("This permanently deletes your account, your saved stories and everything Daily has learned about your reading. It can't be undone.")
            }
            .alert("Couldn't Delete Account",
                   isPresented: Binding(get: { deleteErrorMessage != nil },
                                        set: { if !$0 { deleteErrorMessage = nil } })) {
                Button("OK", role: .cancel) { deleteErrorMessage = nil }
            } message: {
                Text(deleteErrorMessage ?? "")
            }
        }
    }

    /// Apple requires an in-app path to delete the account for any app that
    /// offers account creation (App Store Review Guideline 5.1.1(v)). Kept
    /// visually quieter than Sign Out — destructive, but not a trap.
    private var deleteAccountButton: some View {
        Button {
            HapticService.impact(.medium)
            showDeleteConfirmation = true
        } label: {
            HStack(spacing: AppSpacing.xs) {
                if isDeleting {
                    ProgressView().controlSize(.small)
                }
                Text(isDeleting ? "Deleting…" : "Delete Account")
                    .font(AppTypography.footnote)
            }
            .foregroundColor(BrandColors.textTertiary)
            .frame(maxWidth: .infinity)
            .padding(.vertical, AppSpacing.sm)
        }
        .disabled(isDeleting)
        .accessibilityHint("Permanently deletes your account and all of its data")
    }

    private func deleteAccount() {
        isDeleting = true
        Task {
            defer { isDeleting = false }
            do {
                try await auth.deleteAccount()
                dismiss()
            } catch {
                deleteErrorMessage = (error as? LocalizedError)?.errorDescription
                    ?? "Couldn't reach the server. Please try again."
            }
        }
    }

    private var profileHeader: some View {
        VStack(spacing: AppSpacing.md) {
            if let photoURL = auth.currentUser?.photo_url,
               let url = URL(string: photoURL) {
                AsyncImage(url: url) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .aspectRatio(contentMode: .fill)
                    default:
                        Image(systemName: "person.crop.circle.fill")
                            .resizable()
                            .aspectRatio(contentMode: .fit)
                            .foregroundColor(BrandColors.textTertiary)
                    }
                }
                .frame(width: 80, height: 80)
                .clipShape(Circle())
                .overlay(Circle().stroke(Color(.separator), lineWidth: 0.5))
            } else {
                Image(systemName: "person.crop.circle.fill")
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 80, height: 80)
                    .foregroundColor(BrandColors.textTertiary)
            }

            VStack(spacing: AppSpacing.xs) {
                if let displayName = auth.currentUser?.display_name {
                    Text(displayName)
                        .font(AppTypography.title2)
                        .foregroundColor(BrandColors.textPrimary)
                }

                if let email = auth.currentUser?.email {
                    Text(email)
                        .font(AppTypography.subheadline)
                        .foregroundColor(BrandColors.textSecondary)
                }
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, AppSpacing.lg)
    }

    private func settingsRow(icon: String, title: String, subtitle: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            HStack(spacing: AppSpacing.md) {
                Image(systemName: icon)
                    .font(AppTypography.iconButton)
                    .foregroundColor(BrandColors.textSecondary)
                    .frame(width: 24)

                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(AppTypography.body)
                        .foregroundColor(BrandColors.textPrimary)
                    Text(subtitle)
                        .font(AppTypography.footnote)
                        .foregroundColor(BrandColors.textSecondary)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(AppTypography.navIcon)
                    .foregroundColor(BrandColors.textTertiary)
            }
            .padding(AppSpacing.md)
        }
    }
}

#Preview {
    ProfileView()
}
