//
//  ProfileView.swift
//  Daily
//
//  Created by Muhammadjon on 3/11/25.
//

import SwiftUI
import UIKit

struct ProfileView: View {
    @ObservedObject private var auth = AuthService.shared
    @Environment(\.dismiss) private var dismiss
    @State private var showPersonalizationSettings = false
    
    var body: some View {
        NavigationStack {
            ZStack {
                AppleBackgroundView()
                
                ScrollView(.vertical, showsIndicators: false) {
                    VStack(spacing: AppSpacing.xl) {
                        profileHeader
                        settingsSection
                        signOutButton
                    }
                    .padding(.horizontal, AppSpacing.lg)
                    .padding(.vertical, AppSpacing.xl)
                }
            }
            .navigationTitle("Profile")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(.ultraThinMaterial, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.light, for: .navigationBar)
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
            ZStack {
                Circle()
                    .fill(LinearGradient(colors: [BrandColors.primary.opacity(0.25), BrandColors.primary], startPoint: .topLeading, endPoint: .bottomTrailing))
                    .frame(width: 130, height: 130)
                    .shadow(color: BrandColors.primary.opacity(0.25), radius: 25, x: 0, y: 15)
                
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
                                .foregroundColor(.white)
                        }
                    }
                    .frame(width: 110, height: 110)
                    .clipShape(Circle())
                    .overlay(Circle().stroke(Color.white.opacity(0.3), lineWidth: 2))
                } else {
                    Image(systemName: "person.crop.circle.fill")
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: 90, height: 90)
                        .foregroundColor(.white)
                }
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
        .padding(AppSpacing.xl)
        .glassCard()
    }
    
    private var settingsSection: some View {
        VStack(spacing: AppSpacing.md) {
            Button(action: {
                let impactFeedback = UIImpactFeedbackGenerator(style: .light)
                impactFeedback.impactOccurred()
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
                .padding(AppSpacing.lg)
                .glassCard(cornerRadius: AppCornerRadius.large)
            }
        }
    }
    
    private var signOutButton: some View {
        Button(action: {
            let impactFeedback = UIImpactFeedbackGenerator(style: .medium)
            impactFeedback.impactOccurred()
            auth.signOut()
            dismiss()
        }) {
            HStack(spacing: AppSpacing.sm) {
                Image(systemName: "arrow.right.square")
                    .font(.system(size: 16, weight: .medium))
                Text("Sign Out")
                    .font(AppTypography.labelLarge)
            }
            .foregroundColor(.white)
            .frame(maxWidth: .infinity)
            .frame(height: 52)
            .background(BrandColors.error)
            .cornerRadius(AppCornerRadius.button)
            .shadow(color: BrandColors.error.opacity(0.25), radius: 16, x: 0, y: 10)
        }
    }
}

#Preview {
    ProfileView()
}

