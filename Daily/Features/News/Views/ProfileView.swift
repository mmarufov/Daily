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

    var body: some View {
        NavigationStack {
            ScrollView(.vertical, showsIndicators: false) {
                VStack(spacing: AppSpacing.xl) {
                    profileHeader
                    settingsSection
                    signOutButton
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
                    .foregroundColor(BrandColors.primary)
                }
            }
            .sheet(isPresented: $showPersonalizationSettings) {
                PersonalizationSettingsView()
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

    private var settingsSection: some View {
        Button(action: {
            HapticService.impact(.light)
            showPersonalizationSettings = true
        }) {
            HStack(spacing: AppSpacing.md) {
                Image(systemName: "person.text.rectangle")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundColor(BrandColors.primary)

                VStack(alignment: .leading, spacing: 2) {
                    Text("Personalization")
                        .font(AppTypography.body)
                        .foregroundColor(BrandColors.textPrimary)
                    Text("Fine-tune your briefing preferences")
                        .font(AppTypography.footnote)
                        .foregroundColor(BrandColors.textSecondary)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(BrandColors.textTertiary)
            }
            .padding(AppSpacing.md)
            .background(Color(.secondarySystemGroupedBackground))
            .clipShape(RoundedRectangle(cornerRadius: AppCornerRadius.medium, style: .continuous))
        }
    }

    private var signOutButton: some View {
        Button(action: {
            HapticService.impact(.medium)
            auth.signOut()
            dismiss()
        }) {
            Text("Sign Out")
                .font(AppTypography.body)
                .foregroundColor(BrandColors.error)
        }
        .frame(maxWidth: .infinity)
        .padding(.top, AppSpacing.md)
    }
}

#Preview {
    ProfileView()
}
